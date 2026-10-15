# Data Model: Gateway Code Attribution Reference Stack

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Research**: [research.md](./research.md)

**Store**: PostgreSQL 17 (R14). **Invariant, from Constitution II:** no table, column, message, log or trace holds
source code, model output text or prompt text. Every content-derived value is a **keyed** fingerprint. Rule IDs
(FR-, SC-, R-) refer to the spec and research.

## Identity and access

### Developer
A person who uses AI tools through the gateway, or who authors commits in PRs.

| Field | Type | Rules |
|---|---|---|
| `id` | uuid | PK |
| `github_id` | bigint | unique, not null (the stable GitHub account ID; never the email) |
| `github_login` | text | display only; refreshed on sign-in and on events |
| `created_at`, `last_seen_at` | timestamptz | |

### GatewayCredential
A personal credential for calling the gateway, issued when the developer signs in with GitHub (FR-016, R5).

| Field | Type | Rules |
|---|---|---|
| `id` | uuid | PK; also embedded as `credential_id` in the gateway's key metadata |
| `developer_id` | uuid → Developer | not null |
| `gateway_type` | enum `agentgateway`, `litellm` | matches the install |
| `key_hash` | text | `sha256:<hex>` of the key; the key itself is shown once at issue and never stored |
| `gateway_ref` | text | agentgateway: config entry ID; LiteLLM: virtual key ID |
| `status` | enum `active`, `revoked` | |
| `issued_at`, `revoked_at` | timestamptz | `revoked_at` is set only when `status = revoked` |

**State**: `active → revoked`, which is terminal. Revoking removes the key from the gateway, so no capture can
happen under it afterwards. Captures already made are kept (FR-016).

### IdentityOverride
An admin-defined exception that maps a GitHub account to a developer, for example a service account or a second
account (FR-016).

| Field | Type | Rules |
|---|---|---|
| `id` | uuid | PK |
| `github_id` | bigint | unique; the account being mapped |
| `developer_id` | uuid → Developer | the target identity |
| `reason` | text | required |
| `created_by` | uuid → Developer | must hold the admin role |
| `created_at` | timestamptz | |

**Resolving a GitHub account to a developer:** an IdentityOverride wins if one exists; otherwise
`Developer.github_id`; otherwise the account is **unmapped**, and its lines are not observed (FR-015).

### Team, TeamMembership, TeamLead
Taken from the GitHub organization's teams by default, with admin overrides (FR-027).

| Entity | Fields | Rules |
|---|---|---|
| **Team** | `id`, `github_team_id` (nullable), `slug`, `name`, `source` (`github` or `manual`), `synced_at` | `github_team_id` is unique when present; manual teams have none |
| **TeamMembership** | `team_id`, `developer_id`, `source` (`github` or `override`), `override_action` (`add` or `remove`, nullable), `valid_from` (timestamptz, not null), `valid_to` (timestamptz, nullable; null = current) | effective membership at time T = rows with `valid_from ≤ T < coalesce(valid_to, ∞)`: GitHub members + override adds − override removes. Sync never deletes rows; it closes them by setting `valid_to` and opens new ones, so history is kept for "membership as of the merge date" |
| **TeamLead** | `team_id`, `developer_id`, `source` (`github_maintainer` or `override`), `override_action` | team maintainers are leads by default (FR-029a) |

The sync is driven by the GitHub App's `membership`, `team` and `organization` events, plus a periodic full
resync.

### ViewerRoleGrant
Admin overrides of viewer roles (FR-029, FR-029a).

| Field | Type | Rules |
|---|---|---|
| `developer_id` | uuid → Developer | |
| `role` | enum `admin`, `team_lead` | `team_lead` requires `team_id` |
| `team_id` | uuid → Team, nullable | |
| `action` | enum `grant`, `revoke` | overrides the GitHub-derived default |
| `created_by`, `created_at` | | `created_by` must be an admin |

