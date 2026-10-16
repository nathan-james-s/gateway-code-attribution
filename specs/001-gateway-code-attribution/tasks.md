---

description: "Task list for the Gateway Code Attribution Reference Stack"
---

# Tasks: Gateway Code Attribution Reference Stack

**Input**: Design documents from `specs/001-gateway-code-attribution/`: [plan.md](./plan.md),
[spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md),
[contracts/](./contracts/), [quickstart.md](./quickstart.md). Governing: `.specify/memory/constitution.md`
v1.0.1.

**Tests**: The spec doesn't request test-first development. These test suites are still **required deliverables**
under the constitution (Principles III–V; Development Workflow & Quality Gates) and the spec (FR-006, FR-042 to
FR-045, SC-001 to SC-010), so they're included as tasks:
- determinism and golden-file tests;
- the cross-gateway conformance suite;
- the privacy audit;
- end to end;
- the scenario-set evaluation;
- performance.

**Organization**: Tasks are grouped by user story (US1–US6 in spec priority order), so each story can be built
and checked on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on unfinished tasks)
- **[Story]**: the user story the task belongs to (US1–US6)
- Paths are repository-relative, following the plan's structure. `lib/` is the `gcattr` library; services live in
  `services/<name>/src/gca_<name>/`.

## Global rules for every task

These come from the constitution and research, and apply without being repeated in each task.

- **Constitution II:** no code, model output text or prompt text may be written to storage, logs, traces,
  metrics, queues or crash reports. Content exists only in memory while fingerprinting.
- **Constitution III:** every component imports `gcattr` for normalization, fingerprinting and matching. No
  reimplementation.
- **Fail open (FR-005a):** capture code must never block, alter or delay a gateway response. Every capture
  failure is counted with a cause.
- **Pinned versions:** agentgateway `1.6.0`; LiteLLM `v1.105.1`; nats-server `2.15.1`; Grafana `13.2.4`;
  PostgreSQL `17`; Python `3.12`. Images are pinned by digest (T007).
- **Copied constraints:** where a task quotes a data-model constraint, implement it verbatim.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Set up the workspace, tooling and continuous integration skeleton.

- [X] T001 Create the repository layout from plan.md "Source Code": `lib/src/gcattr/`, `lib/tests/`, `services/{core,capture-extproc,capture-litellm,ingest,prcheck,portal,demo}/src/`, `charts/gateway-code-attribution/`, `dashboards/`, `eval/{scenarios,corpus,harness}/`, `tests/{conformance,privacy,e2e,perf,integration}/`, `docs/`, and `scripts/`. Add a `.gitkeep` to each empty directory.
- [X] T002 Create the root `pyproject.toml` as a uv workspace. Members: `lib`, `services/*`, `eval/harness`. Pin `requires-python = "==3.12.*"` and add `.python-version` with `3.12`. Generate `uv.lock` with `uv lock`.
- [X] T003 [P] Create `lib/pyproject.toml` for package `gcattr`:
  - runtime dependencies: **standard library only**;
  - dev group: `pytest`, `hypothesis`;
  - console script: `gca = "gcattr.cli:main"`;
  - an entry-point group `gca.commands` so other packages can add subcommands;
  - Apache-2.0 license metadata.
