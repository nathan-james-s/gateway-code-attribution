"""Portal: sign-in, credential issue/revoke, setup page, per-line view (T048-T051)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_portal.app import COOKIE, create_app
from gca_portal.backends import ActiveKey, render_agentgateway_config
from gca_portal.config import PortalConfig
from gca_portal.credentials import key_hash

BASE = """
binds:
- port: 4000
llm:
  policies:
    apiKey:
      mode: strict
      keys: []
  models:
  - name: demo-openai
    provider: openAI
"""


class FakeBackend:
    def __init__(self) -> None:
        self.issued: list[str] = []
        self.revoked: list[str] = []
        self.synced: list[list[ActiveKey]] = []

    def issue(self, credential_id: str, github_id: int, key: str, key_hash: str) -> str | None:
        self.issued.append(credential_id)
        return f"ref/{credential_id}"

    def revoke(self, credential_id: str, gateway_ref: str | None) -> None:
        self.revoked.append(credential_id)

    def sync(self, active: list[ActiveKey]) -> None:
        self.synced.append(list(active))

    def ensure(self) -> None:
        return None


class FakeUser:
    def __init__(self, gid: int, login: str, repos: set[str]) -> None:
        self.gid, self.login, self.repos, self.token = gid, login, repos, f"tok-{login}"

    async def me(self) -> dict[str, Any]:
        return {"id": self.gid, "login": self.login}

    async def can_view_repo(self, owner: str, repo: str) -> bool:
        return f"{owner}/{repo}" in self.repos


@pytest.fixture
def client(pg_engine: Engine) -> tuple[TestClient, FakeBackend, FakeUser]:
    gid = 7_000_000 + uuid.uuid4().int % 1_000_000
    user = FakeUser(gid, f"dev{gid}", {"acme/widgets"})
    backend = FakeBackend()

    async def exchange(cid: str, secret: str, code: str, redirect_uri: str | None = None) -> FakeUser:
        assert code == "good"
        return user

    cfg = PortalConfig(
        gateway_type="agentgateway", github_client_id="cid", gateway_public_url="http://gw:4000"
    )
    app = create_app(pg_engine, cfg, backend, exchange=exchange, user_client=lambda tok: user)
    return TestClient(app), backend, user


def sign_in(c: TestClient) -> None:
    r = c.get("/auth/login", follow_redirects=False)
    assert r.status_code == 302
    state = re.search(r"state=([^&]+)", r.headers["location"]).group(1)  # type: ignore[union-attr]
    r = c.get(f"/auth/callback?code=good&state={state}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/me"
    assert COOKIE in r.cookies
    # The cookie is an opaque session id: it never carries the GitHub token.
    assert "tok-" not in r.headers["set-cookie"]


def test_health(client: Any) -> None:
    c, _, _ = client
    assert c.get("/healthz").json() == {"status": "ok"}
    assert c.get("/readyz").json() == {"status": "ready"}


def test_unauthenticated(client: Any) -> None:
    c, _, _ = client
    r = c.get("/api/me")
    assert r.status_code == 401 and r.json() == {"error": "unauthenticated", "message": "sign in first"}
    r = c.get("/me", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/auth/login"


def test_bad_state_rejected(client: Any) -> None:
    c, _, _ = client
    assert c.get("/auth/callback?code=good&state=forged", follow_redirects=False).status_code == 400


def test_repeated_callback_after_sign_in_goes_to_me(client: Any) -> None:
    c, _, _ = client
    sign_in(c)
    r = c.get("/auth/callback?code=good&state=already-used", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/me"


def test_sign_in_creates_developer(client: Any, pg_engine: Engine) -> None:
    c, _, user = client
    sign_in(c)
    with pg_engine.connect() as conn:
        login = conn.execute(
            text("SELECT github_login FROM developer WHERE github_id=:g"), {"g": user.gid}
        ).scalar()
    assert login == user.login
    assert c.get("/api/me").json()["credential"] is None


def test_issue_shows_key_once_and_stores_only_hash(client: Any, pg_engine: Engine) -> None:
    c, backend, user = client
    sign_in(c)
    r = c.post("/me/credential")
    key = re.search(r"sk-gca-[A-Za-z0-9_-]{43}", r.text).group(0)  # type: ignore[union-attr]
    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT key_hash, status::text, gateway_ref FROM gateway_credential c JOIN developer d "
                "ON d.id=c.developer_id WHERE d.github_id=:g"
            ),
            {"g": user.gid},
        ).fetchall()
    assert len(rows) == 1 and rows[0][0] == key_hash(key) and rows[0][1] == "active"
    assert rows[0][2].startswith("ref/")
    assert backend.synced and any(k.github_id == user.gid for k in backend.synced[-1])
    # Shown once: the next page view has no key.
    assert not re.search(r"sk-gca-[A-Za-z0-9_-]{43}", c.get("/me").text)


def test_reissue_revokes_previous(client: Any, pg_engine: Engine) -> None:
    c, backend, user = client
    sign_in(c)
    c.post("/me/credential")
    c.post("/me/credential")
    with pg_engine.connect() as conn:
        statuses = (
            conn.execute(
                text(
                    "SELECT status::text FROM gateway_credential c JOIN developer d ON d.id=c.developer_id "
                    "WHERE d.github_id=:g ORDER BY issued_at"
                ),
                {"g": user.gid},
            )
            .scalars()
            .all()
        )
    assert sorted(statuses) == ["active", "revoked"]
    assert len(backend.revoked) == 1
    mine = [k for k in backend.synced[-1] if k.github_id == user.gid]
    assert len(mine) == 1


def test_revoke(client: Any) -> None:
    c, backend, user = client
    sign_in(c)
    c.post("/me/credential")
    assert c.delete("/me/credential").json() == {"status": "revoked"}
    assert c.get("/api/me").json()["credential"] is None
    assert not [k for k in backend.synced[-1] if k.github_id == user.gid]


def test_setup_lists_tools(client: Any) -> None:
    c, _, _ = client
    sign_in(c)
    body = c.get("/me/setup").text
    for tool in ("Claude Code", "Codex CLI", "Gemini CLI", "OpenCode"):
        assert tool in body
    assert "http://gw:4000" in body


def _seed_change(engine: Engine, gid: int, full_name: str, pr: int) -> None:
    with engine.begin() as conn:
        dev = conn.execute(text("SELECT id FROM developer WHERE github_id=:g"), {"g": gid}).scalar()
        repo = conn.execute(
            text(
                "INSERT INTO repository (id, github_id, full_name, installation_id, active) "
                "VALUES (gen_random_uuid(), :rid, :fn, 1, true) RETURNING id"
            ),
            {"rid": uuid.uuid4().int % 10**9, "fn": full_name},
        ).scalar()
        change = conn.execute(
            text(
                "INSERT INTO change (id, repository_id, pr_number, state, opened_by_github_id) "
                "VALUES (gen_random_uuid(), :r, :pr, 'open', :g) RETURNING id"
            ),
            {"r": repo, "pr": pr, "g": gid},
        ).scalar()
        head = conn.execute(
            text(
                "INSERT INTO change_head (id, change_id, head_sha, event_received_at, status, "
                "coverage_status, coverage_reasons, key_gens, counts, excluded_paths, is_final, attempts, "
                "completed_at, alg) "
                "VALUES (gen_random_uuid(), :c, :sha, now(), 'complete', 'complete', '{}', '{1}', '{}', "
                '\'[{"path": "dist/app.min.js", "reason": "rule"}]\', false, 1, :t, 1) RETURNING id'
            ),
            {"c": change, "sha": "a" * 40, "t": datetime.now(UTC)},
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO line_result (change_head_id, file_path, line_no, outcome, tier, confidence, "
                "credited_developer_id, credited_github_id) VALUES "
                "(:h, 'src/app.py', 1, 'human', 'none', NULL, :d, :g), "
                "(:h, 'src/app.py', 2, 'not_observed', 'none', NULL, NULL, NULL)"
            ),
            {"h": head, "d": dev, "g": gid},
        )


def test_change_view(client: Any, pg_engine: Engine) -> None:
    c, _, user = client
    sign_in(c)
    pr = uuid.uuid4().int % 100_000
    _seed_change(pg_engine, user.gid, "acme/widgets", pr)
    r = c.get(f"/changes/acme/widgets/{pr}")
    assert r.status_code == 200
    assert "Human" in r.text and "Not observed" in r.text and "dist/app.min.js" in r.text
    assert f"/blob/{'a' * 40}/src/app.py#L1" in r.text
    r = c.get(f"/changes/acme/secret/{pr}")
    assert r.status_code == 403 and r.json()["error"] == "forbidden"
    assert c.get("/changes/acme/widgets/999999").status_code == 404


def test_render_agentgateway_config() -> None:
    out = yaml.safe_load(
        render_agentgateway_config(
            BASE, [ActiveKey("c2", 2, "sha256:" + "b" * 64), ActiveKey("c1", 1, "sha256:" + "a" * 64)]
        )
    )
    keys = out["llm"]["policies"]["apiKey"]["keys"]
    assert [k["metadata"]["credential_id"] for k in keys] == ["c1", "c2"]
    assert keys[0] == {"keyHash": "sha256:" + "a" * 64, "metadata": {"credential_id": "c1", "github_id": 1}}
    assert out["llm"]["models"][0]["name"] == "demo-openai"


def test_reissue_after_gateway_switch_skips_foreign_revoke(client: Any, pg_engine: Engine) -> None:
    c, backend, user = client
    sign_in(c)
    c.post("/me/credential")
    with pg_engine.begin() as conn:  # pretend the first key was issued while the install ran LiteLLM
        conn.execute(
            text(
                "UPDATE gateway_credential SET gateway_type = 'litellm' WHERE developer_id = "
                "(SELECT id FROM developer WHERE github_id = :g)"
            ),
            {"g": user.gid},
        )
    assert c.post("/me/credential").status_code == 200
    assert backend.revoked == []  # the agentgateway backend never saw that key
