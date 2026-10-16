"""Write capture messages to PostgreSQL (T046). Fingerprints and metadata only; idempotent per (instance, seq)
and, for the lines of an event sent in parts, per (event, tool call, line)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from gca_core.db.base import bands_to_i64, u32_to_i32
from gca_core.db.models_capture import CapturedLine
from gca_core.messages import line_from_wire

from .loss import STALE_AFTER_SECONDS, close_heartbeat_loss, mark_stale_instances, record_failure, track_seq

__all__ = ["STALE_AFTER_SECONDS", "handle", "mark_stale_instances"]


def _ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    return datetime.fromisoformat(value)


def _credential(conn: Connection, credential_id: str | None) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Return (credential_id, developer_id) for a known credential, else (None, None)."""
    if not credential_id:
        return None, None
    try:
        cid = uuid.UUID(str(credential_id))
    except ValueError:
        return None, None
    row = conn.execute(
        text("SELECT id, developer_id FROM gateway_credential WHERE id = :id"), {"id": cid}
    ).first()
    return (row.id, row.developer_id) if row else (None, None)


def _touch_instance(conn: Connection, msg: dict[str, Any], *, heartbeat: bool) -> None:
    status = "closed" if msg.get("shutting_down") else "active"
    sent = _ts(msg["sent_at"])
    conn.execute(
        text(
            """
            INSERT INTO capture_instance (instance_id, gateway_type, started_at, last_heartbeat_at, last_seq, status)
            VALUES (:iid, :gw, :sent, :sent, :seq, CAST(:status AS instance_status))
            ON CONFLICT (instance_id) DO UPDATE SET
                last_seq = GREATEST(capture_instance.last_seq, EXCLUDED.last_seq),
                last_heartbeat_at = CASE WHEN :hb THEN GREATEST(capture_instance.last_heartbeat_at, EXCLUDED.last_heartbeat_at)
                                         ELSE capture_instance.last_heartbeat_at END,
                status = CASE WHEN :hb THEN EXCLUDED.status ELSE capture_instance.status END
            """
        ),
        {
            "iid": uuid.UUID(msg["instance_id"]),
            "gw": msg["gateway_type"],
            "sent": sent,
            "seq": msg["seq"],
            "status": status,
            "hb": heartbeat,
        },
    )


def _event(conn: Connection, msg: dict[str, Any]) -> None:
    """One event message, or one part of an event sent in parts (same ``event_id``). The event row is created by
    whichever part arrives first; lines are keyed by (event, tool call, line), so a redelivered part adds nothing."""
    credential_id, developer_id = _credential(conn, msg.get("credential_id"))
    received = _ts(msg["received_at"])
    lines = msg.get("lines", [])
    event_id = uuid.UUID(msg["event_id"])
    created = conn.execute(
        text(
            """
            INSERT INTO capture_event (id, instance_id, seq, developer_id, credential_id, gateway_type, api_format,
                                       tool_hint, session_id, model, received_at, status, failure_cause,
                                       tool_call_count, line_count, alg, key_gen)
            VALUES (:id, :iid, :seq, :dev, :cred, CAST(:gw AS gateway_type), CAST(:fmt AS api_format),
                    :hint, :sess, :model, :recv, CAST(:status AS event_status), CAST(:cause AS loss_cause),
                    :tcc, 0, :alg, :kg)
            ON CONFLICT DO NOTHING
            RETURNING id
            """
        ),
        {
            "id": event_id,
            "iid": uuid.UUID(msg["instance_id"]),
            "seq": msg["seq"],
            "dev": developer_id,
            "cred": credential_id,
            "gw": msg["gateway_type"],
            "fmt": msg["api_format"],
            "hint": msg.get("tool_hint"),
            "sess": msg.get("session_id"),
            "model": msg["model"],
            "recv": received,
            "status": msg["status"],
            "cause": msg.get("failure_cause"),
            "tcc": msg.get("tool_call_count", 0),
            "alg": msg["alg"],
            "kg": msg["key_gen"],
        },
    ).first()
    if (
        created is None
        and conn.execute(text("SELECT 1 FROM capture_event WHERE id = :id"), {"id": event_id}).first() is None
    ):
        return  # a redelivery whose (instance, seq) is stored under another event: nothing of this one to add
    if developer_id is None:
        if created is not None:  # counted once per event, not per part
            # An unknown credential is counted, never matched (data-model.md CaptureEvent.developer_id).
            conn.execute(
                text(
                    "INSERT INTO capture_loss (id, instance_id, cause, period_start, period_end, count, gateway_type,"
                    " api_format, tool_hint) VALUES (gen_random_uuid(), :iid, 'unknown_credential', :t, :t, 1,"
                    " CAST(:gw AS gateway_type), CAST(:fmt AS api_format), :hint)"
                ),
                {
                    "iid": uuid.UUID(msg["instance_id"]),
                    "t": received,
                    "gw": msg["gateway_type"],
                    "fmt": msg["api_format"],
                    "hint": msg.get("tool_hint"),
                },
            )
        return
    if not lines:
        return
    rows = []
    for wire in lines:
        ln = line_from_wire(wire)
        rows.append(
            {
                "captured_at": received,
                "capture_event_id": event_id,
                "developer_id": developer_id,
                "tool_call_ordinal": ln["tool_call_ordinal"],
                "line_ordinal": ln["line_ordinal"],
                "path_suffix_fps": list(ln["path_suffix_fps"]),
                "exact_fp": ln["exact_fp"],
                "minhash": u32_to_i32(ln["minhash"]),
                "bands": bands_to_i64(ln["lsh_bands"]),
                "alg": msg["alg"],
                "key_gen": msg["key_gen"],
            }
        )
    line_table = CapturedLine.__table__
    inserted = conn.execute(
        pg_insert(line_table)
        .on_conflict_do_nothing(
            index_elements=["capture_event_id", "tool_call_ordinal", "line_ordinal", "captured_at"]
        )
        .returning(line_table.c.id),
        rows,
    ).fetchall()
    if not inserted:
        return  # a redelivered part
    conn.execute(
        text("UPDATE capture_event SET line_count = line_count + :n WHERE id = :id"),
        {"n": len(inserted), "id": event_id},
    )


def _failure(conn: Connection, msg: dict[str, Any]) -> None:
    _, developer_id = _credential(conn, msg.get("credential_id"))
    record_failure(conn, msg, developer_id, _ts)


def handle(conn: Connection, msg: dict[str, Any]) -> None:
    """Store one validated capture message inside the caller's transaction."""
    kind = msg["kind"]
    track_seq(conn, msg, _ts(msg["sent_at"]))  # before last_seq moves (T088)
    if kind == "event":
        _event(conn, msg)
    elif kind == "failure":
        _failure(conn, msg)
    _touch_instance(conn, msg, heartbeat=kind == "heartbeat")
    if kind == "heartbeat":
        close_heartbeat_loss(conn, uuid.UUID(msg["instance_id"]), msg["gateway_type"], _ts(msg["sent_at"]))
