"""T089: a capture loss that overlaps a head's matching window makes its coverage incomplete, with reasons."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from gca_core.keys import KeyRing
from gca_prcheck import polling, worker
from gca_prcheck.config import PrcheckConfig
from gca_prcheck.coverage import loss_reasons

NOW = datetime.now(UTC)


def _dev(conn: Connection) -> uuid.UUID:
    return uuid.UUID(
        str(
            conn.execute(
                text(
                    "INSERT INTO developer (id, github_id, github_login) VALUES (gen_random_uuid(), "
                    "(random()*1e9)::bigint, 'cov') RETURNING id"
                )
            ).scalar()
        )
    )


def _loss(
    conn: Connection,
    cause: str,
    *,
    dev: uuid.UUID | None = None,
    start: datetime,
    end: datetime | None,
    count: int = 1,
) -> None:
    conn.execute(
        text(
            "INSERT INTO capture_loss (id, cause, period_start, period_end, count, developer_id, gateway_type) "
            "VALUES (gen_random_uuid(), CAST(:c AS loss_cause), :s, :e, :n, :d, 'agentgateway')"
        ),
        {"c": cause, "s": start, "e": end, "n": count, "d": dev},
    )


@pytest.fixture
def conn(pg_engine: Engine) -> Iterator[Connection]:
    with pg_engine.connect() as c:
        tx = c.begin()
        c.execute(text("DELETE FROM capture_loss"))  # only this transaction's rows count
        try:
            yield c
        finally:
            tx.rollback()


def test_only_losses_that_could_hide_a_credited_authors_output_count(conn: Connection) -> None:
    ada, bob = _dev(conn), _dev(conn)
    hour = timedelta(hours=1)
    _loss(conn, "truncated", dev=ada, start=NOW - hour, end=NOW - hour, count=2)  # ada's: counts
    _loss(conn, "unparsable", dev=bob, start=NOW - hour, end=NOW - hour)  # bob isn't credited
    _loss(conn, "unknown_credential", start=NOW - hour, end=NOW - hour)  # nobody in the stack
    _loss(conn, "seq_gap", start=NOW - hour, end=NOW - hour, count=3)  # could be anyone's
    _loss(conn, "truncated", dev=ada, start=NOW - timedelta(days=20), end=NOW - timedelta(days=20))  # too old
    _loss(conn, "truncated", dev=ada, start=NOW + hour, end=NOW + hour)  # after the push
    reasons = loss_reasons(conn, {ada}, NOW, 14)
    assert reasons == [
        "3 capture messages never reached ingest (sequence gap)",
        "2 AI responses cut off mid-response weren't captured (truncated)",
    ]


def test_an_ongoing_outage_spanning_the_window_counts(conn: Connection) -> None:
    _loss(conn, "heartbeat_missed", start=NOW - timedelta(days=30), end=None)
    (reason,) = loss_reasons(conn, set(), NOW, 14)
    assert reason == "capture wasn't reporting for 336 hours in the matching window, and it still isn't"
    assert loss_reasons(conn, set(), NOW - timedelta(days=31), 14) == []


def test_coverage_rules_with_losses() -> None:
    from gcattr import AddedLine, LineOutcome

    human = LineOutcome("human", "none", None, None, None)
    lines = [AddedLine("a.py", 1, "x = compute(a, b)", 5)]
    status, reasons = worker.coverage_for(lines, [human], losses=["2 AI responses lost"])
    assert status == "incomplete" and reasons == ["2 AI responses lost"]
    no = LineOutcome("not_observed", "none", None, None, None)
    assert worker.coverage_for(lines, [no], losses=["x"])[0] == "not_observed"  # nobody's capture to lose


async def test_a_head_overlapping_a_loss_is_incomplete(
    pg_engine: Engine, keyring: KeyRing, world: SimpleNamespace
) -> None:
    gid, other = 8_200_000 + uuid.uuid4().int % 100_000, 9_200_000 + uuid.uuid4().int % 100_000
    gh: Any = world.FakeGitHub(gid, f"acme/cov-{gid}", gid, other)
    with pg_engine.begin() as conn:
        world.capture(conn, gid)
        dev = conn.execute(text("SELECT id FROM developer WHERE github_id = :g"), {"g": gid}).scalar()
        _loss(
            conn,
            "unexpected_format",
            dev=dev,
            start=NOW - timedelta(minutes=5),
            end=NOW - timedelta(minutes=5),
        )
    try:
        await polling.poll_once(pg_engine, gh)
        with pg_engine.begin() as conn:
            world.heartbeat(conn)
        head_id = worker.claim_ready(pg_engine)
        assert head_id is not None
        await worker.process_head(pg_engine, gh, keyring, PrcheckConfig(), head_id)
        with pg_engine.connect() as conn:
            h = conn.execute(
                text(
                    "SELECT coverage_status::text AS s, coverage_reasons AS r FROM change_head WHERE id = :h"
                ),
                {"h": head_id},
            ).one()
        assert h.s == "incomplete"
        assert "1 AI responses in an unexpected format weren't captured (unexpected_format)" in h.r
        assert "coverage: incomplete" in gh.updates[0]["output"]["title"]
        assert "unexpected_format" in gh.updates[0]["output"]["summary"]
    finally:
        with pg_engine.begin() as conn:
            conn.execute(text("DELETE FROM capture_loss WHERE developer_id = :d"), {"d": dev})
