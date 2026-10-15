"""Incomplete coverage from capture loss (T089; FR-022; research R12).

A head's coverage is incomplete when any `CaptureLoss` overlaps its matching window
`[event_received_at - matching_window, event_received_at]` and could have hidden one of its credited authors'
AI output: the loss is that developer's, or it belongs to no developer (a sequence gap, missed heartbeats, a
buffer overflow) and so could be anyone's. Unknown-credential losses are nobody's in the stack, so they never
count. The check summary lists one reason per cause.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection

__all__ = ["loss_reasons"]

LABELS = {
    "truncated": "cut off mid-response",
    "unparsable": "unreadable",
    "unexpected_format": "in an unexpected format",
    "buffer_overflow": "dropped while the queue was unreachable",
    "publish_failed": "not published to the queue",
    "unsupported_combination": "from a tool or API format capture can't read",
}

_LOSSES = text("""
    SELECT cause::text AS cause, sum(count) AS n, count(*) AS periods,
           bool_or(period_end IS NULL) AS ongoing,
           sum(extract(epoch FROM least(coalesce(period_end, :until), :until) - greatest(period_start, :since)))
               AS seconds
    FROM capture_loss
    WHERE period_start <= :until AND coalesce(period_end, 'infinity') >= :since
      AND cause <> 'unknown_credential'
      AND (developer_id IS NULL OR developer_id = ANY(:devs))
    GROUP BY cause
    ORDER BY cause
""")


def _duration(seconds: float) -> str:
    s = max(int(seconds), 1)
    if s < 120:
        return f"{s} seconds"
    if s < 7200:
        return f"{s // 60} minutes"
    return f"{s // 3600} hours"


def loss_reasons(
    conn: Connection, developer_ids: Collection[uuid.UUID], received_at: datetime, window_days: int
) -> list[str]:
    since = received_at - timedelta(days=window_days)
    rows = conn.execute(
        _LOSSES, {"since": since, "until": received_at, "devs": list(developer_ids)}
    ).fetchall()
    reasons = []
    for r in rows:
        if r.cause == "heartbeat_missed":
            tail = ", and it still isn't" if r.ongoing else ""
            reasons.append(
                f"capture wasn't reporting for {_duration(float(r.seconds or 0))} in the matching window{tail}"
            )
        elif r.cause == "seq_gap":
            reasons.append(f"{r.n} capture messages never reached ingest (sequence gap)")
        else:
            reasons.append(f"{r.n} AI responses {LABELS.get(r.cause, r.cause)} weren't captured ({r.cause})")
    return reasons
