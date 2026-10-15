"""Admin surface (T074-T076): identity overrides, revoking any credential, fingerprint key rotation."""

from __future__ import annotations

import base64
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_core.identity import resolve_developer
from gca_core.keys import load_keys
from gca_ingest.maintenance import daily
from gca_portal import admin_keys
from gca_portal.app import create_app
from gca_portal.backends import ActiveKey
from gca_portal.config import PortalConfig
from gca_portal.keysecret import KeySecret


class FakeBackend:
    def __init__(self) -> None:
        self.revoked: list[str] = []

    def issue(self, credential_id: str, github_id: int, key: str, key_hash: str) -> str | None:
        return f"ref/{credential_id}"

    def revoke(self, credential_id: str, gateway_ref: str | None) -> None:
        self.revoked.append(credential_id)

    def sync(self, active: list[ActiveKey]) -> None:
        return None

    def ensure(self) -> None:
        return None


class FakeCoreApi:
    """Just enough of kubernetes' CoreV1Api for the fingerprint Secret (merge-patch semantics)."""

    def __init__(self) -> None:
        self.data = {
            "1": base64.b64encode(base64.b64encode(b"\x01" * 32)).decode(),
            "active": base64.b64encode(b"1").decode(),
        }

    def read_namespaced_secret(self, name: str, namespace: str) -> Any:
        return SimpleNamespace(data=dict(self.data))

    def patch_namespaced_secret(self, name: str, namespace: str, body: dict[str, Any]) -> None:
        for k, v in body["data"].items():
            if v is None:
                self.data.pop(k, None)
            else:
                self.data[k] = v

    def mount(self, directory: Path) -> Path:
        """What the kubelet would project into the pod."""
        for k, v in self.data.items():
            (directory / k).write_bytes(base64.b64decode(v))
        return directory


class FakeUser:
    accounts: ClassVar[dict[str, int]] = {}

    def __init__(self, gid: int, login: str) -> None:
        self.gid, self.login, self.token = gid, login, f"tok-{login}"

    async def me(self) -> dict[str, Any]:
        return {"id": self.gid, "login": self.login}

    async def org_role(self, org: str) -> str | None:
        return None

    async def maintained_teams(self, org: str, login: str) -> list[str]:
        return []

    async def login_for_id(self, account_id: int) -> str | None:
        return next((login for login, gid in FakeUser.accounts.items() if gid == account_id), None)

    async def user_by_login(self, login: str) -> dict[str, Any] | None:
        gid = FakeUser.accounts.get(login)
        return {"id": gid, "login": login} if gid else None

    async def can_view_repo(self, owner: str, repo: str) -> bool:
        return True


def _gid() -> int:
    return 5_000_000 + uuid.uuid4().int % 1_000_000


def _client(
    engine: Engine, login: str, *, admins: list[str], secret: KeySecret | None = None
) -> tuple[TestClient, Any]:
    user = FakeUser(_gid(), login)
    backend = FakeBackend()

    async def exchange(*args: Any) -> FakeUser:
        return user

    cfg = PortalConfig(github_client_id="cid", admin_logins=admins, retention_days=90)
    c = TestClient(
        create_app(engine, cfg, backend, exchange=exchange, user_client=lambda tok: user, key_secret=secret)
    )
    r = c.get("/auth/login", follow_redirects=False)
    state = re.search(r"state=([^&]+)", r.headers["location"]).group(1)  # type: ignore[union-attr]
    c.get(f"/auth/callback?code=x&state={state}", follow_redirects=False)
    return c, SimpleNamespace(user=user, backend=backend)


def test_non_admin_is_forbidden(pg_engine: Engine) -> None:
    c, _ = _client(pg_engine, f"dev{_gid()}", admins=[])
    for r in (c.get("/admin"), c.get("/api/admin/overrides"), c.post("/admin/keys/rotate")):
        assert r.status_code == 403 and r.json()["error"] == "forbidden"


