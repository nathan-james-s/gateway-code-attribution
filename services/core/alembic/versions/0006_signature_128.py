"""128-value MinHash signatures and events sent in parts (T109; research R9; contracts/capture-event.schema.json).

- `captured_line.minhash` holds 128 values (was 32). Fingerprints written before this change came from an
  earlier, unreleased form of alg 1 (3-gram shingles, 32 values) and can't be compared with new ones, so they are
  deleted, with their LSH bands; their capture events keep their metadata and a `line_count` of 0.
- A line is unique per (capture event, tool call, line), replacing the plain index on those columns: ingest
  stores the parts of one event under one row, and a redelivered part must add nothing.

Revision ID: 0006_signature_128
Revises: 0005_coverage_view
"""

from alembic import op

revision = "0006_signature_128"
down_revision = "0005_coverage_view"
branch_labels = None
depends_on = None

UP = """
WITH gone AS (
    DELETE FROM captured_line WHERE array_length(minhash, 1) <> 128 RETURNING id, captured_at, capture_event_id
), bands AS (
    DELETE FROM lsh_band b USING gone g WHERE b.captured_line_id = g.id AND b.captured_at = g.captured_at
)
UPDATE capture_event SET line_count = 0 WHERE id IN (SELECT capture_event_id FROM gone);
ALTER TABLE captured_line DROP CONSTRAINT ck_captured_line_minhash_32;
ALTER TABLE captured_line ADD CONSTRAINT ck_captured_line_minhash_128 CHECK (array_length(minhash, 1) = 128);
DROP INDEX ix_captured_line_event;
CREATE UNIQUE INDEX uq_captured_line_event_line
    ON captured_line (capture_event_id, tool_call_ordinal, line_ordinal, captured_at);
"""

DOWN = """
DROP INDEX uq_captured_line_event_line;
CREATE INDEX ix_captured_line_event ON captured_line (capture_event_id, tool_call_ordinal, line_ordinal);
DELETE FROM lsh_band;
DELETE FROM captured_line;
ALTER TABLE captured_line DROP CONSTRAINT ck_captured_line_minhash_128;
ALTER TABLE captured_line ADD CONSTRAINT ck_captured_line_minhash_32 CHECK (array_length(minhash, 1) = 32);
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
