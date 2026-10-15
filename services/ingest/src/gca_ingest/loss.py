"""Capture loss detection (T088; research R12; FR-005, SC-005). Ingest never drops a failure without recording it.

- **Sequence gaps.** An instance numbers each message it manages to publish, from 0. A message whose `seq` is past
  `last_seq + 1` opens a `seq_gap` loss for the missing span. A late message inside a span (a redelivery that
  arrived out of order) splits the span, so reordering is never counted as loss.
- **Missed heartbeats.** When the sweeper marks an instance `stale`, a `heartbeat_missed` loss opens from its last
  heartbeat. It closes when heartbeats resume, on a `shutting_down` heartbeat, or when a replacement instance of
  the same gateway starts (a crashed or wedged process never comes back; its pod is restarted under a new ID).
- **No capture running.** Instances that shut down cleanly report no loss, but if no instance of the configured
  gateway is active for longer than the stale threshold, nothing is capturing and the gateway fails open. That
  opens a `heartbeat_missed` loss with no instance, from the last heartbeat, until an instance is active again.
- **Self-reported failures** become rows with their cause, count, developer, API format and tool. Each failure
  message is stored once (`source_seq`), however often it's delivered.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

__all__ = [
    "STALE_AFTER_SECONDS",
    "close_heartbeat_loss",
    "mark_stale_instances",
    "record_failure",
    "sweep",
    "track_seq",
]

STALE_AFTER_SECONDS = 15


def _gap(
    conn: Connection, iid: uuid.UUID, gateway: str, first: int, last: int, start: datetime, end: datetime
) -> None:
    conn.execute(
        text(
            "INSERT INTO capture_loss (id, instance_id, cause, period_start, period_end, count, gateway_type, "
            "seq_first, seq_last) VALUES (gen_random_uuid(), :iid, 'seq_gap', :ps, :pe, :n, "
            "CAST(:gw AS gateway_type), :a, :b)"
        ),
        {
            "iid": iid,
            "ps": min(start, end),
            "pe": end,
            "n": last - first + 1,
            "gw": gateway,
            "a": first,
            "b": last,
        },
    )


def track_seq(conn: Connection, msg: dict[str, Any], sent: datetime) -> None:
    """Record or shrink sequence gaps for one message. Call before the instance's `last_seq` is updated."""
    iid, seq = uuid.UUID(msg["instance_id"]), int(msg["seq"])
    inst = conn.execute(
        text("SELECT last_seq, last_heartbeat_at FROM capture_instance WHERE instance_id = :i FOR UPDATE"),
        {"i": iid},
    ).first()
    if inst is None:
        if seq > 0:  # the instance's first messages never arrived
            _gap(conn, iid, msg["gateway_type"], 0, seq - 1, sent, sent)
        return
    if seq > inst.last_seq + 1:
        _gap(conn, iid, msg["gateway_type"], inst.last_seq + 1, seq - 1, inst.last_heartbeat_at, sent)
        return
    if seq <= inst.last_seq:
        _fill(conn, iid, seq)


def _fill(conn: Connection, iid: uuid.UUID, seq: int) -> None:
    span = conn.execute(
        text(
            "DELETE FROM capture_loss WHERE id = (SELECT id FROM capture_loss WHERE instance_id = :i "
            "AND cause = 'seq_gap' AND seq_first <= :s AND seq_last >= :s LIMIT 1) "
            "RETURNING period_start, period_end, gateway_type::text AS gw, seq_first, seq_last"
        ),
        {"i": iid, "s": seq},
    ).first()
    if span is None:
        return  # a duplicate of a message already stored: nothing was missing
    for first, last in ((span.seq_first, seq - 1), (seq + 1, span.seq_last)):
        if first <= last:
            _gap(conn, iid, span.gw, first, last, span.period_start, span.period_end)


def close_heartbeat_loss(conn: Connection, iid: uuid.UUID, gateway: str, at: datetime) -> None:
    """Heartbeats resumed (or the instance shut down): end its open loss, and any capture outage."""
    conn.execute(
        text(
            "UPDATE capture_loss SET period_end = greatest(:at, period_start) WHERE cause = 'heartbeat_missed' "
            "AND period_end IS NULL AND (instance_id = :i OR (instance_id IS NULL AND gateway_type = CAST(:gw AS "
            "gateway_type)))"
        ),
        {"at": at, "i": iid, "gw": gateway},
    )