def test_override_lifecycle(pg_engine: Engine) -> None:
    admin_login = f"admin{_gid()}"
    c, _ = _client(pg_engine, admin_login, admins=[admin_login])
    bot, bot_id = f"svc-bot-{_gid()}", _gid()
    FakeUser.accounts[bot] = bot_id
    body = {
        "github_login": bot,
        "developer_login": admin_login,
        "reason": "release bot commits for the admin",
    }
    r = c.post("/api/admin/overrides", json=body)
    assert r.status_code == 201
    from sqlalchemy.orm import Session

    with Session(pg_engine) as s:
        dev = resolve_developer(s, bot_id)
        assert (
            dev is not None and dev.github_login == admin_login
        )  # lines by the bot now match the admin's captures
    assert c.post("/api/admin/overrides", json=body).json()["error"] == "conflict"
    assert c.post("/api/admin/overrides", json={**body, "reason": " "}).status_code == 422
    assert any(o["github_id"] == bot_id for o in c.get("/api/admin/overrides").json())
    assert c.delete(f"/admin/overrides/{r.json()['id']}").json() == {"status": "deleted"}
    assert c.delete(f"/admin/overrides/{r.json()['id']}").status_code == 404


def test_admin_revokes_any_credential(pg_engine: Engine) -> None:
    dev_c, dev = _client(pg_engine, f"dev{_gid()}", admins=[])
    dev_c.post("/me/credential")
    with pg_engine.connect() as conn:
        cred_id = conn.execute(
            text(
                "SELECT c.id FROM gateway_credential c JOIN developer d ON d.id = c.developer_id "
                "WHERE d.github_id = :g AND c.status = 'active'"
            ),
            {"g": dev.user.gid},
        ).scalar()
    admin_login = f"admin{_gid()}"
    admin_c, admin = _client(pg_engine, admin_login, admins=[admin_login])
    assert admin_c.post(f"/admin/credentials/{cred_id}/revoke").json() == {"status": "revoked"}
    assert admin.backend.revoked == [str(cred_id)]
    assert admin_c.post(f"/admin/credentials/{cred_id}/revoke").status_code == 404
    assert dev_c.get("/api/me").json()["credential"] is None


def test_rotation_keeps_old_generation_until_expiry(pg_engine: Engine, tmp_path: Path) -> None:
    api = FakeCoreApi()
    secret = KeySecret("gca", "fp", core_api=api)
    with pg_engine.begin() as conn:  # a known starting point: generation 1 active
        conn.execute(text("DELETE FROM key_generation"))
        conn.execute(text("INSERT INTO key_generation (id, status) VALUES (1, 'active')"))
    admin_login = f"admin{_gid()}"
    c, _ = _client(pg_engine, admin_login, admins=[admin_login], secret=secret)
    assert c.post("/admin/keys/rotate").json() == {"active_generation": 2}
    keys, active = load_keys(api.mount(tmp_path))  # the services' own loader reads the rotated Secret
    assert active == 2 and sorted(keys) == [1, 2] and len(keys[2].secret) == 32
    with pg_engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT id, status::text FROM key_generation")).fetchall())
    assert rows == {1: "retired", 2: "active"}

    # Past retention: ingest's daily job expires generation 1, then the portal removes it from the Secret.
    with pg_engine.begin() as conn:
        conn.execute(
            text("UPDATE key_generation SET expires_at = :t WHERE id = 1"),
            {"t": datetime.now(UTC) - timedelta(minutes=1)},
        )
        assert daily(conn)["expired_generations"] == 1
    assert admin_keys.sync_secret(pg_engine, secret) == {1}
    assert secret.generations() == {2}


def test_daily_maintenance_is_safe_to_repeat(pg_engine: Engine) -> None:
    with pg_engine.begin() as conn:
        first = daily(conn)
        second = daily(conn)
    assert second == {"expired_generations": 0, "dropped_partitions": 0}
    assert first["dropped_partitions"] >= 0


@pytest.fixture(autouse=True)
def _restore_key_generation(pg_engine: Engine) -> Any:
    yield
    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM key_generation"))
        conn.execute(text("INSERT INTO key_generation (id, status) VALUES (1, 'active')"))
