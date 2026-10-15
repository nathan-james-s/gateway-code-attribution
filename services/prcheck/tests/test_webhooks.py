"""T069/T071: signed, deduplicated webhook delivery drives the same per-head and merge results as polling."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_prcheck.webhooks import create_router, signature_ok

SECRET = "whsec-test"


def _client(engine: Engine, gh: object) -> TestClient:
    app = FastAPI()
    app.include_router(create_router(engine, gh, SECRET))  # type: ignore[arg-type]
    return TestClient(app)


def _post(
    c: TestClient, event: str, payload: dict[str, Any], delivery: str | None = None, sign: bool = True
) -> Any:
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest() if sign else "sha256=bad"
    return c.post(
        "/webhooks/github",
        content=body,
        headers={
            "x-github-event": event,
            "x-github-delivery": delivery or str(uuid.uuid4()),
            "x-hub-signature-256": sig,
            "content-type": "application/json",
        },
    )


def _pr_payload(gh: Any, action: str, *, sha: str, merged: bool = False) -> dict[str, Any]:
    pr = {
        **gh.pr,
        "head": {"sha": sha},
        "merged": merged,
        "merged_at": "2026-10-15T12:00:00Z" if merged else None,
    }
    return {"action": action, "pull_request": pr, "repository": gh.repo, "installation": {"id": 11}}


def _change(engine: Engine, full_name: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT c.id, c.state::text AS state, c.final_head_id FROM change c "
                "JOIN repository r ON r.id = c.repository_id WHERE r.full_name = :fn"
            ),
            {"fn": full_name},
        ).one()


def _heads(engine: Engine, change_id: Any) -> list[Any]:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT head_sha, status::text AS status, is_final FROM change_head WHERE change_id = :c "
                "ORDER BY head_sha"
            ),
            {"c": change_id},
        ).fetchall()


def test_signature() -> None:
    body = b'{"a":1}'
    good = "sha256=" + hmac.new(b"s", body, hashlib.sha256).hexdigest()
    assert signature_ok("s", body, good)
    assert not signature_ok("s", body, "sha256=00") and not signature_ok("", body, good)


def test_rejects_unsigned(pg_engine: Engine, world: SimpleNamespace) -> None:
    gh = world.FakeGitHub(1, "acme/x", 1, 2)
    r = _post(_client(pg_engine, gh), "pull_request", _pr_payload(gh, "opened", sha="a" * 40), sign=False)
    assert r.status_code == 401 and r.json()["detail"]["error"] == "unauthenticated"


def test_pull_request_lifecycle(pg_engine: Engine, world: SimpleNamespace) -> None:
    gid = 7_500_000 + uuid.uuid4().int % 1_000_000
    gh = world.FakeGitHub(gid, f"acme/hooks-{gid}", gid, gid + 1)
    c = _client(pg_engine, gh)
    full = gh.repo["full_name"]

    assert (
        _post(c, "pull_request", _pr_payload(gh, "opened", sha="a" * 40), delivery="d-1").status_code == 202
    )
    assert gh.created and gh.created[0]["status"] == "in_progress"  # announced in the background
    # The same delivery again is a no-op (FR-020).
    assert _post(c, "pull_request", _pr_payload(gh, "opened", sha="a" * 40), delivery="d-1").json() == {
        "status": "duplicate"
    }
    assert len(gh.created) == 1

    _post(c, "pull_request", _pr_payload(gh, "synchronize", sha="b" * 40))
    _post(c, "pull_request", _pr_payload(gh, "closed", sha="b" * 40, merged=True))
    ch = _change(pg_engine, full)
    heads = _heads(pg_engine, ch.id)
    assert ch.state == "merged" and [(h.head_sha[0], h.is_final) for h in heads] == [
        ("a", False),
        ("b", True),
    ]

    # Re-run from GitHub's "Re-run" button: the same head goes back to pending.
    _post(
        c,
        "check_run",
        {
            "action": "rerequested",
            "check_run": {"name": "AI code attribution", "head_sha": "a" * 40},
            "repository": gh.repo,
            "installation": {"id": 11},
        },
    )
    assert {h.head_sha[0]: h.status for h in _heads(pg_engine, ch.id)}["a"] == "pending"


def test_closed_then_reopened(pg_engine: Engine, world: SimpleNamespace) -> None:
    gid = 7_600_000 + uuid.uuid4().int % 1_000_000
    gh = world.FakeGitHub(gid, f"acme/reopen-{gid}", gid, gid + 1)
    c = _client(pg_engine, gh)
    _post(c, "pull_request", _pr_payload(gh, "opened", sha="a" * 40))
    _post(c, "pull_request", _pr_payload(gh, "closed", sha="a" * 40))
    assert _change(pg_engine, gh.repo["full_name"]).state == "closed"
    _post(c, "pull_request", _pr_payload(gh, "reopened", sha="a" * 40))
    assert _change(pg_engine, gh.repo["full_name"]).state == "open"


def test_repositories_removed_are_deactivated(pg_engine: Engine, world: SimpleNamespace) -> None:
    gid = 7_700_000 + uuid.uuid4().int % 1_000_000
    gh = world.FakeGitHub(gid, f"acme/removed-{gid}", gid, gid + 1)
    c = _client(pg_engine, gh)
    _post(c, "installation_repositories", {"installation": {"id": 11}, "repositories_added": [gh.repo]})
    _post(c, "installation_repositories", {"installation": {"id": 11}, "repositories_removed": [gh.repo]})
    with pg_engine.connect() as conn:
        assert (
            conn.execute(text("SELECT active FROM repository WHERE github_id = :g"), {"g": gid}).scalar()
            is False
        )
