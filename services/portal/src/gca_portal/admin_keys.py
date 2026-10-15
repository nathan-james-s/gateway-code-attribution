"""Fingerprint key rotation (T076; FR-036).

Rotation adds a new active generation and retires the old one, which stays usable for matching until
`expires_at = retired_at + retention_days`. The new key is written to the Secret before the database records
it, so a failure in between leaves a usable key rather than a generation with no key behind it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .keysecret import KeySecret

__all__ = ["rotate", "sync_secret"]


def rotate(engine: Engine, secret: KeySecret, retention_days: int) -> int:
    with engine.connect() as conn:
        new_gen = int(conn.execute(text("SELECT coalesce(max(id), 0) + 1 FROM key_generation")).scalar_one())
    secret.add_generation(new_gen)
    now = datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE key_generation SET status = 'retired', retired_at = :now, expires_at = :exp "
                "WHERE status = 'active'"
            ),
            {"now": now, "exp": now + timedelta(days=retention_days)},
        )
        conn.execute(text("INSERT INTO key_generation (id, status) VALUES (:g, 'active')"), {"g": new_gen})
    return new_gen


def sync_secret(engine: Engine, secret: KeySecret) -> set[int]:
    """Remove expired generations' key files from the Secret (never the active one). Returns what was removed."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, status::text FROM key_generation")).fetchall()
    expired = {int(r[0]) for r in rows if r[1] == "expired"}
    active = {int(r[0]) for r in rows if r[1] == "active"}
    remove = (secret.generations() & expired) - active
    secret.remove_generations(remove)
    return remove
