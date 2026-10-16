"""LSH bands inline in captured_line (T115; research R14; SC-013).

Each captured line stored its 8 band hashes as 8 rows of `lsh_band`, each repeating the line id, timestamp and
developer, with two indexes: about 75% of the 2.6 KB a line took. They're now one `bands int8[8]` column on the
line, with one GIN index on (developer_id, bands) from the btree_gin extension (shipped with PostgreSQL, trusted
since 13, so the database owner can create it). Measured on PostgreSQL 17: 2,647 -> 1,464 bytes per line.

The band values don't change: the same 8 keyed hashes, now as signed int8 (gca_core.db.base.bands_to_i64). A hash
is keyed with its band number, so an overlap search (`bands && ...`) can't confuse bands; the PR check still
applies gcattr.select_candidates to what it fetches, so the candidates and outcomes are exactly as before.

Revision ID: 0007_inline_bands
Revises: 0006_signature_128
"""

from alembic import op

revision = "0007_inline_bands"
down_revision = "0006_signature_128"
branch_labels = None
depends_on = None

# Day partitions for captured_line only (0001 created them for lsh_band too).
PARTITION_FUNCTIONS = """
CREATE OR REPLACE FUNCTION gca_ensure_partitions(days_ahead int) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    d date;
BEGIN
    FOR d IN SELECT generate_series(
        (now() AT TIME ZONE 'UTC')::date - 1, (now() AT TIME ZONE 'UTC')::date + days_ahead, interval '1 day'
    )::date LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF captured_line FOR VALUES FROM (%L) TO (%L)',
            'captured_line_' || to_char(d, 'YYYYMMDD'),
            (d::timestamp AT TIME ZONE 'UTC'), ((d + 1)::timestamp AT TIME ZONE 'UTC'));
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION gca_drop_partitions_older_than(days int) RETURNS int
LANGUAGE plpgsql AS $$
DECLARE
    r record;
    dropped int := 0;
    cutoff date := (now() AT TIME ZONE 'UTC')::date - days;
BEGIN
    FOR r IN
        SELECT c.relname
        FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        JOIN pg_class p ON p.oid = i.inhparent
        WHERE p.relname = 'captured_line'
          AND c.relname ~ '_[0-9]{8}$'
          AND to_date(right(c.relname, 8), 'YYYYMMDD') < cutoff
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I', r.relname);
        dropped := dropped + 1;
    END LOOP;
    RETURN dropped;
END;
$$;
"""

UP = """
CREATE EXTENSION IF NOT EXISTS btree_gin;
ALTER TABLE captured_line ADD COLUMN bands BIGINT[];
UPDATE captured_line cl SET bands = (
    SELECT array_agg(('x' || encode(b.band_hash, 'hex'))::bit(64)::bigint ORDER BY b.band)
    FROM lsh_band b WHERE b.captured_line_id = cl.id AND b.captured_at = cl.captured_at
);
-- Every stored line has its 8 bands; if one didn't, this fails rather than dropping it.
ALTER TABLE captured_line ALTER COLUMN bands SET NOT NULL;
ALTER TABLE captured_line ADD CONSTRAINT ck_captured_line_bands_8 CHECK (array_length(bands, 1) = 8);
CREATE INDEX ix_captured_line_bands ON captured_line USING gin (developer_id, bands);
DROP TABLE lsh_band;
"""

DOWN = """
CREATE TABLE lsh_band (
    captured_line_id BIGINT NOT NULL,
    band SMALLINT NOT NULL,
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL,
    developer_id UUID NOT NULL,
    band_hash BYTEA NOT NULL,
    CONSTRAINT pk_lsh_band PRIMARY KEY (captured_line_id, band, captured_at),
    CONSTRAINT ck_lsh_band_band_0_7 CHECK (band BETWEEN 0 AND 7),
    CONSTRAINT ck_lsh_band_band_hash_8_bytes CHECK (octet_length(band_hash) = 8)
) PARTITION BY RANGE (captured_at);
CREATE INDEX ix_lsh_band_lookup ON lsh_band (developer_id, band, band_hash, captured_at);
CREATE TABLE lsh_band_default PARTITION OF lsh_band DEFAULT;
INSERT INTO lsh_band
SELECT cl.id, (b.n - 1)::smallint, cl.captured_at, cl.developer_id, int8send(b.v)
FROM captured_line cl, unnest(cl.bands) WITH ORDINALITY AS b(v, n);
DROP INDEX ix_captured_line_bands;
ALTER TABLE captured_line DROP CONSTRAINT ck_captured_line_bands_8;
ALTER TABLE captured_line DROP COLUMN bands;
"""


# 0001's functions, which also manage lsh_band partitions (for the downgrade).
PARTITION_FUNCTIONS_0001 = """
CREATE OR REPLACE FUNCTION gca_ensure_partitions(days_ahead int) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    d date;
BEGIN
    FOR d IN SELECT generate_series(
        (now() AT TIME ZONE 'UTC')::date - 1, (now() AT TIME ZONE 'UTC')::date + days_ahead, interval '1 day'
    )::date LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF captured_line FOR VALUES FROM (%L) TO (%L)',
            'captured_line_' || to_char(d, 'YYYYMMDD'),
            (d::timestamp AT TIME ZONE 'UTC'), ((d + 1)::timestamp AT TIME ZONE 'UTC'));
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF lsh_band FOR VALUES FROM (%L) TO (%L)',
            'lsh_band_' || to_char(d, 'YYYYMMDD'),
            (d::timestamp AT TIME ZONE 'UTC'), ((d + 1)::timestamp AT TIME ZONE 'UTC'));
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION gca_drop_partitions_older_than(days int) RETURNS int
LANGUAGE plpgsql AS $$
DECLARE
    r record;
    dropped int := 0;
    cutoff date := (now() AT TIME ZONE 'UTC')::date - days;
BEGIN
    FOR r IN
        SELECT c.relname
        FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        JOIN pg_class p ON p.oid = i.inhparent
        WHERE p.relname IN ('captured_line', 'lsh_band')
          AND c.relname ~ '_[0-9]{8}$'
          AND to_date(right(c.relname, 8), 'YYYYMMDD') < cutoff
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I', r.relname);
        dropped := dropped + 1;
    END LOOP;
    RETURN dropped;
END;
$$;
"""


def upgrade() -> None:
    op.execute(UP)
    op.execute(PARTITION_FUNCTIONS)


def downgrade() -> None:
    op.execute(DOWN)
    op.execute(PARTITION_FUNCTIONS_0001)