- [X] T004 [P] Create `services/<name>/pyproject.toml` for each service package:
  - `services/core` (`gca_core`): sqlalchemy>=2, alembic, psycopg[binary]>=3, nats-py, pydantic-settings, githubkit, jsonschema.
  - `services/capture-extproc` (`gca_capture_extproc`): grpcio, grpcio-tools, protobuf.
  - `services/capture-litellm` (`gca_capture_litellm`): no extra dependencies. LiteLLM comes from the base image.
  - `services/ingest` (`gca_ingest`).
  - `services/prcheck` (`gca_prcheck`): fastapi, uvicorn.
  - `services/portal` (`gca_portal`): fastapi, uvicorn, jinja2, itsdangerous, kubernetes.
  - `services/demo` (`gca_demo`): httpx.

  Every service depends on `gcattr` and `gca_core` (except `capture-litellm`, which needs only `gcattr` and `gca_core`'s messaging).
- [X] T005 [P] Configure `ruff` (lint and format) and `mypy` (strict for `lib/`) in the root `pyproject.toml`, and add `.pre-commit-config.yaml` running ruff, mypy and `helm lint`.
- [X] T006 [P] Create a root `Makefile` with targets `lint`, `test`, `test-lib`, `demo` (`GATEWAY=agentgateway|litellm`), `demo-upgrade` (`VALUES=…`), `demo-down`, `eval`, `perf` and `images`. Bodies call scripts in `scripts/`, which are filled in by later tasks.
- [X] T007 [P] Create `versions.yaml` listing every pinned external artifact (agentgateway 1.6.0 binary and image, LiteLLM v1.105.1 image, nats-server 2.15.1, the NATS Helm chart, Grafana 13.2.4, the grafana-community chart, `postgres:17`, `kindest/node`). Create `scripts/pin-digests.sh`, which resolves each tag to a `sha256` digest with `crane digest` or `docker buildx imagetools inspect` and writes them back into `versions.yaml` and `charts/gateway-code-attribution/values.yaml`.
- [X] T008 [P] Create `.github/workflows/ci.yml` with these jobs:
  - lint;
  - `test-lib`, on a matrix of `ubuntu-latest` and `macos-latest` with Python 3.12;
  - `test-services`, on `ubuntu-latest` with Docker for testcontainers;
  - `helm-lint`, running `helm lint` and `kubeconform` on the rendered chart.
- [X] T009 [P] Add `NOTICE` (Apache-2.0), a `README.md` skeleton (purpose, link to `docs/install.md`, license), `CONTRIBUTING.md` (Spec Kit workflow and constitution quality gates) and `SECURITY.md`.
- [X] T010 [P] Extend the root `.gitignore` with `.venv/`, `dist/`, `*.egg-info/`, `.pytest_cache/`, `.mypy_cache/`, `report.json` and `kind-*.kubeconfig`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The `gcattr` library core, the shared service core, the database schema, the messaging runtime, the
chart skeleton, and the two gateway validation spikes. **No user story work starts until this phase is done.**

### `gcattr` library core (R7–R11; [contracts/library-api.md](./contracts/library-api.md))

- [X] T011 Create `lib/src/gcattr/algorithm.py`:
  - `ALG = 1` and `SUPPORTED_ALGS = (1,)`;
  - a frozen dataclass `AlgParams` with fields `unicode_version`, `anchored_threshold`, `broad_threshold`, `minhash_size`, `lsh_bands`, `lsh_rows`, `common_lines_version`;
  - `PARAMS = {1: AlgParams(unicode_version="15.0.0", anchored_threshold=0.50, broad_threshold=0.75, minhash_size=32, lsh_bands=8, lsh_rows=4, common_lines_version="1")}`, where `15.0.0` is the `unicodedata.unidata_version` of CPython 3.12;
  - a comment that the thresholds are provisional until T109 calibrates them and T113 freezes them;
  - exceptions `UnsupportedAlg` and `UnicodeVersionMismatch`;
  - re-export `ALG` and `SUPPORTED_ALGS` from `lib/src/gcattr/__init__.py`.
- [X] T012 [P] Implement `lib/src/gcattr/normalize.py`. `normalize_line(text: str, alg: int) -> str`:
  - raise `UnicodeVersionMismatch` if `unicodedata.unidata_version != PARAMS[alg].unicode_version`;
  - strip a leading U+FEFF;
  - apply NFC;
  - map `\r\n` and `\r` to `\n`.

  Also `split_lines(text) -> list[str]` (R8).
- [X] T013 [P] Implement `lib/src/gcattr/lexer.py`. `tokenize(line: str) -> list[Token]`, where each token is one of:
  - `ident` (`[A-Za-z_À-￿][\w]*`);
  - `number` (digits, with optional `.`, exponent and `0x`/`0o`/`0b` prefixes);
  - `string` (a literal delimited by `'`, `"` or `` ` ``, with backslash escapes, keeping the quote character; an unterminated string runs to end of line);
  - `punct` (any other single non-space character).

  Whitespace is dropped. Language-agnostic (R8).
- [X] T014 [P] Implement `lib/src/gcattr/trivial.py` and `lib/src/gcattr/data/common_lines_v1.txt`. `is_trivial(tokens) -> bool` is true if any of these hold (R10):
  - fewer than 3 tokens;
  - no `ident`, `number` or `string` token;
  - the space-joined token string is in the common-lines list.

  Seed the list with at least: `} else {`, `else {`, `return ;`, `pass`, `break ;`, `continue ;`, `import os`, `import sys`, `} ;`, `) ;`, `end`, `fi`, `done`, `try :`, `except :`, `else :`, `finally :`, `return None`, `return true ;`, `return false ;`, `if __name__ == "__main__" :`.
- [X] T015 Implement `lib/src/gcattr/fingerprint.py`:
  - `FingerprintKey(key_gen: int, secret: bytes)`, where secret must be at least 32 bytes;
  - `exact_fp(tokens, key, alg) = HMAC-SHA256(key.secret, f"v{alg}\x1f".encode() + " ".join(t.text for t in tokens).encode("utf-8"))[:16]`;
  - `path_suffix_fps(path, key, alg)`: normalize separators to `/`, drop empty components, then HMAC each of the last 1, 2 and 3 components joined by `/`, with domain prefix `b"path\x1f"`, truncated to 16 bytes, for a maximum of 3 values (R7, R8).
- [X] T016 Implement `lib/src/gcattr/similarity.py`:
  - **shingles**: token 3-grams, or the whole token list for 3–4 tokens. Each shingle is keyed as `HMAC(secret, b"sh\x1f" + joined)` and becomes a 64-bit int.
  - **MinHash**: 32 seeds `seed_i = HMAC(secret, b"mh\x1f" + i.to_bytes(2))[:8]`. `minhash[i] = min((h ^ seed_i) * 0x9E3779B97F4A7C15 mod 2^64 >> 32 for h in shingles)`, giving uint32.
  - `lsh_bands(minhash)`: 8 bands of 4 rows; `band_hash = HMAC(secret, b"lsh\x1f" + band_index + packed rows)[:8]`.
  - `jaccard(a, b)`: the fraction of equal positions (R9).
- [X] T017 [P] Port `.specify/assessments/gateway-code-attribution/probes/streamed-tool-calls/reassemble.py` into `lib/src/gcattr/streams/sse.py` as an incremental SSE parser (bytes in; handles split UTF-8 and split lines; ignores `[DONE]`). Add one module per format:
  - `lib/src/gcattr/streams/openai_chat.py`;
  - `openai_responses.py`, covering `function_call_arguments` and `custom_tool_call_input`, preferring `.done` payloads and checking them against the deltas;
  - `anthropic.py`, covering `input_json_delta` and `content_block_stop`;
  - `gemini.py`, covering whole `functionCall` parts.

  Each yields `CapturedToolOutput` or `CaptureFailure(cause ∈ {"truncated","unparsable","unexpected_format"})`. Expose `parse_stream(api_format, chunks)` in `lib/src/gcattr/streams/__init__.py`.
- [X] T018 [P] Implement `lib/src/gcattr/adapters/litellm.py`. `from_litellm(response_obj, call_type)` maps LiteLLM's reassembled responses to `CapturedToolOutput`:
  - `acompletion` and `anthropic_messages`: `choices[].message.tool_calls[].function.{name,arguments}`;
  - `aresponses`: `output[]` items of type `function_call` (`arguments`) and `custom_tool_call` (`input`).

  `finish_reason == "length"` or invalid JSON → `complete=False` plus `CaptureFailure("truncated")`. Accepts dicts or pydantic objects (use `model_dump()`).
- [X] T019 Implement `lib/src/gcattr/extract.py` and `lib/src/gcattr/tool_fields.py` (R7). `tool_fields.py` is a versioned table of code-bearing argument fields, with keys `content`, `new_string`, `new_str`, `edits[].new_string`, `patch`, `code` and `text`, and path keys `file_path`, `path`, `filename`. `extract(output, key, alg)`:
  - takes code from the known fields;
  - for freeform `*** Begin Patch` input, takes only `+` lines and the `*** Update File:`/`*** Add File:` path;
  - takes other string values and fenced code blocks in text as pathless lines;
  - for truncated JSON, keeps complete lines before the cut-off and drops the incomplete remainder;
  - normalizes, tokenizes and drops trivial lines;
  - returns `list[LineFingerprint]` with `exact_fp`, `minhash`, `lsh_bands`, `path_suffix_fps`, `tool_call_ordinal` and `line_ordinal`.
- [X] T020 Implement `lib/src/gcattr/match.py`. `attribute(lines, candidates_by_author, keys, alg)` follows R11 exactly:
  1. lines whose `credited_github_id` is `None` or isn't in `candidates_by_author` → the state `not_observed` (not an outcome; spec FR-009, FR-015);
  2. trivial lines → `indeterminate`;
  3. exact tier: multiset match on `exact_fp`, recomputed for each candidate's `(alg, key_gen)` group; each candidate occurrence is used at most once;
  4. anchored tier: candidates are the lines of capture events with **at least one exact match in the same file**. If that capture event's tool call has `path_suffix_fps`, they must intersect the file's suffix fingerprints. A path match **without** an exact match is not an anchor (spec FR-010, R11). `jaccard ≥ anchored_threshold` → `ai_modified` / `anchored` / `high`;
  5. broad tier: any of the author's candidates sharing at least one LSH band, including path-only matches; `jaccard ≥ broad_threshold` → `ai_modified` / `broad` / `lower`;
  6. everything else → `human`.

  Pure and deterministic, with ties broken by `(capture_event_id, tool_call_ordinal, line_ordinal)`.
- [X] T021 [P] Implement `lib/src/gcattr/classify.py`. `summarize(outcomes) -> dict` returns:
  - counts per outcome, with `ai_modified` split into `anchored` and `broad`;
  - `percentages_with_broad` and `percentages_without_broad`, computed over `ai_unmodified + ai_modified + human` only. Indeterminate lines and `not_observed` lines are excluded (FR-014); `not_observed` is reported as its own count, never as an outcome (FR-009). Without broad, broad lines count as `human`.
  - If the denominator is 0 (nothing attributable), percentages are `null`, not 0% (spec Edge Cases, "Nothing to attribute").
- [X] T022 Create the unit tests `lib/tests/test_normalize.py`, `test_lexer.py`, `test_trivial.py`, `test_fingerprint.py`, `test_similarity.py`, `test_extract.py`, `test_match.py` and `test_classify.py`. Cover every rule in T012–T021, including:
  - the multiset rule (FR-013);
  - the rule that an AI outcome needs a candidate match (FR-011);
  - the anchored rule: one exact match in the file anchors; a path match with no exact match falls to broad; a multi-file tool call doesn't anchor across files;
  - `credited_github_id=None` → `not_observed`;
  - `summarize` with nothing attributable returns `null` percentages.
- [X] T023 Create `lib/tests/test_streams.py`, porting the probe fixtures (`probes/streamed-tool-calls/fixtures.py`) into `lib/tests/fixtures/streams.py`. Parse every fixture with byte chunk sizes 1 through 13, and assert:
  - exact argument equality;
  - a `truncated` failure for the truncated Anthropic stream;
  - that schema-deviant input yields `unexpected_format` and never an exception.
- [X] T024 Create `lib/tests/test_determinism.py` with Hypothesis property tests: `extract` and `attribute` are pure (the same inputs give equal outputs across repeated calls and shuffled candidate order), and fingerprints don't depend on chunk boundaries (Constitution III).

### Shared service core

- [X] T025 Implement `services/core/src/gca_core/config.py` with pydantic-settings. Settings: database URL, NATS URL, gateway type, matching window (default 14 days), retention (default 90 days), and the keys directory. Implement `services/core/src/gca_core/keys.py`, which loads fingerprint keys from a mounted Secret directory: files named `<key_gen>` hold 32 or more raw bytes, base64-encoded, and a file `active` holds the active `key_gen`. It returns `dict[int, FingerprintKey]` and never logs key material.
- [X] T026 [P] Create the identity and access models in `services/core/src/gca_core/db/models_identity.py`, copying these constraints from data-model.md:
  - `Developer`: "`github_id` bigint unique, not null (the stable GitHub account ID; never the email)".
  - `GatewayCredential`: "`gateway_type` enum `agentgateway`, `litellm`"; "`key_hash` `sha256:<hex>` of the key; the key itself is shown once at issue and never stored"; "`status` enum `active`, `revoked`"; "`revoked_at` is set only when `status = revoked`".
  - `IdentityOverride`: "`github_id` unique; the account being mapped"; "`reason` required"; "`created_by` must hold the admin role".
  - `Team`: "`github_team_id` is unique when present; manual teams have none"; `source` enum `github`/`manual`.
  - `TeamMembership`, with `source` and `override_action` enums, plus "`valid_from` (timestamptz, not null), `valid_to` (timestamptz, nullable; null = current)". Sync never deletes rows; it closes them by setting `valid_to` and opens new ones.
  - `TeamLead`, with `source` and `override_action` enums.
  - `ViewerRoleGrant`: "`role` enum `admin`, `team_lead`"; "`team_lead` requires `team_id`"; `action` enum `grant`/`revoke`.
  - `PortalSettings` (singleton) with defaults `per_developer_enabled=true`, `visible_roles=[admin, team_lead]`, `matching_window_days=14`, `retention_days=90`.
- [X] T027 [P] Create the algorithm and key models in `services/core/src/gca_core/db/models_algorithm.py`:
  - `AlgorithmVersion`, with every field in data-model.md;
  - `KeyGeneration`: "`id` smallint PK; carried on every fingerprint"; "`status` enum `active`, `retired`, `expired`"; "exactly one is `active`" (a partial unique index on `status='active'`); "`expires_at = retired_at + retention_days`".
- [X] T028 [P] Create the capture models in `services/core/src/gca_core/db/models_capture.py`:
  - `CaptureInstance`: "`status` enum `active`, `stale`, `closed`"; "`stale` when no heartbeat for more than 15 seconds".
  - `CaptureEvent`: "`instance_id`, `seq` unique together; gaps in `seq` mean loss"; `api_format` enum `openai_chat`, `openai_responses`, `anthropic_messages`, `gemini_native`; `status` enum `captured`, `partial`, `failed`; "`failure_cause` required unless `status = captured`".
  - `CapturedLine`: "`exact_fp` bytea(16)", "`minhash` int4[32]", "`path_suffix_fps` bytea[]", "`developer_id` … not null"; partitioned by day on `captured_at`; indexes `(developer_id, exact_fp, captured_at)` and `(capture_event_id, tool_call_ordinal, line_ordinal)`.
  - `LshBand`: "`band` smallint 0–7", "`band_hash` bytea(8)"; index `(developer_id, band, band_hash, captured_at)`; partitioned by day.
  - `CaptureLoss`: "`cause` enum `seq_gap`, `heartbeat_missed`, `truncated`, `unparsable`, `unexpected_format`, `buffer_overflow`, `publish_failed`, `unsupported_combination`, `unknown_credential`"; "`period_end` is null while ongoing".
- [X] T029 [P] Create the attribution models in `services/core/src/gca_core/db/models_attribution.py`:
  - `Repository`.
  - `Change`: "`repository_id`, `pr_number` unique together"; `state` enum `open`, `merged`, `closed`.
  - `ChangeHead`: "`(change_id, head_sha)` unique"; "`status` enum `pending`, `processing`, `complete`, `error`"; "`coverage_status` enum `complete`, `incomplete`, `pending`, `not_observed`"; `counts` jsonb; `excluded_paths` jsonb, holding "`[{path, reason}]` with `reason` enum `rule`, `binary`, `too_large`"; `is_final` bool.
  - `LineResult`, with "`outcome` enum `ai_unmodified`, `ai_modified`, `human`, `indeterminate`, `not_observed`", "`tier` enum `exact`, `anchored`, `broad`, `none`", "`confidence` enum `high`, `lower`, null", and CHECK constraints for:
    - `exact ⇔ ai_unmodified`;
    - `anchored|broad ⇔ ai_modified`;
    - `high ⇔ anchored`;
    - `lower ⇔ broad`;
    - `not_observed ⇔ credited_developer_id IS NULL`;
    - `credited_github_id` is "bigint, nullable", and `credited_github_id IS NULL ⇒ outcome = 'not_observed'`;
    - AI outcomes need `matched_capture_event_id` to be non-null.

  No content columns.
- [X] T030 Create Alembic in `services/core/alembic/` and migration `0001_initial.py`:
  - every table from T026–T029;
  - native declarative partitioning of `captured_line` and `lsh_band` by day;
  - a SQL function `gca_ensure_partitions(days_ahead int)` and `gca_drop_partitions_older_than(days int)`;
  - a read-only role `gca_reporting` with access to views only (created later);
  - a seed of `AlgorithmVersion` row `alg=1` from `gcattr.algorithm.PARAMS`.
- [X] T031 [P] Copy `specs/001-gateway-code-attribution/contracts/capture-event.schema.json` to `services/core/src/gca_core/schemas/capture-event.schema.json`. Implement `services/core/src/gca_core/messages.py`, which builds and validates `event`, `heartbeat` and `failure` messages with jsonschema. It base64-encodes binary fingerprints and **rejects any field not in the schema** (Constitution II).
- [X] T032 Implement `services/core/src/gca_core/nats.py`:
  - a JetStream connection;
  - `ensure_stream()`, which creates stream `GCA_CAPTURE` with subjects `gca.capture.>`, file storage and work-queue retention;
  - a `BufferedPublisher` with a bounded in-memory queue of 10,000 messages and a background flush with retry. On overflow it drops the oldest event message and increments a `buffer_overflow` counter, which it reports as a `failure` message once the connection returns (R13).
- [X] T033 Implement `services/core/src/gca_core/capture_runtime.py`, shared by both capture adapters:
  - `CaptureRuntime(gateway_type)` with a random `instance_id` and a monotonic `seq`;
  - `emit_event(...)` and `emit_failure(cause, count, …)`;
  - a heartbeat task every 5 seconds, carrying `responses_seen`, `buffer_depth` and `shutting_down` on SIGTERM.

  Every publish goes through `BufferedPublisher`. The runtime must never raise into its caller (FR-005a).
- [X] T034 [P] Implement `services/core/src/gca_core/github.py`, a githubkit wrapper for:
  - App JWT and installation tokens;
  - user OAuth (authorize URL, code exchange, `GET /user`, org membership and role, team membership);
  - compare (`GET /repos/{o}/{r}/compare/{base}...{head}`, returning per-file patches in memory);
  - the GraphQL `blame` query for a path at a commit;
  - listing PR commits with author `id`s.
- [X] T035 [P] Implement `services/core/src/gca_core/identity.py`. `resolve_developer(github_id) -> Developer | None`: an IdentityOverride wins if one exists; otherwise `Developer.github_id`; otherwise None (unmapped), as data-model.md defines.

### Packaging skeleton

- [X] T036 Create `charts/gateway-code-attribution/Chart.yaml` (Apache-2.0; dependencies: the `nats` chart from `https://nats-io.github.io/k8s/helm/charts/` and the `grafana` chart from `https://grafana-community.github.io/helm-charts`, both with pinned versions from `versions.yaml`).
  - Create `values.yaml` exactly as in [contracts/helm-values.md](./contracts/helm-values.md), and `values.schema.json` enforcing its validation rules.
  - Add templates `templates/postgres-statefulset.yaml` (official `postgres:17` image by digest, one replica, PVC sized by `postgres.storage`, used only when `postgres.internal`), `templates/secrets.yaml` (fingerprint key Secret with `key_gen` 1 and an `active` file, plus Postgres passwords, generated with `lookup` + `randAscii` so they persist across upgrades unless `existingSecret` is given) and `templates/migrations-job.yaml` (a Helm pre-install/pre-upgrade hook running `alembic upgrade head`).
  - No Bitnami charts or images.
- [X] T037 [P] Create a multi-stage `Dockerfile` (uv-based, non-root, Python 3.12 slim pinned by digest) for each of `services/capture-extproc`, `services/ingest`, `services/prcheck`, `services/portal` and `services/demo`. Create `services/capture-litellm/Dockerfile` based on `ghcr.io/berriai/litellm:v1.105.1` pinned by digest, which installs `gcattr`, `gca_core` and `gca_capture_litellm` into the image. Create `scripts/build-images.sh` for `make images`, which builds and loads the images into kind when `KIND=1`.
- [X] T038 Validate research R2 and record the outcome in `docs/validation/R2-extproc.md`. Run agentgateway 1.6.0 standalone (binary from `versions.yaml`) with `llm.policies.extProc` set to `failureMode: failOpen` and `processingOptions.responseBodyMode: fullDuplexStreamed`, pointed at a minimal Python pass-through processor in `tests/spikes/extproc_echo.py` and the probe's mock upstream. Confirm:
  - (a) streamed responses reach the client byte-identical;
  - (b) the processor gets every body chunk;
  - (c) killing the processor mid-stream doesn't break the client stream;
  - (d) the exact CEL names to use in `metadataContext` for the API-key metadata, the request model and the input format;
  - (e) a **slow** processor: with a 2-second delay injected on the echo path, does agentgateway apply a processor timeout and then fail open, or does the client stream stall? Record the timeout setting to use, and confirm that delays in background work (not the echo) never reach the client.

  If (a)–(c) fail, record the fallback chosen from research R2 before starting T040.
- [X] T039 Validate research R5 and record the outcome in `docs/validation/R5-key-reload.md`. Check that agentgateway 1.6.0 standalone reloads `llm.policies.apiKey.keys` (using `keyHash` and `metadata`) from a changed config file without dropping in-flight streams, and how long the change takes to apply. If it doesn't, record the fallback from research R5 (controller mode or `extAuthz`) before starting T048.

**Checkpoint**: the library passes T022–T024. The schema migrates on a fresh Postgres. The chart renders with
`helm template`. R2 and R5 are validated or have a recorded fallback.

---

## Phase 3: User Story 1 - Stand up the stack and see attribution on a sample change (Priority: P1) 🎯 MVP

**Goal**: Following one documented install with either gateway, an evaluator runs keyless demo traffic and sees
a demonstration PR attributed in all four outcomes, plus per-change and per-repository totals.

**Independent Test**: quickstart.md section 1, on a clean machine with `GATEWAY=agentgateway` and then
`GATEWAY=litellm`. The first attributed PR appears within 30 minutes (SC-001), and both gateways give identical
per-line outcomes.

### Capture: agentgateway

- [X] T040 [US1] Provide Python stubs for Envoy `ext_proc` v3. **Per T038, use the `xds-protos` package** (gRPC's published Envoy/xDS protos, which include `envoy.service.ext_proc.v3` with `StreamedBodyResponse`) as a dependency of `services/capture-extproc/pyproject.toml`, instead of vendoring protos into `services/capture-extproc/protos/`. Pin it to the version `grpcio` pins, and add an import smoke test in `services/capture-extproc/tests/test_stubs.py`.
- [X] T041 [US1] Implement `services/capture-extproc/src/gca_capture_extproc/server.py`, a `grpc.aio` server on port 9000 implementing `ExternalProcessor.Process`:
  - respond immediately to `request_headers` and `response_headers` with `CONTINUE`;
  - echo every `response_body` chunk back unchanged straight away (streamed body mutation equal to the input);
  - copy each chunk into a per-stream buffer capped at 8 MiB (overflow → `CaptureFailure("unexpected_format")`) and feed it to `gcattr.parse_stream` in a background task;
  - at end of stream, call `gcattr.extract` with the active key and emit through `CaptureRuntime`;
  - **the echo path never awaits background work.** Chunks are handed to the parser through a bounded per-stream queue. If the queue is full, stop copying for that stream and emit `failure(buffer_overflow)`; never delay the echo (U6).
  - **apply the T038 findings** (`docs/validation/R2-extproc.md`). agentgateway has no processor timeout: a slow processor stalls the developer's stream, and a crashed one truncates in-flight responses. So:
    - parse and fingerprint in a separate worker **process** (`ProcessPoolExecutor`), so hashing never holds the GIL against the echo loop;
    - add a 250 ms self-deadline. If a chunk waits longer, stop copying for that stream and keep echoing;
    - on SIGTERM, stop accepting new streams and finish in-flight ones (gRPC graceful stop, 300 s grace);
    - read the model from the response stream (`llm.requestModel` isn't available at this stage), and use `xds-protos` for the ext_proc stubs instead of vendored protos.

  Content is never logged. Read identity (`credential_id`, `github_id`), `api_format` and `model` from `metadata_context.filter_metadata["gca"]`, using the CEL names found in T038. With no identity, emit `failure(unknown_credential)`.
- [X] T042 [US1] Implement `services/capture-extproc/src/gca_capture_extproc/api_format.py`. It determines `api_format` from the metadata, falling back to the request path (`/v1/chat/completions` → `openai_chat`, `/v1/responses` → `openai_responses`, `/v1/messages` → `anthropic_messages`, `:streamGenerateContent` → `gemini_native`). It derives `tool_hint` from `user-agent` and the session headers `x-claude-code-session-id` and `x-opencode-session-id`.
- [X] T043 [US1] Create `charts/gateway-code-attribution/templates/agentgateway.yaml`: a Deployment, Service and ConfigMap for agentgateway 1.6.0 standalone, used when `gateway.type == agentgateway`. The ConfigMap renders `llm.policies.apiKey` (strict, the CEL `location.expression` from [contracts/gateway-capture.md](./contracts/gateway-capture.md), and `keys` loaded from a portal-managed ConfigMap per T039) and `llm.policies.extProc` (`failOpen`, `fullDuplexStreamed`, `metadataContext`). Also create `templates/capture-extproc.yaml`, a Deployment and Service on port 9000 with the fingerprint key Secret mounted read-only. Per `docs/validation/R2-extproc.md`, it has at least 2 replicas, `terminationGracePeriodSeconds: 330`, a `preStop` hook, and memory limits sized for 8 MiB per-stream buffers. Per `docs/validation/R5-key-reload.md`, mount the portal-managed keys ConfigMap as a directory, never with `subPath`.

### Capture: LiteLLM

- [X] T044 [US1] Implement `services/capture-litellm/src/gca_capture_litellm/handler.py`, a `CustomLogger` subclass with a module-level `handler` instance:
  - `async_log_success_event` calls `gcattr.from_litellm(response_obj, kwargs["call_type"])`, then `gcattr.extract`, then `CaptureRuntime.emit_event`. Identity comes from `kwargs["litellm_params"]["metadata"]["user_api_key_user_id"]`, the GitHub ID set on the virtual key.
  - `async_log_failure_event` calls `emit_failure`.
  - All exceptions are caught and counted as `publish_failed` or `unparsable`, never raised (FR-005a).
- [X] T045 [US1] Create `charts/gateway-code-attribution/templates/litellm.yaml`: a Deployment, Service and ConfigMap for the T037 LiteLLM image, used when `gateway.type == litellm`. The ConfigMap matches [contracts/gateway-capture.md](./contracts/gateway-capture.md) (`callbacks: ["gca_capture_litellm.handler.handler"]`, `turn_off_message_logging: true`, `store_prompts_in_spend_logs: false`, `database_url` pointing at the stack's Postgres in schema `litellm`, `master_key` from a generated Secret). It mounts the fingerprint key Secret and NATS settings.

### Ingest

- [X] T046 [US1] Implement `services/ingest/src/gca_ingest/consumer.py`, a JetStream pull consumer on `GCA_CAPTURE` that validates each message with `gca_core.messages`:
  - `event` → upsert `CaptureEvent` (idempotent on `(instance_id, seq)`), resolve `developer_id` from `credential_id`, and bulk-insert `CapturedLine` and `LshBand` rows into the day partitions;
  - `heartbeat` → upsert `CaptureInstance.last_heartbeat_at` and `last_seq`, set `status=active`, or `status=closed` when `shutting_down=true`.

  Also run a sweeper every 5 seconds that marks instances with `last_heartbeat_at` older than 15 seconds as `stale`. This status handling belongs in US1, so a pod restart can't freeze the watermark. Recording the loss periods for these transitions is added in T088.

  Acknowledge after commit. Call `gca_ensure_partitions(3)` at startup and every hour.
- [X] T047 [US1] Implement `services/ingest/src/gca_ingest/watermark.py`. `current_watermark()` returns `min(last_heartbeat_at)` over `CaptureInstance` rows with `status='active'` (data-model.md "Watermark"). Stale and closed instances never hold the watermark back; with no active instance it returns `None`, and the head stays pending until the US2 cap. The watermark is exposed to prcheck through the shared database. Add `charts/gateway-code-attribution/templates/ingest.yaml`.

### Portal: sign-in, credentials, per-line view

- [X] T048 [US1] Implement `services/portal/src/gca_portal/app.py` and `auth.py`: FastAPI with `/auth/login`, `/auth/callback` and `/auth/logout`, using the GitHub App's user authorization (`gca_core.github`). Sessions are HttpOnly, SameSite=Lax cookies (Secure whenever the portal URL is https) holding an opaque 256-bit random id; session state, including the user's GitHub token, stays server-side in the portal process. Upsert `Developer` on sign-in. Add `/healthz` and `/readyz` ([contracts/portal-http.md](./contracts/portal-http.md)).
- [X] T049 [US1] Implement credential issue and revoke in `services/portal/src/gca_portal/app.py` (gateway backends in `backends.py`) with `POST /me/credential` and `DELETE /me/credential` (HTML forms use `POST /me/credential/revoke`). Issuing generates `sk-gca-` + 32 random bytes (urlsafe base64; LiteLLM requires the `sk-` prefix), shown once; stores only `sha256:<hex>`; and revokes any previous active credential.
  - **agentgateway:** patch the portal-managed keys ConfigMap (`keyHash`, `metadata: {github_id, credential_id}`) through the Kubernetes API, using the mechanism validated in T039.
  - **LiteLLM:** call `POST /key/generate` with `user_id=<github_id>` and the master key; store the returned key ID in `gateway_ref`. Revoking calls `POST /key/delete`.

  Add `charts/gateway-code-attribution/templates/portal.yaml`, with a ServiceAccount and a Role limited to `get`/`patch` on that one ConfigMap.
- [X] T050 [US1] Implement `GET /me` and `GET /me/setup` in `services/portal/src/gca_portal/app.py`, with templates in `services/portal/src/gca_portal/templates/me.html` and `setup.html`. The setup page renders the R6 per-tool routing table (Claude Code, Codex CLI, Gemini CLI, OpenCode) with the gateway URL filled in.
- [X] T051 [US1] Implement `GET /changes/{owner}/{repo}/{pr}` in `services/portal/src/gca_portal/app.py` and `templates/changes.html`. Check that the signed-in user can view the repository, using their token. Show the latest and final heads' `LineResult` rows (path, line, outcome, tier, confidence, credited login), each linking to `https://github.com/{owner}/{repo}/blob/{head_sha}/{path}#L{line}`. **No line content is fetched or rendered.**

### PR check

- [X] T052 [US1] Implement `services/prcheck/src/gca_prcheck/polling.py`. Every 30 seconds, for each installation repository, list open PRs and compare their head SHAs with known `ChangeHead` rows. For each new head, create `Change` and `ChangeHead` (`status=pending`, `event_received_at=now()`) idempotently on `(change_id, head_sha)`, and enqueue attribution.
- [X] T053 [US1] Implement `services/prcheck/src/gca_prcheck/worker.py`. Per pending head, once `watermark ≥ event_received_at` (cap and loss handling arrive in US2 and US4):
  1. get added lines and per-file patches from the compare API for `merge_base...head`, in memory. **If the compare API omits a file's `patch`** (large files or diffs), fetch that file's blobs at the merge base and the head through the Git Data API and diff them in memory. If that's impossible (binary, or over the size limit), add `{path, reason: "too_large"}` to `excluded_paths`. A file is never dropped silently (Constitution I);
  2. credit each added line through GraphQL `blame` at head: lines whose blame commit is in the PR's commit list are credited to that commit's author `id` (R11). Commits whose author GitHub links to no account give `credited_github_id=None`;
  3. load candidates per credited author with `gca_core.identity.resolve_developer` (`captured_line` for that developer within `matching_window_days`, grouped by `alg` and `key_gen`);
  4. call `gcattr.attribute`;
  5. store `LineResult` rows and `ChangeHead.counts` from `gcattr.summarize`, and set `status=complete` and `coverage_status`.

  Discard all line text afterwards. Never log it.
- [X] T054 [US1] Implement `services/prcheck/src/gca_prcheck/checkrun.py`, which creates and updates the check run named `AI code attribution` exactly as [contracts/github-app.md](./contracts/github-app.md) describes:
  - conclusion always `neutral`;
  - the title format;
  - the summary table, including the anchored and broad split, coverage, `alg`, the library version, key generations, excluded paths and the portal link;
  - grouped notice annotations (at most 50 per update, batched), with no code in messages.

  Add `charts/gateway-code-attribution/templates/prcheck.yaml`.
- [X] T055 [US1] Implement the `gca setup github-app` subcommand in `services/portal/src/gca_portal/setup_cli.py`, registered through the `gca.commands` entry point. It uses the GitHub App manifest flow with exactly the permissions and events in [contracts/github-app.md](./contracts/github-app.md): it opens the browser, catches the redirect on `localhost`, exchanges the code, and writes `values-github.yaml` plus a Kubernetes Secret manifest with `appId`, `clientId`, `clientSecret`, `privateKey` and `webhookSecret`.

### Demo

- [X] T056 [P] [US1] Implement `services/demo/src/gca_demo/model.py` (`demo-model`), porting the probe's `mock_upstream.py`. It serves `/v1/chat/completions`, `/v1/responses`, `/v1/messages` and `/v1beta/models/{m}:streamGenerateContent` in the real streaming formats, with configurable chunk size (default 7 bytes). Responses come from scripted demo sessions in `services/demo/src/gca_demo/sessions/*.yaml`. Each session specifies, per API format, the tool calls to return (Write/Edit, `write_file`/`edit_file`, freeform `apply_patch`, Gemini `functionCall`) holding synthetic code for the sample repository.
- [X] T057 [P] [US1] Create the sample repository template under `services/demo/sample-repo/`: a small Python and TypeScript project with a README, plus `services/demo/sample-repo/.gca-demo.yaml` describing which files the demo sessions touch.
- [X] T058 [US1] Implement `gca demo run` in `services/demo/src/gca_demo/agent.py`, registered through `gca.commands` (`--repo OWNER/NAME`, `--gateway-url`, `--credential` defaulting to `GCA_CREDENTIAL`). It:
  1. clones the sample repo to a temporary directory;
  2. sends each scripted session's requests **through the gateway**, in each API format, with the adopter's credential;
  3. applies the returned tool outputs to files;
  4. applies the scripted human edits from the session YAML (some lines edited near AI output, some lines typed), so the PR exercises exact, anchored, broad, human and indeterminate outcomes;
  5. runs a formatter pass (`ruff format` on the Python files);
  6. commits as the signed-in `gh` user, pushes branch `gca-demo-<timestamp>`, and opens a PR with `gh pr create`.

  Also implement `gca demo init-repo --repo OWNER/NAME`. It creates the repository (private) with `gh repo create` if it doesn't exist, and pushes `services/demo/sample-repo/` to `main` (docs/install.md §2.4).
- [X] T059 [US1] Create `charts/gateway-code-attribution/templates/demo.yaml`. When `demo.enabled`, deploy `demo-model` and add gateway routes so model names `demo-openai`, `demo-anthropic` and `demo-gemini` reach it: agentgateway `llm.models[]` with `baseUrl` pointing at demo-model, and LiteLLM `model_list` entries with `api_base` pointing at demo-model.

### Dashboards (aggregate)

- [X] T060 [US1] Create Alembic migration `services/core/alembic/versions/0002_reporting_views.py` with `v_change_summary` (grain: change head, final or latest; counts by outcome with broad separate; `coverage_status`; `alg`) and `v_repository_daily` (sums of final heads merged per day). Each exposes `*_with_broad` and `*_without_broad` columns and has **no per-developer columns** (data-model.md "Reporting views"). Grant `SELECT` to `gca_reporting`.
- [X] T061 [US1] Configure the Grafana dependency in `charts/gateway-code-attribution/values.yaml` and `templates/grafana-provisioning.yaml`:
  - a PostgreSQL datasource as `gca_reporting`;
  - GitHub OAuth using the App's client, limited to `github.org`;
  - anonymous access off.

  Create `charts/gateway-code-attribution/dashboards/change.json` and `charts/gateway-code-attribution/dashboards/repository.json`, each with an "Include broad matches" variable that switches between the `*_with_broad` and `*_without_broad` columns, and showing `alg`.

### Install, parity, privacy, end to end

- [X] T062 [US1] Implement `scripts/demo.sh` for `make demo GATEWAY=…`. It creates a kind cluster (`kindest/node` from `versions.yaml`), builds and loads images (T037), runs `helm dependency build` and `helm install` with `demo.enabled=true` and `prcheck.delivery=polling`, waits for readiness, and prints the portal URL, the gateway port-forward and the next steps. Also implement `scripts/demo-upgrade.sh` and `scripts/demo-down.sh`.
- [X] T063 [US1] Create the cross-gateway conformance suite `tests/conformance/test_parity.py` with `tests/conformance/harness.py`. It starts agentgateway 1.6.0 (binary) with `capture-extproc`, and LiteLLM 1.105.1 (`uv run --with`, as a subprocess because the proxy keeps process-global state) with the handler publishing to a file, both against `demo-model`, with an in-memory NATS replacement that captures published messages. It replays every probe fixture and every demo session through each gateway, and asserts **identical multisets of `(t, l, x, m, b, p)` per capture event** (FR-006, R4).
- [X] T064 [US1] Create the privacy audit `tests/privacy/test_no_content.py` (SC-006). It runs on the kind cluster left by T065's end-to-end run, after that run completes. That run uses the pre-created test GitHub App (`GCA_E2E_APP`) and test repository (`GCA_E2E_REPO`), so the audit needs no browser setup or extra secrets. Run on its own, it first calls the same T065 fixtures to do a full demo run. It then scans:
  - every Postgres table, by dumping all text and bytea columns;
  - JetStream messages;
  - every pod log, including the gateway's;
  - Grafana's database;
  - LiteLLM's spend-log table, asserting no message or response content (`store_prompts_in_spend_logs: false`);

  for each code line in the demo sessions and the sample repo (normalized, at least 12 characters). It asserts zero occurrences.
- [X] T065 [US1] Create the end-to-end test `tests/e2e/test_us1_demo.py`. It uses a **pre-created test GitHub App** (secret `GCA_E2E_APP`), because the manifest flow needs a browser. It runs `make demo` for each gateway, `gca demo run` against a test repository (`GCA_E2E_REPO`), waits for the check run, and asserts:
  - non-zero counts for exact, anchored, broad, human and indeterminate;
  - `coverage_status=complete`;
  - the change appears in `v_change_summary`;
  - identical per-line outcomes across the two gateways;
  - elapsed time from install start to the completed check ≤ 30 minutes, **excluding App creation**. The authoritative SC-001 timing, including `gca setup github-app`, is the manual run in T120.
- [X] T066 [US1] Create `.github/workflows/gates.yml` with the constitution's required merge gates (Development Workflow & Quality Gates), and list its jobs as required status checks in `docs/maintainers.md`:
  - `conformance` runs `tests/conformance` when `lib/**`, `services/core/**` or `services/capture-*/**` change;
  - `clean-install` runs `tests/e2e/test_us1_demo.py` on kind, with secrets `GCA_E2E_APP` and `GCA_E2E_REPO`, when `lib/**`, `services/**` or `charts/**` change. It reports time to first result (M7);
  - `privacy` runs `tests/privacy` **in the same job, right after `clean-install`, on the same cluster** (data-path gate, T064). A path change that triggers one triggers both;
  - `no-recorder` runs `scripts/check-no-recorder.sh` on every PR. **Create this script in this task.** It fails if any file under `services/` or `charts/` imports from `eval`, references `GCA_RECORD_DIR`, or adds a recording or "record" mode to a capture service. T111 extends it with an image check once the recorder exists.

  T095 (alg-bump check), T110 (release gate and release-bar consistency) and T113 (supported-tools check) add their jobs to this same workflow.
- [X] T067 [P] [US1] Write `docs/install.md`, covering quickstart.md section 1 (prerequisites, `make demo`, `gca setup github-app`, the sample repository, the credential, `gca demo run`, dashboards), and `docs/outcomes.md`, which explains the four outcomes, *not observed*, confidence, and that "human" means "no match to observed AI output". Fix the display labels and use them everywhere (docs, the T054 check summary, the T061 dashboards, the portal): `AI, unmodified`; `AI, modified (anchored)`; `AI, modified (broad)`; `Human`; `Indeterminate`; `Not observed`. These follow constitution Principle I's wording.
- [X] T068 [P] [US1] Write `docs/privacy.md`, the documented assessment of what the similarity fingerprint reveals that Constitution II requires before shipping. Base it on research R9: keyed shingles and MinHash, what a key holder can confirm about short lines, the trivial-line exclusion, and which services can read the key. Include the US jurisdiction statement (FR-040).

**Checkpoint**: User Story 1 is fully functional. Both gateways show a demonstration PR in all four outcomes, and
the conformance and privacy suites pass. **This is the MVP.**

---

## Phase 4: User Story 2 - Attribute real pull requests for developers using AI coding tools (Priority: P2)

**Goal**: Real use on real repositories: webhooks, the pending gate, multi-author credit, unmapped authors,
exclusions, re-runs on each push, a final result at merge, history rewrites, key rotation, bring-your-own provider
keys, and routing for each in-scope tool.

**Independent Test**: quickstart.md sections 2 and 5. Each scripted case PR shows its expected result, and a real
in-scope tool used with a real provider key gives the same check behaviour.

- [X] T069 [US2] Implement `services/prcheck/src/gca_prcheck/webhooks.py`: `POST /webhooks/github`, which verifies `X-Hub-Signature-256` with the webhook secret and deduplicates on `X-GitHub-Delivery` in a table `webhook_delivery(id text pk, received_at)`. Add the table in a migration `services/core/alembic/versions/0003_webhook_delivery.py`. Map `pull_request` opened, synchronize and reopened to new heads; `closed` to updating `Change.state`; and `check_run.rerequested` to re-attributing the same head idempotently (FR-020). Make delivery selectable with `prcheck.delivery` in `templates/prcheck.yaml`, and add an Ingress or Service for webhook mode.
- [X] T070 [US2] Extend `services/prcheck/src/gca_prcheck/worker.py` with the pending gate. A head stays `pending` (check run `in_progress`, title "Waiting for capture to catch up") until `watermark ≥ event_received_at`. After `pendingCapMinutes` (default 10) it proceeds with `coverage_status=incomplete` (FR-017, R12).
- [X] T071 [US2] Extend `services/prcheck/src/gca_prcheck/worker.py` and `webhooks.py` for per-head results and the merge result. Every new head gets its own `ChangeHead`, and earlier heads are left unchanged. On `closed` with `merged=true`, set `Change.state=merged`, `final_head_id` to the merged head's `ChangeHead`, and `is_final=true` (FR-018). On `closed` without merge, set `state=closed`.
- [X] T072 [US2] Implement exclusions in `services/prcheck/src/gca_prcheck/exclusions.py`. Match glob rules from `PortalSettings.exclusion_rules`, defaulting to the values in contracts/helm-values.md `attribution.exclusions`, against the added-line paths. Excluded files aren't attributed. They're listed in `ChangeHead.excluded_paths` as `{path, reason}` and shown in the check summary with their reason (FR-021). The reasons are:
  - `rule`: matched an exclusion glob;
  - `binary`: a binary file;
  - `too_large`: more than 5,000 added lines in the file, or the file's diff couldn't be read (T053).
- [X] T073 [US2] Implement unmapped and partly mapped authors in `services/prcheck/src/gca_prcheck/worker.py`. Lines credited to a GitHub account that `resolve_developer` can't map, or to a commit author with no GitHub account (`credited_github_id=None`), get the state `not_observed`. If no commit author in the PR is mapped, set `coverage_status=not_observed` and say so in the check title (FR-015).
- [X] T074 [US2] Implement identity override administration in `services/portal/src/gca_portal/admin_overrides.py` with `admin_overrides.html.j2`: `GET` and `POST /admin/overrides`, and `DELETE /admin/overrides/{id}`. A `reason` is required; a duplicate `github_id` returns 409 `conflict`; admin role only. Until US3 adds role resolution, a temporary `gca_core.roles.is_admin` checks GitHub organization ownership, or membership of `portal.adminLogins` for installs on a personal account (FR-016).
- [X] T075 [US2] Implement `POST /admin/credentials/{id}/revoke` in `services/portal/src/gca_portal/credentials.py`, using the same gateway-side removal as `DELETE /me/credential` and setting `status=revoked` and `revoked_at`.
- [X] T076 [US2] Implement key rotation (FR-036) in `services/portal/src/gca_portal/admin_keys.py`, `services/core/src/gca_core/keys.py` and `services/ingest/src/gca_ingest/maintenance.py`:
  - `POST /admin/keys/rotate` in `services/portal/src/gca_portal/admin_keys.py` creates a new `KeyGeneration` (active) and retires the old one (`retired_at=now()`, `expires_at=retired_at+retention_days`). It writes the new key file into the fingerprint key Secret and updates `active`.
  - Capture services reload keys when the Secret changes (watch the mounted directory in `gca_core.keys`).
  - prcheck loads every non-expired key generation for matching.
  - Add `services/ingest/src/gca_ingest/maintenance.py`, a daily job that marks generations `expired` after `expires_at` and calls `gca_drop_partitions_older_than(retention_days)`. The portal's key-sync loop removes expired generations' key files, so the portal stays the only writer of the Secret.
- [X] T077 [US2] Implement bring-your-own provider keys (FR-039) in `templates/agentgateway.yaml` and `templates/litellm.yaml`. When `providers.existingSecret` and `providers.models` are set, render one route per model entry (`provider: anthropic|openAI|gemini`) with the provider key read from the Secret. In demo mode, keep the demo routes alongside.
- [X] T078 [US2] Validate research R3 and record the outcome in `docs/validation/R3-litellm-gemini.md`. Check whether Gemini CLI's native `streamGenerateContent`, routed to LiteLLM 1.105.1's `/gemini` pass-through, delivers tool calls to the handler. If it does, add the route to `templates/litellm.yaml` and `gcattr.adapters.litellm`. If it doesn't, have `gca_capture_litellm.handler` emit `failure(unsupported_combination, tool_hint="gemini-cli")` for that route (FR-007), and document it.
- [X] T079 [P] [US2] Write the per-tool routing guides `docs/tools/claude-code.md`, `docs/tools/codex-cli.md`, `docs/tools/gemini-cli.md` and `docs/tools/opencode.md` from the research R6 table, including the `codex logout` caveat and the Gemini auth mechanism. Write `docs/tools/not-observed.md` listing interactions that can't be observed (Copilot inline and next-edit completions; Cursor Tab, Composer and inline edit; chat output pasted from elsewhere) and that Copilot and Cursor are out of scope for v1 (FR-040, FR-041).
- [X] T080 [US2] Implement `gca demo scenarios` in `services/demo/src/gca_demo/scenarios.py`, which opens one PR per case in quickstart.md section 2:
  - unmodified AI lines;
  - edited AI lines;
  - typed-only lines;
  - trivial lines;
  - a rebase onto a moved base, a squash and a cherry-pick (scripted with `git`);
  - a PR opened while ingest is paused (`gca demo pause-ingest` scales `ingest` to 0);
  - an unmapped author (`--as-unmapped` commits with an author email linked to no GitHub account);
  - two mapped authors (requires a second credential, `GCA_CREDENTIAL_2`);
  - a new push to an open PR.

  Each PR carries an answer file in the branch at `.gca-expected.json`.
- [X] T081 [US2] Create the integration test `tests/integration/test_prcheck_edge_cases.py`. For each PR from `gca demo scenarios`, compare the stored `LineResult` rows with `.gca-expected.json`, and assert the head, pending, final and not-observed behaviour from spec User Story 2, scenarios 1–9.

**Checkpoint**: User Stories 1 and 2 both work. Real PRs are attributed correctly through the edge cases.

---

## Phase 5: User Story 3 - Review attribution across changes, repositories and teams (Priority: P3)

**Goal**: Team totals, GitHub-derived roles with overrides, and role-checked per-developer drill-down.

**Independent Test**: quickstart.md section 3. Org owners, team maintainers and plain members get exactly the
per-developer access FR-029 and FR-029a define. Team totals equal the sum of their members' credited lines, and
the broad toggle changes only broad counts.

- [X] T082 [US3] Implement team sync in `services/portal/src/gca_portal/teamsync.py`. Handle the GitHub App events `membership`, `team` and `organization` (routed from `services/prcheck/src/gca_prcheck/webhooks.py` or polling) and run a full resync every 6 hours:
  - upsert `Team` (`source=github`) for every team in `github.org`;
  - reconcile `TeamMembership` (`source=github`) by closing departed members' rows (`valid_to=now()`) and opening rows for new members (`valid_from=now()`), never deleting;
  - upsert `TeamLead` (`source=github_maintainer`) for maintainers.

  Override rows (`source=override`) are never changed by sync (FR-027).

  *Implemented in `services/prcheck/src/gca_prcheck/teamsync.py`*, not the portal: the PR check already holds
  the App key and receives the webhooks, so the portal keeps acting only with the signed-in user's token. Sync
  also runs within a minute of a developer's first sign-in.
- [X] T083 [US3] Implement `services/core/src/gca_core/roles.py`. `roles_for(developer) -> set[Role]` follows data-model.md "Working out a viewer's role": organization owner → `admin`; maintainer of team T → `team_lead(T)`; then `ViewerRoleGrant` grants and revokes are applied. `can_view_developer(viewer, target)` respects `PortalSettings.per_developer_enabled` and `visible_roles`. Defaults: admins see all developers; team leads see members of the teams they lead; others see none (FR-029, FR-029a). Replace T074's temporary `is_admin` with `roles_for`. **GitHub-derived roles are checked live** with the viewer's GitHub token (organization role and team maintainership), cached for at most 60 seconds, so GitHub-side changes apply within 60 seconds (FR-029a). In-stack grants and revokes apply at the next request.
- [X] T084 [US3] Implement role and team administration in `services/portal/src/gca_portal/admin_roles.py` and `admin_teams.py`, with templates: `GET/POST /admin/roles` and `GET/POST /admin/teams`, to grant or revoke admin and team-lead roles and add or remove team members as overrides. Implement `GET/POST /admin/settings` in `admin_settings.py` for `per_developer_enabled`, `visible_roles`, the matching window, retention and exclusions. All are admin only.
- [X] T085 [US3] Implement per-developer views in `services/portal/src/gca_portal/developers.py` with `developer.html.j2` and `team_developers.html.j2`:
  - `GET /developers/{github_login}` shows per-developer totals over a selectable period, with and without broad, aggregated from `LineResult.credited_developer_id` on final heads.
  - `GET /teams/{slug}/developers` shows a per-developer breakdown.

  Both enforce `can_view_developer` and return 403 `forbidden` without revealing whether the target exists (contracts/portal-http.md).
- [X] T086 [US3] Create Alembic migration `services/core/alembic/versions/0004_team_view.py` with `v_team_daily`: team × day sums of line credits on final heads to that team's members, using membership as of the merge date (`valid_from ≤ merged_at < coalesce(valid_to, ∞)`), with `*_with_broad` and `*_without_broad` columns and no per-developer columns. Grant to `gca_reporting`. Create `charts/gateway-code-attribution/dashboards/team.json` with the broad toggle and `alg`.
- [X] T087 [US3] Create `tests/integration/test_roles.py` covering the viewer role matrix:
  - an org owner can view any developer;
  - a team maintainer can view only their team's members;
  - a plain member gets 403;
  - a `ViewerRoleGrant` grant or revoke changes access at the next request;
  - `per_developer_enabled=false` hides the views from everyone.

  Also check that team totals equal the sum of member credits.

**Checkpoint**: Stories 1–3 work on their own.

---

## Phase 6: User Story 4 - See coverage and blind spots (Priority: P4)

**Goal**: Every capture failure and blind spot is visible, and nothing is counted as human. Capture fails open.

**Independent Test**: quickstart.md section 4. Injected faults appear with the right causes and counts. Stopping
capture or NATS never fails a gateway request, and records a loss period that flags overlapping PRs as incomplete.

- [X] T088 [US4] Implement loss detection in `services/ingest/src/gca_ingest/loss.py` (R12):
  - **sequence gaps**: if a received `seq` is more than `last_seq + 1` for that instance, write `CaptureLoss(cause=seq_gap, count=gap)`;
  - **stale instances**: when T046's sweeper marks an instance `stale`, open `CaptureLoss(cause=heartbeat_missed)`. Close it when heartbeats resume (`status=active`) or on a `shutting_down` heartbeat (`closed`);
  - **self-reported failures**: `failure` messages become `CaptureLoss` rows with their `cause`, `count`, `credential_id` → `developer_id`, `api_format` and `tool_hint`.

  Ingest never discards a failure without recording it (FR-005, SC-005).
- [X] T089 [US4] Implement incomplete coverage in `services/prcheck/src/gca_prcheck/coverage.py`. Set a head's `coverage_status=incomplete` if any `CaptureLoss` overlaps `[event_received_at - matching_window, event_received_at]`, where either its `developer_id` is a credited author or its `developer_id` is null (`seq_gap`, `heartbeat_missed`). The check summary lists the reasons (FR-022).
- [X] T090 [US4] Emit `failure(unsupported_combination)` with `tool_hint` and `api_format` from both capture adapters (`services/capture-extproc/src/gca_capture_extproc/server.py`, `services/capture-litellm/src/gca_capture_litellm/handler.py`) whenever a response's API format or tool can't be parsed by `gcattr` (FR-007). Emit `failure(unknown_credential)` when identity is missing.
- [X] T091 [US4] Create Alembic migration `services/core/alembic/versions/0005_coverage_view.py` with `v_coverage_daily`: gateway × API format × tool × cause × day totals of `CaptureLoss`, unsupported combinations, and the daily count of distinct unmapped GitHub accounts credited in PRs. Create `charts/gateway-code-attribution/dashboards/coverage.json` with loss over time by cause, observed versus not-observed combinations, and the static list from `docs/tools/not-observed.md` as a text panel. Implement `GET /coverage` in `services/portal/src/gca_portal/coverage.py`, linking to the dashboard and listing unmapped GitHub logins credited in PRs (FR-030).
- [X] T092 [US4] Add fault injection to `services/demo/src/gca_demo/model.py` and `agent.py` with `gca demo run --inject-faults truncated=N,unexpected_format=M`. demo-model returns N streams truncated mid-tool-call, with `max_tokens` stop reasons, and M streams with schema-deviant events (for example `response.completed` missing `created_at`, as the probe found).
- [X] T093 [US4] Create the end-to-end test `tests/e2e/test_us4_coverage.py`:
  - (a) inject faults and assert the coverage counts equal the injected counts, with the right causes and none counted as human (SC-005);
  - (b) scale `capture-extproc` to 0 (agentgateway) or stop NATS (LiteLLM) during demo traffic, and assert 100% of gateway requests succeed (FR-005a);
  - (c) after restoring, assert a `heartbeat_missed` or `buffer_overflow` loss is recorded, and that a PR whose window overlaps it shows `coverage_status=incomplete`;
  - (d) slow processor: inject a 2-second delay into `capture-extproc`'s background parsing and assert client p95 completion time is unchanged within SC-010. Inject a delay on the echo path and assert requests still succeed, through the T038 timeout and failOpen.

**Checkpoint**: Stories 1–4 work on their own.

---

## Phase 7: User Story 5 - Reuse the versioned matching library (Priority: P5)

**Goal**: `gcattr` is released as a stand-alone, versioned and deterministic library with a CLI, giving the same
results as the stack.

**Independent Test**: quickstart.md section 6. Golden files pass on Linux and macOS, and
`gca attribute` matches the PR check for the same head.

- [X] T094 [US5] Create the golden corpus generator `lib/tests/golden/generate.py` and the corpus `lib/tests/golden/alg-1/`: input streams (from `lib/tests/fixtures`) plus a fixed test key (32 bytes of `0x42`, `key_gen=1`) mapped to expected `LineFingerprint` JSON and expected `attribute` outcomes. Add `lib/tests/test_golden.py`, asserting byte-identical output (FR-033, SC-008), run in CI on Linux and macOS (T008).
- [X] T095 [US5] Create `scripts/check-alg-bump.sh`, wired into CI. If `lib/tests/golden/alg-*` outputs change without a new `ALG` value and corpus directory in the same change, fail with a message citing Constitution III and FR-032.
- [X] T096 [US5] Implement the library CLI in `lib/src/gcattr/cli.py`, per [contracts/library-api.md](./contracts/library-api.md):
  - `gca version`;
  - `gca fingerprint --alg --key-file --format`, which reads a recorded stream from stdin and prints fingerprint JSON lines with no content;
  - `gca attribute --repo --base --head --captures --key-file`, which reads added lines through `git diff --unified=0 <merge-base>..<head>` and `git blame --porcelain <head> -- <path>` held in memory, writes nothing to disk, and prints outcomes per line and a summary;
  - `--json`, exit codes, and plugin subcommands loaded from the `gca.commands` entry points.
- [X] T097 [US5] Create `tests/integration/test_cli_matches_prcheck.py`. For a demo PR head, export that head's candidates (`captured_line` rows, no content) to `captures.jsonl`, run `gca attribute` on a local clone, and assert per-line outcomes identical to the stored `LineResult` rows.
- [X] T098 [US5] Create `.github/workflows/release.yml`, triggered on `v*` tags (R21):
  - build the `gcattr` wheel and sdist;
  - write `SHA256SUMS`;
  - publish to PyPI with trusted publishing and attestations;
  - attach the artifacts to the GitHub Release;
  - build and push the service images to `ghcr.io` with digests in the release notes;
  - package the Helm chart (`helm package`) with a checksum, and push it to the GitHub Pages chart repository or an OCI registry.
- [X] T099 [P] [US5] Write `docs/library.md`: the Python API summary, the CLI, the versioning guarantees (semver versus `ALG`, the Unicode pin, `SUPPORTED_ALGS`) and an example of using `gcattr` outside the stack.

**Checkpoint**: Stories 1–5 work on their own.

---

## Phase 8: User Story 6 - Measure attribution quality before publishing (Priority: P6)

**Goal**: The published scenario set, the evaluation harness, threshold calibration, the quality report, and the
release gate in CI. No tool is listed as supported without recorded real traffic.

**Independent Test**: quickstart.md section 7. `gca eval --gateway both` produces a schema-valid report for both
gateways. Degrading the thresholds makes the release gate fail and name the failing measures.

- [X] T100 [US6] Define the scenario format in `eval/harness/src/gca_eval/scenario.py` and document it in `eval/scenarios/README.md`. A scenario is a directory with:
  - `repo.yaml`: the initial files and an ordered list of git operations (commits by author alias, rebase, squash, cherry-pick);
  - `streams/*.sse`: model output per API format, with the session and author alias;
  - `edits.yaml`: human edits and formatter passes applied after AI output;
  - `expected.json`: an outcome per added line, and the tier for AI modified lines.

  Aliases map to test developers with fixed credentials.
- [X] T101 [P] [US6] Author the seed scenarios in `eval/scenarios/seed-*/`, recreating the categories from spec 002's measured set (the handoff's section 6): line accuracy (59 lines across unmodified, edited, typed and trivial lines), and history rewrites (30 agent lines across a rebase onto a moved base and `merge --squash`). If the owner provides the original spec 002 scenario files from the `ai-gateway` project, import them instead and note where they came from in `eval/scenarios/README.md`.
- [X] T102 [P] [US6] Author `eval/scenarios/human-edits-*/`, covering single-token edits, renamed identifiers, added arguments, edited string literals and deleted-then-retyped lines. Each line is labelled with its expected tier (anchored versus broad) based on whether same-file exact anchors exist. Include **unapplied model output** (captured but never applied to the repo), to confirm it doesn't raise the AI share, and a path-only case (same file path, no exact match), which must be broad or human, never anchored.
- [X] T103 [P] [US6] Author `eval/scenarios/formatters-*/`, covering Python (Black, pinned version), TypeScript (Prettier, pinned) and Go (gofmt, pinned) passes over AI output. That includes quote-style changes, wrapped long lines and trailing commas. Pin the formatter versions in `eval/harness/formatters.lock`.
- [X] T104 [P] [US6] Author `eval/scenarios/lookalike-*/` (human-written code that resembles common AI output but has no matching capture, for the false-AI-modified rate) and `eval/scenarios/refactor-*/` (renames and extractions across files).
- [X] T105 [P] [US6] Author `eval/scenarios/multi-author-*/` (two authors, one PR, crediting) and `eval/scenarios/faults-*/` (truncated streams, schema-deviant streams and a dropped-sequence simulation, with expected loss counts), plus `eval/scenarios/key-rotation-*/` (output captured under key generation 1, a rotation, then a PR attributed afterwards that must still match) and `eval/scenarios/empty-*/` (deletion-only and excluded-only PRs that must report nothing attributable, not 0%).
- [X] T106 [US6] Implement the harness runner `eval/harness/src/gca_eval/runner.py`. For each gateway, it starts the gateway locally (agentgateway 1.6.0 binary with capture-extproc, or LiteLLM 1.105.1 with the handler, reusing `tests/conformance/harness.py`) together with `demo-model` serving the scenario streams, plus a testcontainers Postgres and NATS with `ingest`. It replays each scenario's streams with the test credentials, builds the scenario git repository in a temporary directory, attributes each PR range with the same code path as prcheck (`gcattr.attribute` with database candidates and `git blame` crediting), and records per-line results.
- [X] T107 [US6] Implement the quality report in `eval/harness/src/gca_eval/report.py`, following [contracts/quality-report.schema.json](./contracts/quality-report.schema.json):
  - accuracy;
  - per-outcome precision and recall;
  - `false_ai_modified_anchored` and `false_ai_modified_broad` (human lines labelled AI modified by each tier, over lines labelled with that tier);
  - `formatter_false_human`;
  - `history_rewrite_survival`;
  - `capture` counts, with `silent_loss` = responses neither captured nor reported as loss;
  - `cross_gateway_agreement`.

  Read the release-bar constants from the schema file. That schema is the single source; never redefine the numbers in code.

  The release-bar constants are 0.95, 0.02, 0.05, 0.10 and 0 (SC-002, SC-003, FR-044). Validate the output against the schema.
- [X] T108 [US6] Implement `gca eval` in `eval/harness/src/gca_eval/cli.py`, registered through `gca.commands` (`--scenarios`, `--gateway agentgateway|litellm|both`, `--out`). Exit 0 when the bar is met, 10 when the release bar is missed (listing failing measures), and 11 on silent loss, as in contracts/library-api.md.
- [X] T109 [US6] Implement threshold calibration in `eval/harness/src/gca_eval/calibrate.py`. Sweep `anchored_threshold` (0.30–0.90) and `broad_threshold` (0.50–0.95) in steps of 0.05 over a calibration split of the scenario set (a fixed seed with 70% calibration, 30% held out). Choose the thresholds that maximize accuracy subject to `false_ai_modified_anchored ≤ 0.02` and `false_ai_modified_broad ≤ 0.05` on the calibration split. Report the held-out results, and write the chosen values into `lib/src/gcattr/algorithm.py` `PARAMS[1]` (allowed only before the first release of `alg=1`; afterwards it needs a new `ALG`).
- [X] T110 [US6] Create `.github/workflows/release-gate.yml`, run on pull requests to `main` and required by `release.yml`. It runs `gca eval --scenarios eval/scenarios --gateway both --out report.json`, uploads `report.json`, and fails on exit codes 10 or 11 (Constitution V, FR-044). Add `scripts/check-release-bar.sh` as a job in `.github/workflows/gates.yml`. It fails if the SC-002/SC-003 numbers in `specs/001-gateway-code-attribution/spec.md` differ from the `release_bar` constants in `contracts/quality-report.schema.json`.
- [X] T111 [US6] Implement the real-traffic recorder as a **standalone developer tool** in `eval/corpus/record.py`. It's a local HTTP recording proxy that the consenting owner runs on their own machine, between their coding tool and the gateway. It forwards requests unchanged and writes each raw client-facing response stream to `eval/corpus/<tool>/<api_format>/<n>.sse`, with a `consent.yaml` stating the owner and consent.
  - **It is never part of a deployed service** (Constitution II: the system must not persist model output). Recording code is not added to `capture-extproc` or any service package, and `eval/` is excluded from every image built by T037 and from the chart.
  - Extend `scripts/check-no-recorder.sh` (created in T066) so it also fails if any image built by T037 contains `eval/corpus/record.py` or any file from `eval/`. It inspects the image filesystems with `docker image save` or `crane export`.
  - Under constitution v1.0.1, corpus files may hold only synthetic tasks run by a consenting owner.
  - Document how to record in `eval/corpus/README.md`.
- [ ] T112 [US6] *(Claude Code recorded 2026-10-15 and wired into conformance and the eval, `corpus-claude-code`; Codex CLI, Gemini CLI and OpenCode not recorded, so not listed as supported)* Record the real-traffic corpus for Claude Code, Codex CLI, Gemini CLI and OpenCode through each gateway, using the scripted coding tasks in `eval/corpus/tasks.md`. **This needs the owner to run the tools with their provider keys.** Then add the corpus to both the conformance suite (`tests/conformance/test_parity.py`) and the eval runner. This also validates research R6: Codex's freeform `apply_patch` and Claude Code's full edit-tool set. For each tool, record in `eval/corpus/<tool>/setup.md` that routing needed only an endpoint and credential change and no install (SC-011).
- [X] T113 [US6] *(alg 1 thresholds frozen at anchored 0.35, broad 0.75 on 2026-10-15; supported tools: Claude Code)* Gate supported tools in `scripts/check-supported-tools.sh`, wired into CI. `docs/tools/supported.md` may list a tool only if `eval/corpus/<tool>/` exists with `consent.yaml` and passes conformance (FR-045). Run T109 calibration on the full scenario set and corpus, freeze `alg=1` thresholds, and regenerate the golden files (T094).

**Checkpoint**: All six stories work, and the release gate is in force.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Performance, sizing, hardening and documentation across all stories.

- [X] T114 [P] Create the Locust performance suite in `tests/perf/`. `tests/perf/locustfile.py` simulates 500 active developers (configurable) sending streamed tool-call responses through the gateway from `demo-model`, with realistic think times. `tests/perf/run.sh` (`make perf`) runs each gateway with capture on and off, reports p95 response completion time, and asserts overhead ≤ 5% (SC-010, research R2 at load). It also opens PRs of 1,000 added lines and asserts the check completes in 2 minutes or less after the watermark passes (SC-009), at the SC-013 load with 90 days of synthetic captured lines pre-loaded.
- [X] T115 Write `docs/sizing.md` from `make perf` results and research R14: measured Postgres size per million captured lines, the projected size at 500 developers over 90 days (validating the 30–40 GB estimate and the 100 Gi default), NATS sizing, replica guidance for `capture-extproc` and `ingest`, and guidance beyond 500 developers. Mark the CloudNativePG operator as the production path, without high-availability guarantees in v1 (SC-013).
- [X] T116 [P] Harden the chart in `charts/gateway-code-attribution/templates/`:
  - NetworkPolicies, so only `capture-extproc`, `ingest`, `prcheck` and `portal` reach Postgres and NATS, and only the gateway reaches `capture-extproc`;
  - `securityContext` (non-root, read-only root filesystem, dropped capabilities);
  - resource requests and limits;
  - Pod Security "restricted" labels on the namespace.
- [X] T117 [P] Write `docs/github-app.md`, listing every permission and event with its reason (copied from [contracts/github-app.md](./contracts/github-app.md)), plus webhook versus polling mode and how to uninstall (FR-023).
- [X] T118 [P] Write `docs/upgrade.md` (key rotation, `alg` upgrades and what happens to older results, migrations) and `docs/configuration.md`, the full values reference generated from `values.schema.json`.
- [X] T119 Run `scripts/pin-digests.sh` and commit the resolved digests in `versions.yaml` and `values.yaml`. Add a CI check that fails if any image in the rendered chart lacks a digest (Constitution VI).
- [ ] T120 *(section 1 run 2026-10-16 for both gateways and recorded in `docs/validation/quickstart-run.md`; SC-001 met; privacy audit, sections 6 and 7 run 2026-10-16 and passed; section 2, section 4 step 2 and SC-011 run 2026-10-16; left: `scn-pending` rerun after its fix, two-authors (needs a second account), section 4 step 1)* Run every section of quickstart.md from start to finish on a clean machine for both gateways, and record the results in `docs/validation/quickstart-run.md`. This run is the **authoritative SC-001 measurement**, including `gca setup github-app`. Also confirm each in-scope tool needed no per-machine install (SC-011). Fix any step that doesn't match the guide.
- [X] T121 Update `README.md` with the project summary, the outcome definitions, links to the install, tools, privacy and library docs, the current `docs/tools/supported.md` list, the US jurisdiction statement and the latest quality report summary. Quote numbers only once T110 is green on `main` (Constitution V).

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)** has no dependencies.
- **Foundational (Phase 2)** depends on Setup and **blocks every user story**:
  - T038 (R2) must finish before T041 and T043;
  - T039 (R5) must finish before T049 and T043.
- **US1 (Phase 3)** depends on Foundational. It is the MVP.
- **US2 (Phase 4)** depends on Foundational. It extends US1's worker, portal and chart files, so in practice it
  follows US1. It doesn't need US3–US6.
- **US3 (Phase 5)** depends on Foundational and on US1's portal sign-in (T048). It replaces T074's temporary admin
  check if US2 was done first.
- **US4 (Phase 6)** depends on Foundational and US1 (capture, ingest, PR check).
- **US5 (Phase 7)** depends on Foundational. T097 needs US1's PR check.
- **US6 (Phase 8)** depends on Foundational and on US1's capture services (the harness reuses them):
  - T113 depends on T112, which needs the owner.
  - T110's gate must be green before any public release.
- **Polish (Phase 9)** comes after the stories you want to ship. T121 comes after T110.

### Story dependency graph

```text
Setup → Foundational ─┬─> US1 (MVP) ─┬─> US2 ──┐
                      │              ├─> US3   ├─> Polish
                      │              ├─> US4   │
                      │              └─> US6 ──┘
                      └─> US5 (T094–T096, T098, T099 need only Foundational; T097 needs US1)
```

### Within each story

Data model and migrations come first, then services, then UI and check output, then chart templates, then tests
and docs. Validation spikes (T038, T039, T078, T112) come before the code that depends on them.

## Parallel Opportunities

- **Setup:** T003–T010 run in parallel after T001 and T002.
- **Foundational:**
  - T012, T013 and T014 in parallel, after T011;
  - T017 and T018 in parallel;
  - the models T026–T029 in parallel;
  - T031, T034 and T035 in parallel;
  - T037 in parallel with the library work;
  - T038 and T039 in parallel with each other and with the library work.
- **US1:** the agentgateway capture (T040–T043), the LiteLLM capture (T044–T045), the demo (T056, T057) and the
  docs (T067, T068) are independent tracks, which meet at T062–T065.
- **US6:** scenario authoring T101–T105 is fully parallel.
- **Across stories:** after US1, US3, US4 and US5 can proceed in parallel. They touch mostly separate files, except
  `worker.py`, where US2 and US4 should be sequenced.

## Parallel Example: User Story 1

```bash
# Track A: agentgateway capture
Task: "T040 Generate ext_proc v3 stubs into services/capture-extproc/src/gca_capture_extproc/_gen/"
Task: "T041 Implement services/capture-extproc/src/gca_capture_extproc/server.py"

# Track B: LiteLLM capture (parallel with A)
Task: "T044 Implement services/capture-litellm/src/gca_capture_litellm/handler.py"

# Track C: demo assets (parallel with A and B)
Task: "T056 Implement services/demo/src/gca_demo/model.py"
Task: "T057 Create services/demo/sample-repo/"

# Track D: docs (parallel)
Task: "T067 Write docs/install.md and docs/outcomes.md"
Task: "T068 Write docs/privacy.md"
```

## Parallel Example: User Story 6

```bash
Task: "T101 Author eval/scenarios/seed-*/"
Task: "T102 Author eval/scenarios/human-edits-*/"
Task: "T103 Author eval/scenarios/formatters-*/"
Task: "T104 Author eval/scenarios/lookalike-*/ and refactor-*/"
Task: "T105 Author eval/scenarios/multi-author-*/ and faults-*/"
```

## Implementation Strategy

### MVP first (User Story 1 only)

1. Phase 1: Setup.
2. Phase 2: Foundational, including the R2 and R5 validations. **Stop if either fails without a workable
   fallback**, and revisit the plan.
3. Phase 3: User Story 1.
4. **Stop and validate:** quickstart.md section 1 with both gateways, plus the conformance and privacy suites.
5. Internal demo only. Under Constitution V, nothing is published and no numbers are quoted until US6's release
   gate (T110) is green.

### Incremental delivery

1. US1, the MVP demo.
2. US2: real PRs, BYO keys and per-tool docs. **First internal pilot** at the owner's company.
3. US3: roles and per-developer views.
4. US4: coverage. Required before trusting pilot numbers.
5. US5: the library release.
6. US6: the scenario set, calibration and the release gate. **Public release and blog post only after T110 is
   green.**
7. Polish: performance, sizing, hardening and docs.

### Notes

- Commit after each task or logical group, following the constitution's merge gates in CONTRIBUTING.md.
- T112 is the one task that requires the owner (real tools and provider keys). Plan it early in US6.
- Avoid editing `services/prcheck/src/gca_prcheck/worker.py` from two stories at once (US1, US2, US4). Sequence
  those tasks.
