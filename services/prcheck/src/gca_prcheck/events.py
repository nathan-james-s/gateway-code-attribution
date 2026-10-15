"""PR events shared by polling and webhook delivery (T052, T069, T071; FR-018, FR-020).

Every new head gets its own ChangeHead; earlier heads keep their results. At merge, the merged head becomes the
final result. Re-running a head recomputes the same head idempotently.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

__all__ = ["on_closed", "rerun_head"]


def on_closed(engine: Engine, repository_id: uuid.UUID, pr: dict[str, Any]) -> uuid.UUID | None:
    """Record a closed PR. If it merged, its head at merge becomes the final result. Returns that head's id."""
    from .polling import record_head

    merged = bool(pr.get("merged") or pr.get("merged_at"))
    final_id: uuid.UUID | None = None
    if merged:
        # The merged head may not be known yet (pushed and merged within one poll interval).
        record_head(engine, repository_id, pr)
    with engine.begin() as conn:
        change_id = conn.execute(
            text("SELECT id FROM change WHERE repository_id = :r AND pr_number = :pr"),
            {"r": repository_id, "pr": pr["number"]},
        ).scalar()
        if change_id is None:
            return None
        if merged:
            final_id = conn.execute(
                text("SELECT id FROM change_head WHERE change_id = :c AND head_sha = :sha"),
                {"c": change_id, "sha": pr["head"]["sha"]},
            ).scalar()
            conn.execute(
                text("UPDATE change_head SET is_final = (id = :f) WHERE change_id = :c"),
                {"f": final_id, "c": change_id},
            )
        conn.execute(
            text("""
                UPDATE change SET state = CAST(:state AS change_state), merged_at = :merged_at,
                       final_head_id = :final
                WHERE id = :c
            """),
            {
                "state": "merged" if merged else "closed",
                "merged_at": pr.get("merged_at"),
                "final": final_id,
                "c": change_id,
            },
        )
    return final_id


def rerun_head(engine: Engine, full_name: str, head_sha: str) -> uuid.UUID | None:
    """`check_run.rerequested`: attribute the same head again. Results are replaced, not added (FR-020)."""
    with engine.begin() as conn:
        return conn.execute(
            text("""
                UPDATE change_head h SET status = 'pending', attempts = 0, check_run_id = NULL
                FROM change c JOIN repository r ON r.id = c.repository_id
                WHERE h.change_id = c.id AND r.full_name = :fn AND h.head_sha = :sha
                RETURNING h.id
            """),
            {"fn": full_name, "sha": head_sha},
        ).scalar()