**Working out a viewer's role:**
1. Start from the GitHub defaults: organization owner → admin; maintainer of team T → team lead for T.
2. Apply grants and revokes.
3. Anyone else → other.

**Per-developer visibility (FR-029 defaults, configurable in `PortalSettings`):**
- admins see every developer;
- team leads see only members of the teams they lead;
- others see none;
- `per_developer_enabled = false` hides the views from everyone.

### PortalSettings (singleton)
`per_developer_enabled` (default **true**), `visible_roles` (default `[admin, team_lead]`),
`matching_window_days` (default 14), `retention_days` (default 90), `exclusion_rules` (glob list, with the defaults
from FR-021).

## Algorithm and keys

### AlgorithmVersion
| Field | Type | Rules |
|---|---|---|
| `alg` | int | PK; increases monotonically |
| `library_version` | text | the `gcattr` semver that introduced it |
| `unicode_version` | text | pinned; the library refuses to fingerprint under any other version (R8) |
| `anchored_threshold`, `broad_threshold` | numeric | frozen after calibration (R9) |
| `minhash_size`, `lsh_bands`, `lsh_rows` | int | 32, 8 and 4 at first |
| `common_lines_version` | text | R10 |
| `released_at` | timestamptz | |

### KeyGeneration
The identity of a fingerprint key. The key material lives in a Kubernetes Secret, never in the database
(FR-035, FR-036).

| Field | Type | Rules |
|---|---|---|
| `id` | smallint | PK; carried on every fingerprint |
| `status` | enum `active`, `retired`, `expired` | exactly one is `active` |
| `created_at`, `retired_at`, `expires_at` | timestamptz | `expires_at = retired_at + retention_days` |

**State**: `active → retired → expired`.
- **Retired:** no new captures use it, but it's still used to fingerprint PR lines when matching older captures.
- **Expired:** after retention, the key is deleted from the Secret and its partitions have already been dropped.

## Capture

### CaptureInstance
One running capture process, either a `capture-extproc` replica or a LiteLLM worker (R12).

| Field | Type | Rules |
|---|---|---|
| `instance_id` | uuid | PK; random at process start |
| `gateway_type` | enum | |
| `started_at`, `last_heartbeat_at` | timestamptz | |
| `last_seq` | bigint | highest contiguous sequence number received |
| `status` | enum `active`, `stale`, `closed` | `stale` when no heartbeat for more than 15 seconds |

**State**: `active ↔ stale → closed`, where closed means a clean shutdown heartbeat. Turning stale opens a
`CaptureLoss` period with cause `heartbeat_missed`, which closes when heartbeats resume.

### CaptureEvent
One model response seen by the gateway. Metadata only.

| Field | Type | Rules |
|---|---|---|
| `id` | uuid | PK |
| `instance_id`, `seq` | uuid, bigint | unique together; gaps in `seq` mean loss |
| `developer_id` | uuid → Developer, nullable | resolved from the credential; null means an unauthenticated or unknown key (counted, never matched) |
| `credential_id` | uuid → GatewayCredential, nullable | |
| `gateway_type` | enum | |
| `api_format` | enum `openai_chat`, `openai_responses`, `anthropic_messages`, `gemini_native` | |
| `tool_hint` | text, nullable | inferred client tool (for example `claude-code`), from the user agent or session header |
| `session_id` | text, nullable | the tool's session header, when present; not used for matching |
| `model` | text | the client-facing model name |
| `received_at` | timestamptz | when the response finished |
| `status` | enum `captured`, `partial`, `failed` | |
| `failure_cause` | enum, nullable | required unless `status = captured`; same values as `CaptureLoss.cause` |
| `tool_call_count`, `line_count` | int | `line_count` counts non-trivial lines stored |
| `alg`, `key_gen` | int, smallint | |

### CapturedLine
One non-trivial normalized line of model output. Partitioned by day on `captured_at`.

