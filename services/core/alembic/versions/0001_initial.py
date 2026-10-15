"""Initial schema (T030): all tables from data-model.md, daily partitions, reporting role, seed rows.

The DDL below was generated once from the SQLAlchemy models and is frozen here, so later model edits can't
silently change this migration. Later schema changes get their own migrations.

Revision ID: 0001_initial
Revises:
"""

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

DDL = """
CREATE TYPE gateway_type AS ENUM ('agentgateway', 'litellm');
CREATE TYPE instance_status AS ENUM ('active', 'stale', 'closed');
CREATE TYPE key_status AS ENUM ('active', 'retired', 'expired');
CREATE TYPE team_source AS ENUM ('github', 'manual');
CREATE TYPE loss_cause AS ENUM ('seq_gap', 'heartbeat_missed', 'truncated', 'unparsable', 'unexpected_format', 'buffer_overflow', 'publish_failed', 'unsupported_combination', 'unknown_credential');
CREATE TYPE api_format AS ENUM ('openai_chat', 'openai_responses', 'anthropic_messages', 'gemini_native');
CREATE TYPE change_state AS ENUM ('open', 'merged', 'closed');
CREATE TYPE credential_status AS ENUM ('active', 'revoked');
CREATE TYPE lead_source AS ENUM ('github_maintainer', 'override');
CREATE TYPE override_action AS ENUM ('add', 'remove');
CREATE TYPE membership_source AS ENUM ('github', 'override');
CREATE TYPE viewer_role AS ENUM ('admin', 'team_lead');
CREATE TYPE grant_action AS ENUM ('grant', 'revoke');
CREATE TYPE event_status AS ENUM ('captured', 'partial', 'failed');
CREATE TYPE head_status AS ENUM ('pending', 'processing', 'complete', 'error');
CREATE TYPE coverage_status AS ENUM ('complete', 'incomplete', 'pending', 'not_observed');
CREATE TYPE line_outcome AS ENUM ('ai_unmodified', 'ai_modified', 'human', 'indeterminate', 'not_observed');
CREATE TYPE match_tier AS ENUM ('exact', 'anchored', 'broad', 'none');
CREATE TYPE match_confidence AS ENUM ('high', 'lower');
CREATE SEQUENCE captured_line_id_seq;
CREATE TABLE algorithm_version (
    alg INTEGER NOT NULL, 
    library_version VARCHAR(64) NOT NULL, 
    unicode_version VARCHAR(16) NOT NULL, 
    anchored_threshold NUMERIC(4, 3) NOT NULL, 
    broad_threshold NUMERIC(4, 3) NOT NULL, 
    minhash_size SMALLINT NOT NULL, 
    lsh_bands SMALLINT NOT NULL, 
    lsh_rows SMALLINT NOT NULL, 
    common_lines_version VARCHAR(16) NOT NULL, 
    released_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_algorithm_version PRIMARY KEY (alg)
);
CREATE TABLE capture_instance (
    instance_id UUID NOT NULL, 
    gateway_type gateway_type NOT NULL, 
    started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    last_heartbeat_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    last_seq BIGINT NOT NULL, 
    status instance_status NOT NULL, 
    CONSTRAINT pk_capture_instance PRIMARY KEY (instance_id)
);
CREATE TABLE captured_line (
    id BIGINT DEFAULT nextval('captured_line_id_seq') NOT NULL, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    capture_event_id UUID NOT NULL, 
    developer_id UUID NOT NULL, 
    tool_call_ordinal INTEGER NOT NULL, 
    line_ordinal INTEGER NOT NULL, 
    path_suffix_fps BYTEA[] NOT NULL, 
    exact_fp BYTEA NOT NULL, 
    minhash INTEGER[] NOT NULL, 
    alg INTEGER NOT NULL, 
    key_gen SMALLINT NOT NULL, 
    CONSTRAINT pk_captured_line PRIMARY KEY (id, captured_at), 
    CONSTRAINT ck_captured_line_exact_fp_16_bytes CHECK (octet_length(exact_fp) = 16), 
    CONSTRAINT ck_captured_line_minhash_32 CHECK (array_length(minhash, 1) = 32), 
    CONSTRAINT ck_captured_line_at_most_3_path_fps CHECK (coalesce(array_length(path_suffix_fps, 1), 0) <= 3)
)
 PARTITION BY RANGE (captured_at);
CREATE INDEX ix_captured_line_dev_exact ON captured_line (developer_id, exact_fp, captured_at);
CREATE INDEX ix_captured_line_event ON captured_line (capture_event_id, tool_call_ordinal, line_ordinal);
CREATE TABLE developer (
    id UUID NOT NULL, 
    github_id BIGINT NOT NULL, 
    github_login VARCHAR(64) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    last_seen_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_developer PRIMARY KEY (id), 
    CONSTRAINT uq_developer_github_id UNIQUE (github_id)
);
CREATE TABLE key_generation (
    id SMALLINT NOT NULL, 
    status key_status NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    retired_at TIMESTAMP WITH TIME ZONE, 
    expires_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_key_generation PRIMARY KEY (id), 
    CONSTRAINT ck_key_generation_retired_when_not_active CHECK (status = 'active' OR retired_at IS NOT NULL)
);
CREATE UNIQUE INDEX uq_key_generation_one_active ON key_generation (status) WHERE status = 'active';
CREATE TABLE lsh_band (
    captured_line_id BIGINT NOT NULL, 
    band SMALLINT NOT NULL, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    developer_id UUID NOT NULL, 
    band_hash BYTEA NOT NULL, 
    CONSTRAINT pk_lsh_band PRIMARY KEY (captured_line_id, band, captured_at), 
    CONSTRAINT ck_lsh_band_band_0_7 CHECK (band BETWEEN 0 AND 7), 
    CONSTRAINT ck_lsh_band_band_hash_8_bytes CHECK (octet_length(band_hash) = 8)
)
 PARTITION BY RANGE (captured_at);
CREATE INDEX ix_lsh_band_lookup ON lsh_band (developer_id, band, band_hash, captured_at);
CREATE TABLE portal_settings (
    id INTEGER NOT NULL, 
    per_developer_enabled BOOLEAN DEFAULT true NOT NULL, 
    visible_roles TEXT[] DEFAULT ARRAY['admin','team_lead'] NOT NULL, 
    matching_window_days INTEGER DEFAULT 14 NOT NULL, 
    retention_days INTEGER DEFAULT 90 NOT NULL, 
    exclusion_rules TEXT[] DEFAULT ARRAY['**/*.lock','**/package-lock.json','**/vendor/**','**/node_modules/**','**/*.min.*','**/dist/**'] NOT NULL, 
    CONSTRAINT pk_portal_settings PRIMARY KEY (id), 
    CONSTRAINT ck_portal_settings_singleton CHECK (id = 1)
);
CREATE TABLE repository (
    id UUID NOT NULL, 
    github_id BIGINT NOT NULL, 
    full_name VARCHAR(256) NOT NULL, 
    installation_id BIGINT NOT NULL, 
    active BOOLEAN NOT NULL, 
    added_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_repository PRIMARY KEY (id), 
    CONSTRAINT uq_repository_github_id UNIQUE (github_id)
);
CREATE TABLE team (
    id UUID NOT NULL, 
    github_team_id BIGINT, 
    slug VARCHAR(128) NOT NULL, 
    name VARCHAR(256) NOT NULL, 
    source team_source NOT NULL, 
    synced_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_team PRIMARY KEY (id), 
    CONSTRAINT uq_team_github_team_id UNIQUE (github_team_id), 
    CONSTRAINT uq_team_slug UNIQUE (slug)
);
CREATE TABLE capture_loss (
    id UUID NOT NULL, 
    instance_id UUID, 
    cause loss_cause NOT NULL, 
    period_start TIMESTAMP WITH TIME ZONE NOT NULL, 
    period_end TIMESTAMP WITH TIME ZONE, 
    count INTEGER NOT NULL, 
    developer_id UUID, 
    gateway_type gateway_type NOT NULL, 
    api_format api_format, 
    tool_hint VARCHAR(64), 
    CONSTRAINT pk_capture_loss PRIMARY KEY (id), 
    CONSTRAINT ck_capture_loss_count_positive CHECK (count >= 1), 
    CONSTRAINT fk_capture_loss_developer_id_developer FOREIGN KEY(developer_id) REFERENCES developer (id)
);
CREATE INDEX ix_capture_loss_period ON capture_loss (period_start, period_end);
CREATE TABLE change (
    id UUID NOT NULL, 
    repository_id UUID NOT NULL, 
    pr_number INTEGER NOT NULL, 
    opened_by_github_id BIGINT NOT NULL, 
    state change_state NOT NULL, 
    final_head_id UUID, 
    merged_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_change PRIMARY KEY (id), 
    CONSTRAINT uq_change_repository_id UNIQUE (repository_id, pr_number), 
    CONSTRAINT fk_change_repository_id_repository FOREIGN KEY(repository_id) REFERENCES repository (id)
);
CREATE TABLE gateway_credential (
    id UUID NOT NULL, 
    developer_id UUID NOT NULL, 
    gateway_type gateway_type NOT NULL, 
    key_hash VARCHAR(71) NOT NULL, 
    gateway_ref TEXT, 
    status credential_status NOT NULL, 
    issued_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    revoked_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_gateway_credential PRIMARY KEY (id), 
    CONSTRAINT ck_gateway_credential_key_hash_format CHECK (key_hash ~ '^sha256:[0-9a-f]{64}$'), 
    CONSTRAINT ck_gateway_credential_revoked_at_iff_revoked CHECK ((status = 'revoked') = (revoked_at IS NOT NULL)), 
    CONSTRAINT fk_gateway_credential_developer_id_developer FOREIGN KEY(developer_id) REFERENCES developer (id), 
    CONSTRAINT uq_gateway_credential_key_hash UNIQUE (key_hash)
);
CREATE INDEX ix_gateway_credential_developer_id ON gateway_credential (developer_id);
CREATE TABLE identity_override (
    id UUID NOT NULL, 
    github_id BIGINT NOT NULL, 
    developer_id UUID NOT NULL, 
    reason TEXT NOT NULL, 
    created_by UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_identity_override PRIMARY KEY (id), 
    CONSTRAINT ck_identity_override_reason_required CHECK (length(trim(reason)) > 0), 
    CONSTRAINT uq_identity_override_github_id UNIQUE (github_id), 
    CONSTRAINT fk_identity_override_developer_id_developer FOREIGN KEY(developer_id) REFERENCES developer (id), 
    CONSTRAINT fk_identity_override_created_by_developer FOREIGN KEY(created_by) REFERENCES developer (id)
);
CREATE TABLE team_lead (
    id UUID NOT NULL, 
    team_id UUID NOT NULL, 
    developer_id UUID NOT NULL, 
    source lead_source NOT NULL, 
    override_action override_action, 
    CONSTRAINT pk_team_lead PRIMARY KEY (id), 
    CONSTRAINT uq_team_lead_team_id UNIQUE (team_id, developer_id, source), 
    CONSTRAINT fk_team_lead_team_id_team FOREIGN KEY(team_id) REFERENCES team (id), 
    CONSTRAINT fk_team_lead_developer_id_developer FOREIGN KEY(developer_id) REFERENCES developer (id)
);
CREATE INDEX ix_team_lead_team_id ON team_lead (team_id);
CREATE TABLE team_membership (
    id UUID NOT NULL, 
    team_id UUID NOT NULL, 
    developer_id UUID NOT NULL, 
    source membership_source NOT NULL, 
    override_action override_action, 
    valid_from TIMESTAMP WITH TIME ZONE NOT NULL, 
    valid_to TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_team_membership PRIMARY KEY (id), 
    CONSTRAINT ck_team_membership_valid_period CHECK (valid_to IS NULL OR valid_to > valid_from), 
    CONSTRAINT fk_team_membership_team_id_team FOREIGN KEY(team_id) REFERENCES team (id), 
    CONSTRAINT fk_team_membership_developer_id_developer FOREIGN KEY(developer_id) REFERENCES developer (id)
);
CREATE INDEX ix_team_membership_team_id ON team_membership (team_id);
CREATE INDEX ix_team_membership_developer_id ON team_membership (developer_id);
CREATE TABLE viewer_role_grant (
    id UUID NOT NULL, 
    developer_id UUID NOT NULL, 
    role viewer_role NOT NULL, 
    team_id UUID, 
    action grant_action NOT NULL, 
    created_by UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_viewer_role_grant PRIMARY KEY (id), 
    CONSTRAINT ck_viewer_role_grant_team_lead_requires_team CHECK (role <> 'team_lead' OR team_id IS NOT NULL), 
    CONSTRAINT fk_viewer_role_grant_developer_id_developer FOREIGN KEY(developer_id) REFERENCES developer (id), 
    CONSTRAINT fk_viewer_role_grant_team_id_team FOREIGN KEY(team_id) REFERENCES team (id), 
    CONSTRAINT fk_viewer_role_grant_created_by_developer FOREIGN KEY(created_by) REFERENCES developer (id)
);
CREATE INDEX ix_viewer_role_grant_developer_id ON viewer_role_grant (developer_id);
CREATE TABLE capture_event (
    id UUID NOT NULL, 
    instance_id UUID NOT NULL, 
    seq BIGINT NOT NULL, 
    developer_id UUID, 
    credential_id UUID, 
    gateway_type gateway_type NOT NULL, 
    api_format api_format NOT NULL, 
    tool_hint VARCHAR(64), 
    session_id VARCHAR(128), 
    model VARCHAR(128) NOT NULL, 
    received_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    status event_status NOT NULL, 
    failure_cause loss_cause, 
    tool_call_count INTEGER NOT NULL, 
    line_count INTEGER NOT NULL, 
    alg INTEGER NOT NULL, 
    key_gen SMALLINT NOT NULL, 
    CONSTRAINT pk_capture_event PRIMARY KEY (id), 
    CONSTRAINT uq_capture_event_instance_id UNIQUE (instance_id, seq), 
    CONSTRAINT ck_capture_event_failure_cause_required CHECK (status = 'captured' OR failure_cause IS NOT NULL), 
    CONSTRAINT fk_capture_event_developer_id_developer FOREIGN KEY(developer_id) REFERENCES developer (id), 
    CONSTRAINT fk_capture_event_credential_id_gateway_credential FOREIGN KEY(credential_id) REFERENCES gateway_credential (id)
);
CREATE INDEX ix_capture_event_developer_received ON capture_event (developer_id, received_at);
CREATE TABLE change_head (
    id UUID NOT NULL, 
    change_id UUID NOT NULL, 
    head_sha VARCHAR(64) NOT NULL, 
    base_sha VARCHAR(64), 
    merge_base_sha VARCHAR(64), 
    event_received_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    status head_status NOT NULL, 
    coverage_status coverage_status NOT NULL, 
    coverage_reasons TEXT[] NOT NULL, 
    alg INTEGER, 
    key_gens SMALLINT[] NOT NULL, 
    counts JSONB NOT NULL, 
    excluded_paths JSONB NOT NULL, 
    check_run_id BIGINT, 
    is_final BOOLEAN NOT NULL, 
    attempts INTEGER NOT NULL, 
    completed_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_change_head PRIMARY KEY (id), 
    CONSTRAINT uq_change_head_change_id UNIQUE (change_id, head_sha), 
    CONSTRAINT fk_change_head_change_id_change FOREIGN KEY(change_id) REFERENCES change (id)
);
CREATE INDEX ix_change_head_change_id ON change_head (change_id);
CREATE TABLE line_result (
    change_head_id UUID NOT NULL, 
    file_path TEXT NOT NULL, 
    line_no INTEGER NOT NULL, 
    outcome line_outcome NOT NULL, 
    tier match_tier NOT NULL, 
    confidence match_confidence, 
    similarity FLOAT, 
    credited_developer_id UUID, 
    credited_github_id BIGINT, 
    matched_capture_event_id UUID, 
    CONSTRAINT pk_line_result PRIMARY KEY (change_head_id, file_path, line_no), 
    CONSTRAINT ck_line_result_exact_iff_unmodified CHECK ((tier = 'exact') = (outcome = 'ai_unmodified')), 
    CONSTRAINT ck_line_result_sim_iff_modified CHECK ((tier IN ('anchored','broad')) = (outcome = 'ai_modified')), 
    CONSTRAINT ck_line_result_confidence_matches_tier CHECK ((tier = 'anchored' AND confidence = 'high') OR (tier = 'broad' AND confidence = 'lower') OR (tier IN ('exact','none') AND confidence IS NULL)), 
    CONSTRAINT ck_line_result_not_observed_iff_unmapped CHECK ((outcome = 'not_observed') = (credited_developer_id IS NULL)), 
    CONSTRAINT ck_line_result_null_github_unmapped CHECK (credited_github_id IS NOT NULL OR outcome = 'not_observed'), 
    CONSTRAINT ck_line_result_ai_requires_match CHECK (outcome NOT IN ('ai_unmodified','ai_modified') OR matched_capture_event_id IS NOT NULL), 
    CONSTRAINT ck_line_result_indeterminate_no_match CHECK (outcome <> 'indeterminate' OR matched_capture_event_id IS NULL), 
    CONSTRAINT fk_line_result_change_head_id_change_head FOREIGN KEY(change_head_id) REFERENCES change_head (id), 
    CONSTRAINT fk_line_result_credited_developer_id_developer FOREIGN KEY(credited_developer_id) REFERENCES developer (id)
);
CREATE INDEX ix_line_result_credited_developer_id ON line_result (credited_developer_id);
ALTER TABLE change ADD CONSTRAINT fk_change_final_head_id_change_head
    FOREIGN KEY (final_head_id) REFERENCES change_head (id);
"""

