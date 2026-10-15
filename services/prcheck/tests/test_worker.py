"""T052-T054 end to end against PostgreSQL with a fake GitHub: poll, gate on the watermark, attribute, report."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_core.keys import KeyRing
from gca_prcheck import polling, worker
from gca_prcheck.config import PrcheckConfig


async def test_poll_gate_attribute_report(
    pg_engine: Engine, keyring: KeyRing, world: SimpleNamespace
) -> None:
    gid, other = 8_000_000 + uuid.uuid4().int % 1_000_000, 9_100_000 + uuid.uuid4().int % 1_000_000
    full_name = f"acme/repo{gid}"
    gh = world.FakeGitHub(gid, full_name, gid, other)
    with pg_engine.begin() as conn:
        world.capture(conn, gid)
        conn.execute(text("UPDATE capture_instance SET status = 'stale' WHERE status = 'active'"))

    assert await polling.poll_once(pg_engine, gh) == 1  # type: ignore[arg-type]
    assert await polling.poll_once(pg_engine, gh) == 0  # idempotent on (change, head_sha)
    assert gh.created[0]["status"] == "in_progress" and gh.created[0]["output"]["title"].startswith("Waiting")

    # No active capture instance yet: the head waits (FR-017).
    assert worker.claim_ready(pg_engine) is None
    with pg_engine.begin() as conn:
        world.heartbeat(conn)
    head_id = worker.claim_ready(pg_engine)
    assert head_id is not None

    cfg = PrcheckConfig(portal_url="http://portal")
    await worker.process_head(pg_engine, gh, keyring, cfg, head_id)  # type: ignore[arg-type]

    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT line_no, outcome::text, tier::text, credited_github_id FROM line_result "
                "WHERE change_head_id = :h ORDER BY line_no"
            ),
            {"h": head_id},
        ).fetchall()
        head = conn.execute(
            text(
                "SELECT status::text, coverage_status::text, counts, excluded_paths, check_run_id "
                "FROM change_head WHERE id = :h"
            ),
            {"h": head_id},
        ).one()
    assert [(r[0], r[1], r[2]) for r in rows] == [
        (1, "ai_unmodified", "exact"),
        (2, "ai_modified", "anchored"),
        (3, "human", "none"),
        (4, "indeterminate", "none"),
        (5, "not_observed", "none"),
    ]
    assert rows[4][3] == other  # unmapped account recorded, developer left empty
    assert head[0] == "complete" and head[1] == "complete" and head[4] == 555
    assert head[2]["excluded"] == 1 and head[3] == [{"path": "assets/logo.png", "reason": "binary"}]

    final = gh.updates[0]
    assert final["conclusion"] == "neutral" and final["status"] == "completed"
    assert final["output"]["title"] == "AI 67% · human 33% · indeterminate 1 lines · coverage: complete"
    assert f"http://portal/changes/{full_name}/7" in final["output"]["summary"]
    # No code anywhere in what goes to GitHub.
    sent = repr(gh.updates) + repr(gh.created)
    assert "item.price" not in sent and "print(" not in sent
