"""T088: capture loss is recorded for sequence gaps, missed heartbeats, outages and self-reported failures, and
never double-counted (reordering, redelivery)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from gca_core import messages
from gca_ingest.loss import sweep
from gca_ingest.store import handle

GW = "litellm"  # the other ingest tests use agentgateway instances; keep the outage checks apart


class Capture:
    """One capture instance's messages, in the order ingest sees them."""

    def __init__(self, conn: Connection, gateway: str = GW) -> None:
        self.conn, self.gateway, self.iid = conn, gateway, str(uuid.uuid4())

    def _env(self, seq: int, sent: datetime | None) -> dict[str, Any]:
        return {
            "schema": messages.SCHEMA_ID,
            "instance_id": self.iid,
            "seq": seq,
            "gateway_type": self.gateway,
            "sent_at": (sent or datetime.now(UTC)).isoformat(),
        }

    def heartbeat(self, seq: int, sent: datetime | None = None, *, shutting_down: bool = False) -> None:
        body = messages.heartbeat_body(responses_seen=0, buffer_depth=0, shutting_down=shutting_down)
        handle(self.conn, messages.validate({**self._env(seq, sent), **body}))

    def failure(self, seq: int, cause: str, count: int = 1, **kw: Any) -> None:
        now = datetime.now(UTC).isoformat()
        body = messages.failure_body(cause=cause, count=count, period_start=now, period_end=now, **kw)
        handle(self.conn, messages.validate({**self._env(seq, None), **body}))

    def losses(self, cause: str | None = None) -> list[Any]:
        return list(
            self.conn.execute(
                text(
                    "SELECT cause::text AS cause, count, seq_first, seq_last, period_start, period_end, "
                    "developer_id, api_format::text AS api_format, tool_hint FROM capture_loss "
                    "WHERE instance_id = :i AND (CAST(:c AS text) IS NULL OR cause::text = :c) ORDER BY seq_first"
                ),
                {"i": uuid.UUID(self.iid), "c": cause},
            )
        )

    def status(self) -> str:
        return str(
            self.conn.execute(
                text("SELECT status::text FROM capture_instance WHERE instance_id = :i"),
                {"i": uuid.UUID(self.iid)},
            ).scalar()
        )


@pytest.fixture
def conn(pg_engine: Engine) -> Iterator[Connection]:
    """A transaction rolled back afterwards, so no loss leaks into other suites' coverage checks."""
    with pg_engine.connect() as c:
        tx = c.begin()
        c.execute(text("UPDATE capture_instance SET status = 'closed' WHERE gateway_type = 'litellm'"))
        try:
            yield c
        finally:
            tx.rollback()


def _outages(conn: Connection) -> list[Any]:
    return list(
        conn.execute(
            text(
                "SELECT period_start, period_end FROM capture_loss WHERE instance_id IS NULL "
                "AND cause = 'heartbeat_missed' AND gateway_type = 'litellm' ORDER BY period_start"
            )
        )
    )


def test_sequence_gap_is_recorded_with_its_span(conn: Connection) -> None:
    cap = Capture(conn)
    for seq in (0, 1, 2, 6):
        cap.heartbeat(seq)
    (gap,) = cap.losses("seq_gap")
    assert (gap.count, gap.seq_first, gap.seq_last) == (3, 3, 5)
    assert gap.developer_id is None


def test_first_messages_missing(conn: Connection) -> None:
    cap = Capture(conn)
    cap.heartbeat(4)
    (gap,) = cap.losses("seq_gap")
    assert (gap.count, gap.seq_first, gap.seq_last) == (4, 0, 3)


def test_late_messages_split_the_gap_and_duplicates_change_nothing(conn: Connection) -> None:
    cap = Capture(conn)
    for seq in (0, 1, 7):
        cap.heartbeat(seq)
    cap.heartbeat(4)  # a redelivery that arrived out of order
    assert [(g.seq_first, g.seq_last, g.count) for g in cap.losses("seq_gap")] == [(2, 3, 2), (5, 6, 2)]
    cap.heartbeat(4)  # delivered again
    cap.heartbeat(1)
    for seq in (2, 3, 5, 6):
        cap.heartbeat(seq)
    assert cap.losses("seq_gap") == []  # it was only reordering: no loss


