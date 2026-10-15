"""Operator command: issue a credential without a browser sign-in (T065)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_portal import admin_cli
from gca_portal.backends import ActiveKey
from gca_portal.credentials import key_hash


class FakeBackend:
    def __init__(self) -> None:
        self.synced: list[list[ActiveKey]] = []

    def issue(self, credential_id: str, github_id: int, key: str, key_hash: str) -> str | None:
        return f"ref/{credential_id}"

    def revoke(self, credential_id: str, gateway_ref: str | None) -> None:
        return None

    def sync(self, active: list[ActiveKey]) -> None:
        self.synced.append(list(active))

    def ensure(self) -> None:
        return None


def test_issue_credential_creates_developer_and_prints_key_once(
    pg_engine: Engine, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    backend = FakeBackend()
    monkeypatch.setattr(admin_cli, "make_engine", lambda: pg_engine)
    monkeypatch.setattr(admin_cli, "make_backend", lambda cfg: backend)
    gid = 6_000_000 + uuid.uuid4().int % 1_000_000
    assert admin_cli.main(["issue-credential", "--github-id", str(gid), "--github-login", "ci-bot"]) == 0
    key = capsys.readouterr().out.strip()
    assert key.startswith("sk-gca-")
    with pg_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT d.github_login, c.key_hash, c.status::text FROM gateway_credential c "
                "JOIN developer d ON d.id = c.developer_id WHERE d.github_id = :g"
            ),
            {"g": gid},
        ).one()
    assert row == ("ci-bot", key_hash(key), "active")
    assert any(k.github_id == gid for k in backend.synced[-1])
    # A second issue revokes the first.
    admin_cli.main(["issue-credential", "--github-id", str(gid), "--github-login", "ci-bot"])
    with pg_engine.connect() as conn:
        statuses = (
            conn.execute(
                text(
                    "SELECT status::text FROM gateway_credential c JOIN developer d ON d.id = c.developer_id "
                    "WHERE d.github_id = :g ORDER BY issued_at"
                ),
                {"g": gid},
            )
            .scalars()
            .all()
        )
    assert sorted(statuses) == ["active", "revoked"]