# Day partitions in UTC. A DEFAULT partition catches rows if maintenance falls behind, so an insert never fails
# (a failed insert would be silent capture loss). Ingest calls gca_ensure_partitions(3) at start and hourly.
PARTITION_FUNCTIONS = """
CREATE TABLE captured_line_default PARTITION OF captured_line DEFAULT;
CREATE TABLE lsh_band_default PARTITION OF lsh_band DEFAULT;

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

ROLE_AND_SEEDS = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gca_reporting') THEN
        CREATE ROLE gca_reporting NOLOGIN;
    END IF;
END
$$;

INSERT INTO algorithm_version (alg, library_version, unicode_version, anchored_threshold, broad_threshold,
                               minhash_size, lsh_bands, lsh_rows, common_lines_version)
VALUES (1, '0.1.0', '15.0.0', 0.500, 0.750, 32, 8, 4, '1')
ON CONFLICT (alg) DO NOTHING;

INSERT INTO portal_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

INSERT INTO key_generation (id, status) VALUES (1, 'active') ON CONFLICT (id) DO NOTHING;

SELECT gca_ensure_partitions(3);
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(PARTITION_FUNCTIONS)
    op.execute(ROLE_AND_SEEDS)


def downgrade() -> None:
    raise NotImplementedError("the initial migration is not reversible; drop the database instead")
