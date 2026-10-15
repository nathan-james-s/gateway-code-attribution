"""Reporting views for Grafana (T060; data-model.md "Reporting views"; research R15).

Views only, with **no per-developer columns**: Grafana has no row-level security, so per-developer data never
reaches it. Every view has `*_with_broad` and `*_without_broad` columns so the "Include broad matches" toggle
(FR-028) is a pure column choice. Without broad matches, broad lines count as human.

Revision ID: 0002_reporting_views
Revises: 0001_initial
"""

from alembic import op

revision = "0002_reporting_views"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

UP = """
CREATE VIEW v_change_summary AS
WITH chosen AS (
    -- one head per change: the final head at merge, otherwise the latest completed head
    SELECT DISTINCT ON (h.change_id) h.*
    FROM change_head h
    WHERE h.status = 'complete'
    ORDER BY h.change_id, h.is_final DESC, h.completed_at DESC
), counted AS (
    SELECT
        c.id AS change_id,
        r.full_name AS repository,
        c.pr_number,
        c.state::text AS change_state,
        c.merged_at,
        x.head_sha,
        x.is_final,
        x.completed_at,
        x.coverage_status::text AS coverage_status,
        x.alg,
        coalesce((x.counts ->> 'ai_unmodified')::int, 0) AS ai_unmodified,
        coalesce((x.counts ->> 'ai_modified_anchored')::int, 0) AS ai_modified_anchored,
        coalesce((x.counts ->> 'ai_modified_broad')::int, 0) AS ai_modified_broad,
        coalesce((x.counts ->> 'human')::int, 0) AS human,
        coalesce((x.counts ->> 'indeterminate')::int, 0) AS indeterminate,
        coalesce((x.counts ->> 'not_observed')::int, 0) AS not_observed,
        coalesce((x.counts ->> 'excluded')::int, 0) AS excluded_files
    FROM chosen x
    JOIN change c ON c.id = x.change_id
    JOIN repository r ON r.id = c.repository_id
)
SELECT
    counted.*,
    ai_unmodified + ai_modified_anchored + ai_modified_broad + human AS attributable_lines,
    ai_unmodified + ai_modified_anchored + ai_modified_broad AS ai_lines_with_broad,
    ai_unmodified + ai_modified_anchored AS ai_lines_without_broad,
    human AS human_lines_with_broad,
    human + ai_modified_broad AS human_lines_without_broad,
    round(100.0 * (ai_unmodified + ai_modified_anchored + ai_modified_broad)
          / nullif(ai_unmodified + ai_modified_anchored + ai_modified_broad + human, 0), 2) AS ai_pct_with_broad,
    round(100.0 * (ai_unmodified + ai_modified_anchored)
          / nullif(ai_unmodified + ai_modified_anchored + ai_modified_broad + human, 0), 2) AS ai_pct_without_broad,
    round(100.0 * human
          / nullif(ai_unmodified + ai_modified_anchored + ai_modified_broad + human, 0), 2) AS human_pct_with_broad,
    round(100.0 * (human + ai_modified_broad)
          / nullif(ai_unmodified + ai_modified_anchored + ai_modified_broad + human, 0), 2) AS human_pct_without_broad
FROM counted;

CREATE VIEW v_repository_daily AS
SELECT
    repository,
    date_trunc('day', merged_at) AS day,
    count(*) AS changes,
    count(*) FILTER (WHERE coverage_status <> 'complete') AS changes_not_fully_covered,
    array_agg(DISTINCT alg) AS algs,
    sum(attributable_lines) AS attributable_lines,
    sum(ai_lines_with_broad) AS ai_lines_with_broad,
    sum(ai_lines_without_broad) AS ai_lines_without_broad,
    sum(human_lines_with_broad) AS human_lines_with_broad,
    sum(human_lines_without_broad) AS human_lines_without_broad,
    sum(indeterminate) AS indeterminate,
    sum(not_observed) AS not_observed,
    round(100.0 * sum(ai_lines_with_broad) / nullif(sum(attributable_lines), 0), 2) AS ai_pct_with_broad,
    round(100.0 * sum(ai_lines_without_broad) / nullif(sum(attributable_lines), 0), 2) AS ai_pct_without_broad,
    round(100.0 * sum(human_lines_with_broad) / nullif(sum(attributable_lines), 0), 2) AS human_pct_with_broad,
    round(100.0 * sum(human_lines_without_broad) / nullif(sum(attributable_lines), 0), 2) AS human_pct_without_broad
FROM v_change_summary
WHERE is_final AND merged_at IS NOT NULL
GROUP BY repository, date_trunc('day', merged_at);

GRANT SELECT ON v_change_summary, v_repository_daily TO gca_reporting;
"""

DOWN = """
DROP VIEW IF EXISTS v_repository_daily;
DROP VIEW IF EXISTS v_change_summary;
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
