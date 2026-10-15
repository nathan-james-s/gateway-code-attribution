"""Team totals for Grafana (T086; data-model.md "Reporting views"; FR-026, FR-028).

`v_team_daily`: team x day sums of the line credits on final heads to that team's members, with membership taken
as of each change's merge date (`valid_from <= merged_at < coalesce(valid_to, inf)`; GitHub members plus override
adds minus override removes). Like the other views it has `*_with_broad` and `*_without_broad` columns and **no
per-developer columns**; per-developer figures are served only by the portal's role-checked pages.

Also adds `portal_settings.helm_values`: the attribution settings the chart last applied (gca_core.bootstrap), so
an upgrade applies a changed Helm value without undoing what an admin set on the settings page since.

Revision ID: 0004_team_view
Revises: 0003_webhook_delivery
"""

from alembic import op

revision = "0004_team_view"
down_revision = "0003_webhook_delivery"
branch_labels = None
depends_on = None

UP = """
ALTER TABLE portal_settings ADD COLUMN helm_values JSONB;

CREATE VIEW v_team_daily AS
WITH final_lines AS (
    SELECT l.change_head_id, l.file_path, l.line_no, c.merged_at, h.alg,
           l.credited_developer_id AS developer_id, l.outcome, l.tier
    FROM change c
    JOIN change_head h ON h.id = c.final_head_id
    JOIN line_result l ON l.change_head_id = h.id
    WHERE c.state = 'merged' AND c.merged_at IS NOT NULL AND l.credited_developer_id IS NOT NULL
), member_lines AS (
    -- one row per (team, line) where the credited developer was an effective member at the merge
    SELECT m.team_id, f.change_head_id, f.file_path, f.line_no, f.merged_at, f.alg, f.outcome, f.tier
    FROM final_lines f
    JOIN team_membership m
      ON m.developer_id = f.developer_id
     AND m.valid_from <= f.merged_at AND (m.valid_to IS NULL OR f.merged_at < m.valid_to)
    GROUP BY m.team_id, f.change_head_id, f.file_path, f.line_no, f.merged_at, f.alg, f.outcome, f.tier
    HAVING bool_or(m.source = 'github' OR m.override_action = 'add')
       AND NOT bool_or(m.source = 'override' AND m.override_action = 'remove')
), counted AS (
    SELECT
        t.slug AS team,
        t.name AS team_name,
        date_trunc('day', ml.merged_at) AS day,
        array_agg(DISTINCT alg) AS algs,
        count(*) FILTER (WHERE outcome = 'ai_unmodified') AS ai_unmodified,
        count(*) FILTER (WHERE outcome = 'ai_modified' AND tier = 'anchored') AS ai_modified_anchored,
        count(*) FILTER (WHERE outcome = 'ai_modified' AND tier = 'broad') AS ai_modified_broad,
        count(*) FILTER (WHERE outcome = 'human') AS human,
        count(*) FILTER (WHERE outcome = 'indeterminate') AS indeterminate
    FROM member_lines ml
    JOIN team t ON t.id = ml.team_id
    GROUP BY t.slug, t.name, date_trunc('day', ml.merged_at)
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

GRANT SELECT ON v_team_daily TO gca_reporting;
"""

DOWN = """
DROP VIEW IF EXISTS v_team_daily;
ALTER TABLE portal_settings DROP COLUMN IF EXISTS helm_values;
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
