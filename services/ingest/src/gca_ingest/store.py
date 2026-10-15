"""Write capture messages to PostgreSQL (T046). Fingerprints and metadata only; idempotent per (instance, seq)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, text
from sqlalchemy.engine import Connection

from gca_core.db.base import u32_to_i32
from gca_core.db.models_capture import CapturedLine, LshBand
from gca_core.messages import line_from_wire

__all__ = ["handle", "mark_stale_instances"]

STALE_AFTER_SECONDS = 15


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
    credential_id, developer_id = _credential(conn, msg.get("credential_id"))
    received = _ts(msg["received_at"])
    lines = msg.get("lines", [])
    row = conn.execute(
        text(
            """
            INSERT INTO capture_event (id, instance_id, seq, developer_id, credential_id, gateway_type, api_format,
                                       tool_hint, session_id, model, received_at, status, failure_cause,
                                       tool_call_count, line_count, alg, key_gen)
            VALUES (gen_random_uuid(), :iid, :seq, :dev, :cred, CAST(:gw AS gateway_type), CAST(:fmt AS api_format),
                    :hint, :sess, :model, :recv, CAST(:status AS event_status), CAST(:cause AS loss_cause),
                    :tcc, :lc, :alg, :kg)
            ON CONFLICT (instance_id, seq) DO NOTHING
            RETURNING id
            """
        ),
        {
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
            "lc": len(lines) if developer_id else 0,
            "alg": msg["alg"],
            "kg": msg["key_gen"],
        },
    ).first()
    if row is None:
        return  # duplicate delivery: already stored
    if developer_id is None:
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
    params = []
    for wire in lines:
        ln = line_from_wire(wire)
        params.append(
            {
                "t": received,
                "ev": row.id,
                "dev": developer_id,
                "tco": ln["tool_call_ordinal"],
                "lo": ln["line_ordinal"],
                "p": list(ln["path_suffix_fps"]),
                "x": ln["exact_fp"],
                "m": u32_to_i32(ln["minhash"]),
                "alg": msg["alg"],
                "kg": msg["key_gen"],
                "bands": ln["lsh_bands"],
            }
        )
    line_table = CapturedLine.__table__
    ids = conn.execute(
        insert(line_table).returning(line_table.c.id, sort_by_parameter_order=True),
        [
            {
                "captured_at": p["t"],
                "capture_event_id": p["ev"],
                "developer_id": p["dev"],
                "tool_call_ordinal": p["tco"],
                "line_ordinal": p["lo"],
                "path_suffix_fps": p["p"],
                "exact_fp": p["x"],
                "minhash": p["m"],
                "alg": p["alg"],
                "key_gen": p["kg"],
            }
            for p in params
        ],
    ).fetchall()
    band_rows = []
    for (line_id,), p in zip(ids, params, strict=True):
        for b, h in enumerate(p["bands"]):
            band_rows.append(
                {
                    "captured_line_id": line_id,
                    "band": b,
                    "captured_at": received,
                    "developer_id": developer_id,
                    "band_hash": h,
                }
            )
    conn.execute(insert(LshBand.__table__), band_rows)


def _failure(conn: Connection, msg: dict[str, Any]) -> None:
    _, developer_id = _credential(conn, msg.get("credential_id"))
    conn.execute(
        text(
            "INSERT INTO capture_loss (id, instance_id, cause, period_start, period_end, count, developer_id,"
            " gateway_type, api_format, tool_hint) VALUES (gen_random_uuid(), :iid, CAST(:cause AS loss_cause),"
            " :ps, :pe, :count, :dev, CAST(:gw AS gateway_type), CAST(:fmt AS api_format), :hint)"
        ),
        {
            "iid": uuid.UUID(msg["instance_id"]),
            "cause": msg["cause"],
            "ps": _ts(msg["period_start"]),
            "pe": _ts(msg["period_end"]),
            "count": msg["count"],
            "dev": developer_id,
            "gw": msg["gateway_type"],
            "fmt": msg.get("api_format"),
            "hint": msg.get("tool_hint"),
        },
    )


def handle(conn: Connection, msg: dict[str, Any]) -> None:
    """Store one validated capture message inside the caller's transaction."""
    kind = msg["kind"]
    if kind == "event":
        _event(conn, msg)
    elif kind == "failure":
        _failure(conn, msg)
    _touch_instance(conn, msg, heartbeat=kind == "heartbeat")


def mark_stale_instances(conn: Connection) -> int:
    """Active instances without a heartbeat for STALE_AFTER_SECONDS become stale (U1: never freeze the watermark)."""
    result = conn.execute(
        text(
            "UPDATE capture_instance SET status = 'stale' WHERE status = 'active' "
            "AND last_heartbeat_at < now() - make_interval(secs => :s)"
        ),
        {"s": STALE_AFTER_SECONDS},
    )
    return int(result.rowcount or 0)
