"""Daily maintenance (T076; FR-036; data-model.md "Retention").

- Retired key generations past `expires_at` become `expired`. The portal's key sync then removes their key files
  from the Secret, so captures under them are no longer matchable (they're past retention anyway).
- Captured-line and LSH-band partitions older than `retention_days` are dropped.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

__all__ = ["daily"]


def daily(conn: Connection) -> dict[str, int]:
    expired = conn.execute(
        text("""
            UPDATE key_generation SET status = 'expired'
            WHERE status = 'retired' AND expires_at IS NOT NULL AND expires_at <= now()
            RETURNING id
        """)
    ).fetchall()
    days = conn.execute(text("SELECT retention_days FROM portal_settings WHERE id = 1")).scalar() or 90
    dropped = conn.execute(text("SELECT gca_drop_partitions_older_than(:d)"), {"d": int(days)}).scalar() or 0
    return {"expired_generations": len(expired), "dropped_partitions": int(dropped)}