def record_failure(conn: Connection, msg: dict[str, Any], developer_id: uuid.UUID | None, ts: Any) -> None:
    conn.execute(
        text(
            "INSERT INTO capture_loss (id, instance_id, cause, period_start, period_end, count, developer_id,"
            " gateway_type, api_format, tool_hint, source_seq) VALUES (gen_random_uuid(), :iid,"
            " CAST(:cause AS loss_cause), :ps, :pe, :count, :dev, CAST(:gw AS gateway_type),"
            " CAST(:fmt AS api_format), :hint, :seq)"
            " ON CONFLICT (instance_id, source_seq) WHERE source_seq IS NOT NULL DO NOTHING"
        ),
        {
            "iid": uuid.UUID(msg["instance_id"]),
            "cause": msg["cause"],
            "ps": ts(msg["period_start"]),
            "pe": ts(msg["period_end"]),
            "count": msg["count"],
            "dev": developer_id,
            "gw": msg["gateway_type"],
            "fmt": msg.get("api_format"),
            "hint": msg.get("tool_hint"),
            "seq": msg["seq"],
        },
    )


def mark_stale_instances(conn: Connection) -> int:
    """Active instances without a heartbeat for STALE_AFTER_SECONDS become stale (U1: never freeze the watermark),
    and each opens a `heartbeat_missed` loss from its last heartbeat."""
    rows = conn.execute(
        text(
            "UPDATE capture_instance SET status = 'stale' WHERE status = 'active' "
            "AND last_heartbeat_at < now() - make_interval(secs => :s) "
            "RETURNING instance_id, gateway_type::text AS gw, last_heartbeat_at"
        ),
        {"s": STALE_AFTER_SECONDS},
    ).fetchall()
    for r in rows:
        conn.execute(
            text(
                "INSERT INTO capture_loss (id, instance_id, cause, period_start, count, gateway_type) "
                "SELECT gen_random_uuid(), :i, 'heartbeat_missed', :ps, 1, CAST(:gw AS gateway_type) "
                "WHERE NOT EXISTS (SELECT 1 FROM capture_loss WHERE instance_id = :i "
                "AND cause = 'heartbeat_missed' AND period_end IS NULL)"
            ),
            {"i": r.instance_id, "ps": r.last_heartbeat_at, "gw": r.gw},
        )
    return len(rows)


def _close_superseded(conn: Connection) -> int:
    """A stale instance replaced by a newer one of the same gateway won't return: end its loss and close it."""
    rows = conn.execute(
        text(
            """
            WITH done AS (
                SELECT l.id, l.instance_id, min(n.started_at) AS replaced_at
                FROM capture_loss l
                JOIN capture_instance o ON o.instance_id = l.instance_id AND o.status = 'stale'
                JOIN capture_instance n ON n.gateway_type = o.gateway_type AND n.status = 'active'
                                       AND n.started_at >= l.period_start AND n.instance_id <> o.instance_id
                WHERE l.cause = 'heartbeat_missed' AND l.period_end IS NULL
                GROUP BY l.id, l.instance_id
            ), ended AS (
                UPDATE capture_loss l SET period_end = greatest(d.replaced_at, l.period_start)
                FROM done d WHERE l.id = d.id
                RETURNING d.instance_id
            )
            UPDATE capture_instance SET status = 'closed'
            WHERE instance_id IN (SELECT instance_id FROM ended)
            RETURNING instance_id
            """
        )
    ).fetchall()
    return len(rows)


def _outage(conn: Connection, gateway: str) -> int:
    """Open a capture outage when no instance of ``gateway`` has been active for STALE_AFTER_SECONDS."""
    row = conn.execute(
        text(
            "SELECT count(*) FILTER (WHERE status = 'active') AS active, max(last_heartbeat_at) AS last_seen "
            "FROM capture_instance WHERE gateway_type = CAST(:gw AS gateway_type)"
        ),
        {"gw": gateway},
    ).one()
    if row.active or row.last_seen is None:
        return 0  # capturing, or capture has never run here
    return int(
        conn.execute(
            text(
                "INSERT INTO capture_loss (id, cause, period_start, count, gateway_type) "
                "SELECT gen_random_uuid(), 'heartbeat_missed', :ps, 1, CAST(:gw AS gateway_type) "
                # An instance's own open loss already covers the time since its last heartbeat.
                "WHERE :ps < now() - make_interval(secs => :s) AND NOT EXISTS (SELECT 1 FROM capture_loss "
                "WHERE cause = 'heartbeat_missed' AND period_end IS NULL "
                "AND gateway_type = CAST(:gw AS gateway_type))"
            ),
            {"ps": row.last_seen, "gw": gateway, "s": STALE_AFTER_SECONDS},
        ).rowcount
        or 0
    )


def sweep(conn: Connection, gateway: str) -> dict[str, int]:
    """The sweeper's loss bookkeeping, run every few seconds."""
    return {
        "stale": mark_stale_instances(conn),
        "superseded": _close_superseded(conn),
        "outages": _outage(conn, gateway),
    }
