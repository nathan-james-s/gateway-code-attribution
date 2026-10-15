"""T091: /coverage shows capture loss and unmapped PR authors; only admins see who they are."""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_portal.app import create_app
from gca_portal.config import PortalConfig

from .test_admin import FakeBackend, FakeUser


def _client(engine: Engine, *, admin: bool) -> TestClient:
    login = f"cov-{uuid.uuid4().hex[:6]}"
    user = FakeUser(9_600_000 + uuid.uuid4().int % 100_000, login)

    async def exchange(*args: Any) -> FakeUser:
        return user

    cfg = PortalConfig(
        github_client_id="cid", admin_logins=[login] if admin else [], grafana_url="http://g:3000"
    )
    c = TestClient(create_app(engine, cfg, FakeBackend(), exchange=exchange, user_client=lambda tok: user))
    r = c.get("/auth/login", follow_redirects=False)
    state = re.search(r"state=([^&]+)", r.headers["location"]).group(1)  # type: ignore[union-attr]
    c.get(f"/auth/callback?code=x&state={state}", follow_redirects=False)
    return c


def test_coverage_lists_unmapped_authors_for_admins_only(pg_engine: Engine) -> None:
    bot, bot_id = f"ci-bot-{uuid.uuid4().hex[:6]}", 9_700_000 + uuid.uuid4().int % 100_000
    FakeUser.accounts[bot] = bot_id
    repo = f"acme/cov-{uuid.uuid4().hex[:6]}"
    with pg_engine.begin() as conn:
        r = conn.execute(
            text(
                "INSERT INTO repository (id, github_id, full_name, installation_id, active) "
                "VALUES (gen_random_uuid(), :g, :fn, 1, true) RETURNING id"
            ),
            {"g": bot_id, "fn": repo},
        ).scalar()
        c = conn.execute(
            text(
                "INSERT INTO change (id, repository_id, pr_number, opened_by_github_id, state) "
                "VALUES (gen_random_uuid(), :r, 1, 1, 'open') RETURNING id"
            ),
            {"r": r},
        ).scalar()
        heads = []
        for sha in ("a1", "b2"):  # two heads of one PR: only the latest counts
            heads.append(
                conn.execute(
                    text(
                        "INSERT INTO change_head (id, change_id, head_sha, event_received_at, status, coverage_status, "
                        "coverage_reasons, key_gens, counts, excluded_paths, is_final, attempts, completed_at) VALUES "
                        "(gen_random_uuid(), :c, :s, now(), 'complete', 'complete', '{}', '{}', '{}', '[]', false, 1, "
                        "now() - make_interval(secs => :age)) RETURNING id"
                    ),
                    {"c": c, "s": sha, "age": 60 if sha == "a1" else 0},
                ).scalar()
            )
        for h in heads:
            for n in (1, 2, 3):
                conn.execute(
                    text(
                        "INSERT INTO line_result (change_head_id, file_path, line_no, outcome, tier, credited_github_id) "
                        "VALUES (:h, 'x.py', :n, 'not_observed', 'none', :g)"
                    ),
                    {"h": h, "n": n, "g": bot_id},
                )
    admin = _client(pg_engine, admin=True).get("/api/coverage").json()
    assert admin["dashboard_url"] == "http://g:3000/d/gca-coverage"
    mine = next(u for u in admin["unmapped"] if u["github_id"] == bot_id)
    assert mine == {
        "github_id": bot_id,
        "github_login": bot,
        "lines": 3,
        "changes": 1,
        "repositories": [repo],
    }
    viewer = _client(pg_engine, admin=False)
    data = viewer.get("/api/coverage").json()
    assert "unmapped" not in data and data["unmapped_accounts"] >= 1
    page = viewer.get("/coverage")
    assert page.status_code == 200 and bot not in page.text and "Admins see which accounts" in page.text
    assert bot in _client(pg_engine, admin=True).get("/coverage").text
