"""Capture watermark (T047; shared by ingest and prcheck; data-model.md "Watermark"; research R12)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection


def current_watermark(conn: Connection) -> datetime | None:
    """min(last_heartbeat_at) over active instances. Stale and closed instances never hold it back.

    None when no instance is active: PR heads stay pending until the cap (FR-017).
    """
    return conn.execute(
        text("SELECT min(last_heartbeat_at) FROM capture_instance WHERE status = 'active'")
    ).scalar()
