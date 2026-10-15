"""T060: reporting views aggregate without per-developer columns; the reporting role reads views only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine

FORBIDDEN = {"developer_id", "credited_developer_id", "credited_github_id", "github_login", "github_id"}


def test_views_have_no_per_developer_columns(pg_engine: Engine) -> None:
    with pg_engine.connect() as conn:
        for view in ("v_change_summary", "v_repository_daily"):
            cols = set(
                conn.execute(
                    text("SELECT column_name FROM information_schema.columns WHERE table_name = :v"),
                    {"v": view},
                ).scalars()
            )
            assert cols and not (cols & FORBIDDEN), (view, cols & FORBIDDEN)
            assert {"ai_pct_with_broad", "ai_pct_without_broad"} <= cols


def test_reporting_role_reads_views_not_tables(pg_engine: Engine) -> None:
    with pg_engine.connect() as conn:

        def can(obj: str) -> bool:
            return bool(
                conn.execute(
                    text("SELECT has_table_privilege('gca_reporting', :o, 'SELECT')"), {"o": obj}
                ).scalar()
            )

        assert can("v_change_summary") and can("v_repository_daily")
        assert not can("line_result") and not can("captured_line") and not can("developer")


def test_change_summary_toggle(pg_engine: Engine) -> None:
    counts = (
        '{"ai_unmodified": 6, "ai_modified_anchored": 1, "ai_modified_broad": 1, "human": 2, '
        '"indeterminate": 3, "not_observed": 4, "excluded": 1}'
    )
    with pg_engine.begin() as conn:
        repo = conn.execute(
            text(
                "INSERT INTO repository (id, github_id, full_name, installation_id, active) "
                "VALUES (gen_random_uuid(), :g, :fn, 1, true) RETURNING id"
            ),
            {"g": uuid.uuid4().int % 10**9, "fn": f"acme/views{uuid.uuid4().hex[:6]}"},
        ).scalar()
        change = conn.execute(
            text(
                "INSERT INTO change (id, repository_id, pr_number, opened_by_github_id, state, merged_at) "
                "VALUES (gen_random_uuid(), :r, 1, 1, 'merged', :t) RETURNING id"
            ),
            {"r": repo, "t": datetime.now(UTC)},
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO change_head (id, change_id, head_sha, event_received_at, status, coverage_status, "
                "coverage_reasons, key_gens, counts, excluded_paths, is_final, attempts, completed_at, alg) "
                "VALUES (gen_random_uuid(), :c, 'abc', now(), 'complete', 'complete', '{}', '{1}', "
                "CAST(:counts AS jsonb), '[]', true, 1, now(), 1)"
            ),
            {"c": change, "counts": counts},
        )
        row = (
            conn.execute(text("SELECT * FROM v_change_summary WHERE change_id = :c"), {"c": change})
            .mappings()
            .one()
        )
        assert row["attributable_lines"] == 10
        assert row["ai_pct_with_broad"] == 80 and row["ai_pct_without_broad"] == 70
        assert row["human_pct_without_broad"] == 30 and row["not_observed"] == 4 and row["alg"] == 1
        daily = (
            conn.execute(
                text(
                    "SELECT * FROM v_repository_daily WHERE repository = (SELECT full_name FROM repository WHERE id = :r)"
                ),
                {"r": repo},
            )
            .mappings()
            .one()
        )
        assert daily["changes"] == 1 and daily["ai_lines_without_broad"] == 7