| Field | Type | Rules |
|---|---|---|
| `id` | bigint | PK, within its partition |
| `capture_event_id` | uuid → CaptureEvent | |
| `developer_id` | uuid | copied from the event so scoped lookups are fast; not null (only attributable events store lines) |
| `captured_at` | timestamptz | partition key |
| `tool_call_ordinal`, `line_ordinal` | int | order within the event; used for anchoring |
| `path_suffix_fps` | bytea[] | keyed fingerprints of the last 1, 2 and 3 path components of the tool call's file path; empty if there was no path (R7) |
| `exact_fp` | bytea(16) | HMAC-SHA256 of the normalized token string, truncated (R8) |
| `minhash` | int4[32] | keyed MinHash signature (R9) |
| `alg`, `key_gen` | int, smallint | |

**Indexes**: `(developer_id, exact_fp, captured_at)`, `(capture_event_id, tool_call_ordinal, line_ordinal)`.

### LshBand
| Field | Type | Rules |
|---|---|---|
| `captured_line_id` | bigint | |
| `developer_id` | uuid | |
| `band` | smallint | 0–7 |
| `band_hash` | bytea(8) | keyed |
| `captured_at` | timestamptz | partition key, the same as CapturedLine |

**Index**: `(developer_id, band, band_hash, captured_at)`.

### CaptureLoss
| Field | Type | Rules |
|---|---|---|
| `id` | uuid | PK |
| `instance_id` | uuid, nullable | |
| `cause` | enum `seq_gap`, `heartbeat_missed`, `truncated`, `unparsable`, `unexpected_format`, `buffer_overflow`, `publish_failed`, `unsupported_combination`, `unknown_credential` | |
| `period_start`, `period_end` | timestamptz | `period_end` is null while ongoing |
| `count` | int | responses or messages affected; for `seq_gap`, the missing sequence span |
| `developer_id` | uuid, nullable | set when known (self-reported failures carry it) |
| `gateway_type`, `api_format`, `tool_hint` | | for the coverage breakdown (FR-030) |

**Rule**: every capture failure creates or extends a `CaptureLoss` row. Ingest never discards a failure without
recording it (FR-005, SC-005).

### Watermark (derived)
`watermark = min(last_heartbeat_at)` over instances with `status = active`. With no active instances, the
watermark doesn't move and PR heads stay pending until the 10-minute cap (R12).

## Attribution

### Repository
`id`, `github_id` (unique), `full_name`, `installation_id`, `active`, `added_at`.

### Change
One pull request.

| Field | Type | Rules |
|---|---|---|
| `id` | uuid | PK |
| `repository_id`, `pr_number` | | unique together |
| `opened_by_github_id` | bigint | informational only (credit is per commit author, FR-012) |
| `state` | enum `open`, `merged`, `closed` | |
| `final_head_id` | uuid → ChangeHead, nullable | set at merge (FR-018) |

### ChangeHead
The attribution of one PR head (FR-018, FR-024).

