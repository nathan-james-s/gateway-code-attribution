"""Capture loss bookkeeping and coverage views (T088, T091; FR-005, FR-007, FR-030; research R12).

`capture_loss` gains:
- `seq_first`, `seq_last`: the missing span of a `seq_gap`. A late (redelivered) message inside the span splits
  it, so a reordering never counts as loss;
- `source_seq`: the sequence number of the `failure` message a row came from. Unique per instance, so a
  redelivered failure report is counted once.

Views for Grafana, all without per-developer columns:
- `v_coverage_daily`: capture loss by day x gateway x API format x tool x cause;
- `v_capture_daily`: responses captured by day x gateway x API format x tool x algorithm version (the observed
  combinations);
- `v_unmapped_daily`: per day, how many distinct GitHub accounts without a gateway credential were credited with
  lines (one head per change), and how many lines that was. Counts only; the portal lists the accounts (T091).

Revision ID: 0005_coverage_view
Revises: 0004_team_view
"""

from alembic import op

revision = "0005_coverage_view"
down_revision = "0004_team_view"
branch_labels = None
depends_on = None

UP = """
ALTER TABLE capture_loss ADD COLUMN seq_first BIGINT, ADD COLUMN seq_last BIGINT, ADD COLUMN source_seq BIGINT;
ALTER TABLE capture_loss ADD CONSTRAINT ck_capture_loss_seq_span
    CHECK ((seq_first IS NULL) = (seq_last IS NULL) AND (seq_first IS NULL OR seq_last >= seq_first));
CREATE UNIQUE INDEX uq_capture_loss_source ON capture_loss (instance_id, source_seq) WHERE source_seq IS NOT NULL;
CREATE INDEX ix_capture_loss_open ON capture_loss (instance_id, cause) WHERE period_end IS NULL;

CREATE VIEW v_coverage_daily AS
SELECT
    date_trunc('day', period_start) AS day,
    gateway_type::text AS gateway_type,
    coalesce(api_format::text, 'unknown') AS api_format,
    coalesce(tool_hint, 'unknown') AS tool,
    cause::text AS cause,
    sum(count) AS lost,
    count(*) AS periods,
    count(*) FILTER (WHERE period_end IS NULL) AS ongoing,
    sum(extract(epoch FROM coalesce(period_end, now()) - period_start)) AS seconds
FROM capture_loss
GROUP BY 1, 2, 3, 4, 5;

CREATE VIEW v_capture_daily AS
SELECT
    date_trunc('day', received_at) AS day,
    gateway_type::text AS gateway_type,
    api_format::text AS api_format,
    coalesce(tool_hint, 'unknown') AS tool,
    alg,
    count(*) AS responses,
    count(*) FILTER (WHERE status = 'captured') AS captured,
    count(*) FILTER (WHERE status = 'partial') AS partial,
    count(*) FILTER (WHERE developer_id IS NULL) AS unknown_credential
FROM capture_event
GROUP BY 1, 2, 3, 4, 5;

CREATE VIEW v_unmapped_daily AS
WITH chosen AS (
    -- one head per change, as in v_change_summary: the final head at merge, otherwise the latest completed one
    SELECT DISTINCT ON (h.change_id) h.id, h.completed_at
    FROM change_head h
    WHERE h.status = 'complete'
    ORDER BY h.change_id, h.is_final DESC, h.completed_at DESC
)
SELECT
    date_trunc('day', x.completed_at) AS day,
    count(DISTINCT l.credited_github_id) AS unmapped_accounts,
    count(*) AS not_observed_lines
FROM chosen x
JOIN line_result l ON l.change_head_id = x.id
WHERE l.outcome = 'not_observed' AND l.credited_github_id IS NOT NULL
GROUP BY 1;

GRANT SELECT ON v_coverage_daily, v_capture_daily, v_unmapped_daily TO gca_reporting;
"""

DOWN = """
DROP VIEW IF EXISTS v_unmapped_daily;
DROP VIEW IF EXISTS v_capture_daily;
DROP VIEW IF EXISTS v_coverage_daily;
DROP INDEX IF EXISTS ix_capture_loss_open;
DROP INDEX IF EXISTS uq_capture_loss_source;
ALTER TABLE capture_loss DROP CONSTRAINT IF EXISTS ck_capture_loss_seq_span;
ALTER TABLE capture_loss DROP COLUMN IF EXISTS source_seq, DROP COLUMN IF EXISTS seq_last,
    DROP COLUMN IF EXISTS seq_first;
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