def test_failures_are_recorded_once_with_their_details(conn: Connection) -> None:
    dev = conn.execute(
        text(
            "INSERT INTO developer (id, github_id, github_login) VALUES (gen_random_uuid(), "
            "(random()*1e9)::bigint, 'loss-dev') RETURNING id"
        )
    ).scalar()
    cred = conn.execute(
        text(
            "INSERT INTO gateway_credential (id, developer_id, gateway_type, key_hash, status) "
            "VALUES (gen_random_uuid(), :d, 'litellm', :h, 'active') RETURNING id"
        ),
        {"d": dev, "h": "sha256:" + uuid.uuid4().hex * 2},
    ).scalar()
    cap = Capture(conn)
    cap.heartbeat(0)
    kw = {"credential_id": str(cred), "api_format": "openai_responses", "tool_hint": "codex-cli"}
    cap.failure(1, "truncated", 2, **kw)
    cap.failure(1, "truncated", 2, **kw)  # JetStream redelivered it
    cap.failure(2, "unsupported_combination", credential_id=str(cred), tool_hint="opencode")
    rows = cap.losses()
    assert [(r.cause, r.count) for r in rows] == [("truncated", 2), ("unsupported_combination", 1)]
    assert rows[0].developer_id == dev and rows[0].api_format == "openai_responses"
    assert rows[0].tool_hint == "codex-cli" and rows[1].tool_hint == "opencode"


def test_missed_heartbeats_open_a_loss_that_closes_when_they_resume(conn: Connection) -> None:
    cap = Capture(conn)
    last = datetime.now(UTC) - timedelta(minutes=2)
    cap.heartbeat(0, last)
    assert sweep(conn, GW)["stale"] >= 1
    (loss,) = cap.losses("heartbeat_missed")
    assert loss.period_start == last and loss.period_end is None and cap.status() == "stale"
    sweep(conn, GW)  # sweeping again doesn't open a second one
    assert len(cap.losses("heartbeat_missed")) == 1
    back = datetime.now(UTC)
    cap.heartbeat(1, back)
    (loss,) = cap.losses("heartbeat_missed")
    assert loss.period_end == back and cap.status() == "active"


def test_shutdown_heartbeat_closes_the_loss(conn: Connection) -> None:
    cap = Capture(conn)
    cap.heartbeat(0, datetime.now(UTC) - timedelta(minutes=1))
    sweep(conn, GW)
    cap.heartbeat(1, shutting_down=True)
    (loss,) = cap.losses("heartbeat_missed")
    assert loss.period_end is not None and cap.status() == "closed"


def test_a_replacement_instance_ends_a_dead_instances_loss(conn: Connection) -> None:
    dead = Capture(conn)
    dead.heartbeat(0, datetime.now(UTC) - timedelta(minutes=3))
    sweep(conn, GW)
    assert dead.losses("heartbeat_missed")[0].period_end is None
    new = Capture(conn)
    new.heartbeat(0)  # its pod was restarted under a new instance ID
    sweep(conn, GW)
    (loss,) = dead.losses("heartbeat_missed")
    assert loss.period_end is not None and dead.status() == "closed"


def test_no_capture_running_is_an_outage(conn: Connection) -> None:
    cap = Capture(conn)
    last = datetime.now(UTC) - timedelta(minutes=5)
    cap.heartbeat(0, last)
    cap.heartbeat(1, last, shutting_down=True)  # scaled to zero: a clean shutdown, no instance loss
    assert cap.losses() == []
    assert sweep(conn, GW)["outages"] == 1
    assert sweep(conn, GW)["outages"] == 0  # one outage, not one per sweep
    (outage,) = _outages(conn)
    assert outage.period_start == last and outage.period_end is None
    Capture(conn).heartbeat(0)  # capture is back
    (outage,) = _outages(conn)
    assert outage.period_end is not None


def test_a_short_gap_between_instances_is_not_an_outage(conn: Connection) -> None:
    cap = Capture(conn)
    cap.heartbeat(0)
    cap.heartbeat(1, shutting_down=True)  # a rolling update: the old pod stops, the new one is starting
    assert sweep(conn, GW)["outages"] == 0
    assert _outages(conn) == []