| Field | Type | Rules |
|---|---|---|
| `id` | uuid | PK |
| `change_id` | uuid → Change | |
| `head_sha`, `base_sha`, `merge_base_sha` | text | `(change_id, head_sha)` unique, which keeps reprocessing idempotent (FR-020) |
| `event_received_at` | timestamptz | the pending gate compares it with the watermark |
| `status` | enum `pending`, `processing`, `complete`, `error` | |
| `coverage_status` | enum `complete`, `incomplete`, `pending`, `not_observed` | `incomplete` if a CaptureLoss overlaps the matching window for any credited author (FR-022), or if the pending cap expired |
| `alg`, `key_gens` | int, smallint[] | the versions and key generations used |
| `counts` | jsonb | per outcome; AI modified split into `anchored` and `broad`; plus `not_observed`, `indeterminate`, `excluded` |
| `excluded_paths` | jsonb | `[{path, reason}]`, with `reason` enum `rule` (matched an exclusion glob), `binary`, `too_large` (over 5,000 added lines, or the diff couldn't be read). Shown with reasons in the check summary (FR-021) |
| `check_run_id` | bigint, nullable | GitHub check run |
| `is_final` | bool | true for `Change.final_head_id` only |
| `completed_at` | timestamptz | |

**State**: `pending → processing → complete`. `error` retries with backoff and returns to `processing`.
`pending → processing` happens when `watermark ≥ event_received_at`, or after 10 minutes, which sets
`coverage_status = incomplete`. A new head doesn't change earlier heads. At merge, `is_final = true` on the
merged head.

### LineResult
One attributable added line at a PR head. **No content.**

| Field | Type | Rules |
|---|---|---|
| `change_head_id` | uuid → ChangeHead | |
| `file_path` | text | repo-relative; display and anchoring only |
| `line_no` | int | the position at head; display only, never used for matching |
| `outcome` | enum `ai_unmodified`, `ai_modified`, `human`, `indeterminate`, `not_observed` | for an **attributable** line, exactly one of the four outcomes (FR-009). For a non-attributable line (credited to an unmapped author), the **state** `not_observed` (FR-015), which isn't an outcome. One column holds both, so each line has exactly one value |
| `tier` | enum `exact`, `anchored`, `broad`, `none` | `exact` ⇔ `ai_unmodified`; `anchored` or `broad` ⇔ `ai_modified`; otherwise `none` |
| `confidence` | enum `high`, `lower`, null | `high` ⇔ anchored; `lower` ⇔ broad; null otherwise |
| `similarity` | real, nullable | the estimated Jaccard for anchored and broad matches |
| `credited_developer_id` | uuid, nullable | null ⇔ the credited GitHub account is unmapped |
| `credited_github_id` | bigint, nullable | the GitHub account of the author of the PR commit that added the line; **null** when GitHub links that commit's author to no account (for example an email not on any account), which always means `not_observed` |
| `matched_capture_event_id` | uuid, nullable | set for AI outcomes (an AI outcome needs a capture match; FR-011) |

**Validation**:
- An AI outcome needs `matched_capture_event_id` and a `credited_developer_id` equal to that capture event's
  `developer_id` (FR-012).
- `not_observed` ⇔ `credited_developer_id` is null. `credited_github_id` null ⇒ `credited_developer_id` null.
- Outcome counts and percentages never include `not_observed` lines (FR-009, FR-014); they're counted
  separately.
- `indeterminate` lines never have a match.
- Percentages are computed over `ai_unmodified + ai_modified + human` only (FR-014).

## Reporting views (read by Grafana; no per-developer columns, R15)

| View | Grain | Notes |
|---|---|---|
| `v_change_summary` | change head (final, or latest) | counts by outcome, with broad separate; coverage status; `alg` |
| `v_repository_daily` | repository × day | sums of final heads merged that day |
| `v_team_daily` | team × day | sums of line credits to team members; membership as of the merge date |
| `v_coverage_daily` | gateway × API format × tool × cause × day | CaptureLoss totals, unsupported combinations, count of unmapped authors |

Each view exposes `*_with_broad` and `*_without_broad` columns so the toggle (FR-028) is a pure selection.
**Per-developer aggregates** are served only by the portal's role-checked API ([contracts/portal-http.md](./contracts/portal-http.md)).

## Retention

- `captured_line` and `lsh_band` partitions older than `retention_days` (default 90) are dropped every day.
- `capture_event` metadata is kept for the same period.
- `change_head` and `line_result` are kept indefinitely by default. They hold no content and are the reporting
  record. Adopters can configure this.
- `capture_loss` is kept for 400 days, for trend reporting.

## Message: capture → ingest

Fingerprints and metadata only. Schema: [contracts/capture-event.schema.json](./contracts/capture-event.schema.json).
