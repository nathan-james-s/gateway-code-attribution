# Phase 0 Research: Gateway Code Attribution Reference Stack

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-10-14

These decisions resolve every unknown in the plan's Technical Context. Sources:
- the assessment (`.specify/assessments/gateway-code-attribution/`), including the streamed tool-call probe in
  `probes/streamed-tool-calls/`;
- agentgateway's v1.6.0 configuration schema (`schema/config.md`, `schema/cel.md` at tag `v1.6.0`);
- repository metadata for each dependency, checked on 2026-10-14.

Items marked **Validate** are decisions with a named check in `tasks.md`. If a check fails, the fallback listed
alongside applies. These are not open questions.

---

## R1. Implementation language

- **Decision**: Python 3.12 for every component: the library, both capture adapters, ingest, the PR check, the
  portal, the demo, and the evaluation harness. It is one uv workspace.
- **Rationale**:
  - Constitution III requires a single matching library used by every component.
  - LiteLLM's capture hook must run in-process in Python (`CustomLogger`), so a Python library avoids a second
    implementation or a cross-language binding.
  - The 500-developer scale (SC-013) is within reach of async Python services that scale out.
  - One language keeps the maintenance load workable for a single maintainer (concept assumption 14).
- **Alternatives considered**:
  - A Rust core with Python bindings: faster, but it adds a build toolchain and a cross-platform determinism
    surface across two languages.
  - Go services plus a Python library: that's two implementations, which Constitution III forbids.

## R2. Capture with agentgateway

- **Decision**: Use agentgateway's `llm.policies.extProc` (external processing) to stream the **client-facing
  response body** to a capture service, `capture-extproc`, over gRPC.
  - Settings: `failureMode: failOpen`, `processingOptions.responseBodyMode: fullDuplexStreamed`, and
    `requestHeaderMode: send`.
  - `metadataContext` passes the authenticated identity (API-key metadata) and the coding tool's session header
    through CEL.
  - The service echoes each body chunk back unchanged straight away, and reassembles and fingerprints in the
    background, holding content in memory only.
- **Rationale**:
  - It keeps code out of every log and trace (Constitution II). The `llm.toolCalls` and `llm.completion` CEL
    fields would have to be exported through logging or OTLP, which puts code into a log pipeline.
  - The library parses the raw stream itself, which closes agentgateway 1.6.0's native-Gemini gap: its own
    `passthrough_stream` for Gemini never accumulates tool calls.
  - `failOpen` gives the fail-open behaviour in FR-005a.
- **Alternatives considered**:
  - CEL `llm.toolCalls` exported to an in-memory OTLP receiver: simpler, but it routes code through log or trace
    plumbing, and it misses native Gemini.
  - A sidecar proxy in front of agentgateway: duplicates the gateway's job.
- **Validate**:
  - `fullDuplexStreamed` with pass-through echo keeps SC-010 (≤ 5% p95 overhead) at the 500-developer load.
  - `failOpen` really bypasses a dead processor mid-stream.

  **Fallback**: `responseBodyMode: bufferedPartial` for non-streamed requests, or extra `capture-extproc`
  replicas. If streaming overhead still fails SC-010, raise it as a constitution-checked deviation; don't
  silently drop capture.

## R3. Capture with LiteLLM

- **Decision**: Ship a LiteLLM `CustomLogger` module, `gcattr_litellm`, loaded through `litellm_settings.callbacks`
  in a pinned LiteLLM 1.105.1 image.
  - It reads the reassembled response in `async_log_success_event` and in the failure and partial paths.
  - It passes the response to the library's LiteLLM adapter, which produces the same `CapturedToolOutput` records
    as the stream parser.
  - Fingerprinting happens in-process. Only fingerprints are published.
- **Rationale**: the probe showed byte-exact reassembled arguments for Chat Completions, Responses (including
  freeform `apply_patch`), Anthropic Messages (translated to the OpenAI shape) and Gemini through the
  OpenAI-format route. Truncated calls arrive as invalid JSON with `finish_reason: length`.
- **Settings**: LiteLLM must not store prompts or responses anywhere (Constitution II): `turn_off_message_logging:
  true`, spend logs without message content, and no other logging callbacks.
- **Alternatives considered**:
  - Parsing LiteLLM's outgoing stream through `async_post_call_streaming_iterator_hook`: it gives the
    client-facing format, but chunk types vary by route and the probe didn't cover it. It's kept as a fallback
    for routes where the success callback lacks tool calls.
- **Packaging finding (implementation, 2026-10-14)**: the upstream `ghcr.io/berriai/litellm:v1.105.1` image runs
  **Python 3.13 / Unicode 15.1.0**. `gcattr` alg 1 pins CPython 3.12 / Unicode 15.0.0 (R8) and refuses to fingerprint
  under any other version, so capture inside the upstream image would fail every time. The stack therefore builds
  its own `gca-litellm` image on the same pinned `python:3.12-slim` base, with `litellm[proxy]==1.105.1` from PyPI
  (the version the probe ran on Python 3.12) and the Prisma client generated at build time. Relaxing the pin to
  accept 15.1.0 was rejected: tokenization of characters newly assigned in 15.1 could differ between gateways,
  which would break FR-006 parity.
- **Validate**:
  - Gemini CLI's native `streamGenerateContent` through LiteLLM's `/gemini` pass-through route (untested in the
    probe).
  - The self-built `gca-litellm` image starts the proxy with virtual keys against Postgres (Prisma client generated
    at build).

  **Fallback**: report that combination as **not observed** (FR-007) until it's resolved.

## R4. Parity between the two gateways

- **Decision**: Both capture paths finish in one library function, `gcattr.capture.extract(...)`, which turns a
  `CapturedToolOutput` into normalized, fingerprinted lines. Parity is enforced by a **cross-gateway conformance
  suite** in `tests/conformance/`. It replays the same recorded streams through each gateway against the same mock
  upstream and asserts identical fingerprint multisets per capture event (FR-006, SC-007).
- **Rationale**: Constitution IV requires identical results, checked by a shared suite. Converging on one
  intermediate record means only the two small adapters differ.
- **Alternatives considered**: comparing at the attribution-outcome level only. That's too late to locate a
  divergence.

## R5. Developer gateway credentials

- **Decision**: Opaque personal API keys (`gca_…`, 32 random bytes) issued by the portal when a developer signs in
  with GitHub (FR-016). Keys are stored only as SHA-256 hashes.
  - **agentgateway**: the portal renders `llm.policies.apiKey.keys[]` entries (`keyHash: sha256:…`,
    `metadata: {github_id, github_login, credential_id}`) into the gateway's config file and triggers a reload. A
    CEL `location.expression` accepts the key from `Authorization: Bearer`, `x-api-key` or `x-goog-api-key`, so
    every in-scope tool works unchanged.
  - **LiteLLM**: the portal creates virtual keys through LiteLLM's key-management API with `user_id` set to the
    GitHub id. That is open source and needs no enterprise feature.
  - **Revocation**: removing the key revokes it, which stops future capture under it (FR-016).
- **Rationale**: one credential model for developers, with immediate revocation and no paid features. JWTs were
  rejected because long-lived static tokens can't be revoked without a deny-list, and LiteLLM's JWT auth is an
  enterprise feature.
- **Validate**: agentgateway standalone picks up config changes without dropping in-flight streams.

  **Fallback**: run agentgateway in its Kubernetes controller mode and manage keys as resources, or use
  `extAuthz` against the portal, accepting a dependency on the portal's availability for auth only.

## R6. How each in-scope coding tool reaches the gateway

| Tool | Endpoint setting | Credential carried as |
|---|---|---|
| Claude Code | `ANTHROPIC_BASE_URL` | `ANTHROPIC_AUTH_TOKEN` → `Authorization: Bearer` |
| Codex CLI | `~/.codex/config.toml` `model_providers.<name>.base_url`, `wire_api = "responses"` | `env_key` → `Authorization: Bearer` (a logged-in ChatGPT session overrides it, so run `codex logout`) |
| Gemini CLI | `GOOGLE_GEMINI_BASE_URL` | `GEMINI_API_KEY` → `x-goog-api-key` (or Bearer with `GEMINI_API_KEY_AUTH_MECHANISM=bearer`) |
| OpenCode | provider `baseURL` in `opencode.json` | provider `apiKey` → header used by that provider |

- **Session IDs**: the tool's session header is captured when present (`x-claude-code-session-id`,
  `x-opencode-session-id`). Matching never relies on it (FR-012 uses identity and time window).
- **Validate**: record real traffic from each tool through each gateway for the evaluation corpus (FR-045). This
  also confirms Codex's freeform `apply_patch` and the full set of Claude Code edit tools.
  - **Status for v1 (2026-10-16)**: Claude Code is recorded (eval/corpus/claude-code) and confirms its edit tools:
    `Write` and `Edit`, including `replace_all`. Recording Codex CLI, Gemini CLI and OpenCode is deferred past v1,
    so Codex's freeform `apply_patch` is confirmed only by scripted sessions and the probe in the assessment, not
    by real traffic.

## R7. Extracting code from model output

- **Decision**: The library extracts candidate code lines from:
  1. structured tool-call arguments, using the string-valued fields of known edit and write tools (`content`,
     `new_string`, `new_str`, `edits[].new_string`, `patch`, and so on). File paths come from `file_path` or
     `path` when present;
  2. freeform tool input in patch format: only the `+` lines of `*** Begin Patch` hunks, and the `+++` target
     path;
  3. any other string value in tool arguments, and fenced code blocks in assistant text, as **pathless** lines.

  Tool-specific field knowledge lives in a versioned table inside the library. An unknown tool falls back to
  rule 3, so a new tool degrades to pathless capture rather than none.
- **Rationale**: the assessment favoured "fingerprint everything code-bearing" to avoid parsing each tool's
  schema. Paths sharpen anchoring when they're available. Removed lines (`-`) in patches are never captured as
  model output.
- **Alternatives considered**:
  - Rule 3 only: loses paths and inflates candidates.
  - Full per-tool parsing only: brittle as tools change.

## R8. Normalization and the exact tier

- **Decision**:
  1. Decode as UTF-8 and apply **NFC**.
  2. Strip any BOM, and convert `\r\n` and `\r` to `\n`.
  3. Tokenize with a **language-agnostic lexer**: identifiers, numbers, string literals (quote character
     preserved), and single-character punctuation and operators. Whitespace is dropped.
  4. The exact fingerprint is `HMAC-SHA256(key_gen, "v{alg}\x1f" + tokens joined by U+0020)`, truncated to 128
     bits.
- **Rationale**: removing whitespace between tokens makes indentation, spacing and trailing-space changes from
  formatters match exactly, which helps M2. Keyed HMAC is required by Constitution II.
- **Unicode determinism**: `unicodedata` behaviour depends on the Python build's Unicode version. Each algorithm
  version records the Unicode version it was calibrated with, and the library **refuses to fingerprint** under a
  different one. This enforces FR-033 and SC-008 explicitly rather than hoping for it.
- **Alternatives considered**:
  - Trimming only (spec 002 style): fails on internal whitespace changes.
  - Language-aware parsers: too much per-language work, and they break on partial lines.

## R9. Similarity fingerprint (anchored and broad tiers)

- **Decision**: For each non-trivial line:
  - **Shingles**: token 2-grams (the whole token list for lines of up to 3 tokens), each keyed through HMAC.
    *Changed from 3-grams during implementation (T109): on the scenario set, one changed token on a 6-10 token
    line left a 3-gram similarity of 0.25-0.45, below any safe threshold; with 2-grams it's 0.50-0.65, while
    unrelated look-alike lines stay mostly under 0.30.*
  - **Quote style**: single- and double-quoted string literals are the same token, so a formatter switching
    quotes changes no fingerprint (R8 normalization; T109).
  - **Signature**: a **MinHash signature of 128 × 32-bit values**, built from 128 keyed hash seeds derived from
    the key generation. *Was 32 until T109: with 32, a line's estimated similarity varies by about ±0.18 (2
    standard deviations) between keys, so a common edit near a threshold (one identifier renamed on a 7-token
    line, true similarity 0.50) came out AI modified under some keys and human under others: the same edit
    scored differently per installation and across a key rotation. 128 values narrow that to about ±0.09. It
    costs about 17% more storage per captured line and 2.7 times the message size, reduced by sending the
    signature as packed binary (contracts/capture-event.schema.json v2).*
  - **Lookup index for the broad tier**: **LSH bands**, 8 bands of 4 rows, over the **first 32** signature
    values. The bands only find candidates; the whole signature decides similarity. Banding all 128 values would
    multiply the band rows (about 75% of the bytes per captured line) by four.
  - **Similarity**: the estimated Jaccard similarity of the two signatures.
  - **Starting thresholds**, before calibration: anchored ≥ 0.50, broad ≥ 0.75. They're calibrated against the
    scenario set to meet SC-003 and frozen into the algorithm version. *Now anchored ≥ 0.35 (T109): the
    highest value at which a one-identifier rename of a short AI line (true similarity 0.50) is AI modified
    under at least 99% of keys. An outcome must depend on the code, not on the key, so calibration only
    considers key-stable anchored thresholds.* **Frozen by T113 at anchored 0.35, broad 0.75**, calibrated on the
    scenario set plus the Claude Code corpus and scored under 50 fingerprint keys (plan.md, "Threshold
    margins").
- **What it reveals** (the documented assessment Constitution II requires):
  - Without the key, signatures can't be computed or compared. They're keyed hashes, and they resist dictionary
    attacks.
  - A key holder can compare a guessed line against stored signatures, which is the same exposure as the exact
    tier. A key holder can also estimate the similarity between two stored lines.
  - Lines under 3 tokens are already **indeterminate** and get no signature, which removes the most guessable
    content.
  - Residual risk: an operator with the key can confirm guesses about short lines. This is documented in
    `docs/privacy.md`, and key access is limited to the capture, ingest and PR-check services.
- **Alternatives considered**:
  - TLSH: needs about 50 bytes or more of input, so it's unusable on single lines.
  - SimHash: weaker on short, sparse token sets.
  - Storing normalized tokens: violates Constitution II.
  - Tree edit distance (TensorZero): needs code on both sides.

## R10. Trivial and common lines (indeterminate)

- **Decision**: A line is indeterminate if any of these apply:
  - it has fewer than 3 tokens after normalization;
  - it has no identifier, number or string token;
  - its normalized token string is in the library's versioned **common-lines list**, seeded from a frequency
    count over permissively licensed open-source code (for example `return;`, `else {`, `import os`, `} else {`,
    `pass`).

  Indeterminate lines are counted separately and left out of percentages (FR-014).
- **Rationale**: the design review (handoff §4.4) and FR-011. The list is versioned with the algorithm.
- **Alternatives considered**: inheriting the neighbours' label. That's a guess, which Constitution I forbids.

## R11. Matching, scoping and multiset counting

- **Decision**: For each PR head:
  1. **Find the added lines** in `merge-base...head`, using GitHub's compare API for the PR check or `git diff`
     for the CLI. Apply the exclusion rules.
  2. **Credit each added line** to the author of the PR commit that introduced it (the per-line author within
     the PR range, by GitHub account), per FR-012.
  3. **Look up candidates**: captured lines for that author's gateway identity within the matching window (14
     days by default), using the algorithm version and key generation of each capture (FR-034).
  4. **Tier 1, exact**: a multiset match on the exact fingerprint. Each captured occurrence is used at most once
     (FR-013).
  5. **Tier 2, anchored**: for unmatched lines in file F, the candidates are the lines of capture events that
     produced **at least one exact match in F** (spec FR-010). If such a capture event's tool call names a file
     path, its path suffix fingerprints must also match F. That stops anchoring across files when one tool call
     wrote several files. A path match **without** an exact match is not an anchor; those lines go to tier 3. If
     similarity reaches the anchored threshold → AI modified, high confidence.
  6. **Tier 3, broad**: for lines still unmatched, look up the author's LSH bands within the window, then confirm
     with MinHash similarity at or above the broad threshold → AI modified, lower confidence.
  7. **Tier 4, wrapped** *(added during implementation, T109)*: a formatter often splits one AI line over several
     (a wrapped call, a dict literal, a method chain), and a fragment of a long line is too dissimilar to the whole
     line to match on its own. Runs of consecutive added lines still unmatched in a file (trivial lines like `{`
     may sit inside) are joined and matched as one line, exact or by similarity, against the same author's
     candidates (anchored threshold if the matching capture event anchors the file, else broad). Every
     non-trivial line of a matching run is AI modified. Windows are 2-8 lines, largest first.
  8. **Tier 5, split** *(added during implementation, T109)*: when a formatter splits a line, the main part can
     match by similarity on its own (anchored or broad), leaving a short fragment unmatched (`if missing:` above
     its `raise`, one `.filter(...)` link of a chain). An unmatched or trivial fragment directly above or below
     lines that matched candidate *c* by similarity joins them when the joined text's MinHash similarity to *c* is
     **higher** than theirs alone; the fragment gets their tier. Up to 8 lines in all. This needs no new
     fingerprint: adding shingles that aren't in *c* can never raise a MinHash estimate, so only text that was in
     the AI line can join it.
  9. **Classify the rest**: indeterminate (R10) or human. Lines credited to unmapped authors are not observed
     (FR-015).
- **How step 2 gets each line's author without cloning**: the PR check uses GitHub's GraphQL `blame` on the head
  commit for each changed file. A line whose blame commit is in the PR's commit set is credited to that commit's
  author (by GitHub account). Added-line content comes from the compare API's patch, is held in memory only, and
  is discarded after fingerprinting (Constitution II). The local CLI and the evaluation harness use `git blame`
  over the PR range on a temporary, memory-backed checkout.
- **Rationale**: this implements FR-010 to FR-015 directly, and confines the broad search to one author's window,
  which keeps the candidate set small at SC-013 scale.

## R12. Detecting capture loss and gating on timing

- **Decision**:
  - Every capture instance has a random instance ID and a **monotonic sequence number** on each message. It
    sends a **heartbeat** every 5 seconds carrying its latest sequence number and the gateway's processed
    response count.
  - Ingest records gaps in a sequence, heartbeats that stop, and capture failures the instance reports itself
    (truncated, unreadable, unexpected format) as `CaptureLoss` rows with a cause.
  - **Watermark**: the oldest last-heartbeat time across active instances.
  - **Pending**: a PR head waits until the watermark passes the time the PR event was received, for at most 10
    minutes. After that it completes with **incomplete coverage** (FR-017, FR-022).
- **Rationale**: this catches loss even when a capture process crashes and loses its own counters. It's required
  for "zero silent capture loss" (SC-005).
- **Alternatives considered**: counters held in each process only. They're lost on a crash, which would be silent
  loss.

## R13. Ingest buffering (the queue)

- **Decision**: NATS JetStream, using nats-server 2.15.1 and the official `nats-io/k8s` Helm chart (Apache-2.0).
  It runs as a single-node file-backed stream, `GCA_CAPTURE`, with work-queue retention.
  - Capture publishes **fingerprint-only** messages (schema:
    [contracts/capture-event.schema.json](./contracts/capture-event.schema.json)).
  - If NATS is unreachable, each capture instance buffers up to 10,000 messages in memory. Overflow counts as
    loss, with cause `buffer_overflow`.
- **Rationale**: the owner asked for a queue. NATS is light, Apache-2.0 and maintained, with an official chart and
  no Bitnami dependency. JetStream gives durable acknowledgement.
- **Alternatives considered**:
  - Kafka: heavy for a reference stack.
  - Redis Streams: Redis's licensing changed. Valkey would work but adds little over NATS here.
  - Postgres as a queue: couples write load to query load.

## R14. Storage

- **Decision**:
  - **PostgreSQL 17**, using the official `postgres:17` image in a single-replica StatefulSet rendered by our
    chart. Adopters can choose an external Postgres instead.
  - The `captured_line` table is partitioned by day, with retention of 90 days by default, enforced by dropping
    whole partitions.
  - Indexes:
    - `(developer_id, exact_fp, captured_at)` for the exact tier;
    - `(capture_event_id, tool_call_ordinal, line_ordinal, captured_at)` (unique) for the anchored tier;
    - a GIN index on `(developer_id, bands)` for the broad tier: the 8 band hashes are a column of the line
      (migration 0007). They were a separate `lsh_band` table with a row per band until T115 measured it.
  - Migrations use Alembic.
- **Sizing estimate (assumption, to validate)**: 500 developers × 2,000 captured non-trivial lines per day × 90
  days ≈ 90M lines. At about 230 bytes per line (16-byte exact fingerprint, 128-byte signature, 8 band hashes,
  metadata) plus indexes, that's about 30–40 GB. The chart defaults to a 100 Gi volume and documents sizing
  (SC-013).
  *Measured (T115, PostgreSQL 17, real tables and indexes): about 2,650 bytes per line with 128-value signatures
  and band rows, about 241 GB at 90M lines. The 230-byte estimate left out PostgreSQL's per-row and per-index
  overhead, which the 8 band rows multiplied. With the bands inline (migration 0007) it's 1,464 bytes per line,
  about 123 GiB of fingerprints at 90M lines, so the default volume is now 200 Gi; see docs/sizing.md.*
- **Rationale**: one relational store serves exact lookups, the anchored joins, LSH candidate lookups and the
  dashboards. The official image avoids Bitnami (Constitution VI).
- **Alternatives considered**:
  - The CloudNativePG operator: needs cluster-scoped CRDs and operator install, and adds HA we don't need in v1.
    It's documented as the production path.
  - ClickHouse: overkill at this scale.

## R15. Dashboards and per-developer access

- **Decision**:
  - **Grafana OSS 13.2.4**, from the `grafana-community/helm-charts` chart, holds the aggregate dashboards: per
    change, per repository, team totals, and coverage. It reads a read-only Postgres role through **SQL views
    that contain no per-developer columns**.
  - Viewers sign in to Grafana with GitHub OAuth, limited to the adopter's organization.
  - **Per-developer drill-down lives in the portal** (FR-029, FR-029a). The portal enforces the
    admin / team-lead / other roles taken from GitHub (organization owners; team maintainers for their team only),
    with admin overrides.
- **Rationale**: the owner asked for Grafana. Grafana OSS has no row-level security, so per-developer data stays
  out of it entirely rather than relying on dashboard variables that can be tampered with. Grafana is AGPL-3.0 but
  is deployed as an unmodified, separate service, so it's compatible with an Apache-2.0 project.
- **Alternatives considered**:
  - Per-team Grafana folders: variables can be overridden through the URL, so it isn't access control.
  - Building every view in the portal: discards the owner's Grafana requirement and adds front-end work.

## R16. PR check (GitHub App)

- **Decision**: One GitHub App per install, which provides both the check and GitHub sign-in (user-to-server
  OAuth). It's created with a **manifest flow** by `gca setup github-app`.
  - **Events**: `pull_request` (opened, synchronize, reopened, closed), `check_run` (rerequested), `installation`,
    `membership`, `team`, `organization`.
  - **Permissions** (minimum; reasons are in [contracts/github-app.md](./contracts/github-app.md)): Checks:
    write, Pull requests: read, Contents: read, Metadata: read, Members: read.
  - **Event delivery**: webhooks when the install has a public URL, and **polling mode** (every 30 seconds) for
    local demos without one. Either way the event handling is idempotent (FR-020).
  - **Check output**: the outcome counts table, coverage status, excluded paths, and algorithm version.
    Annotations group runs of AI lines into ranges, and the full per-line view is in the portal.
  - **Conclusion**: always `neutral` (informational; FR-025).
- **Rationale**: one app, least privilege, and it works on a laptop without exposing a public endpoint.
- **Alternatives considered**:
  - A GitHub Action: it would run in each repo's CI and need the fingerprint key there, which breaks key custody.
  - smee.io as the only route for local delivery: a third-party relay.

## R17. Packaging and install

- **Decision**: One Helm chart, `charts/gateway-code-attribution`, with `gateway.type: agentgateway | litellm`.
  - **agentgateway 1.6.0**: runs in **standalone mode** from our templates (config in a ConfigMap), so no
    Gateway API CRDs or controller are needed.
  - **LiteLLM 1.105.1**: rendered from **our own templates**. Its upstream chart depends on Bitnami
    `postgresql` and `redis` charts, which Constitution VI rules out.
  - **Dependencies**: Postgres (our template, official image), NATS (official chart) and Grafana (community
    chart).
  - **Pinning**: every image is pinned by version and digest.
  - **Secrets**: generated at install (FR-035, constitution Security): the fingerprint key, Postgres passwords
    and portal session keys, created with `lookup` + random generation so they persist across upgrades, or
    supplied by the adopter. GitHub App credentials always come from the adopter.
  - **Local path**: `make demo` creates a kind cluster and installs with demo values.
- **Rationale**: this delivers FR-037 and SC-001, and avoids Bitnami and controller sprawl.

## R18. Demo traffic

- **Decision**: Two demo components, enabled with `demo.enabled: true`.
  1. **`demo-model`**: a mock upstream provider. It streams recorded and synthetic responses in the real OpenAI
     Chat, Responses, Anthropic Messages and Gemini formats, chunked to split lines and UTF-8 characters, as the
     probe's `mock_upstream.py` did. In demo mode, the gateway routes the demo model names to it.
  2. **`demo-agent`**: a scripted client that acts as each in-scope tool. It sends requests **through the
     gateway** with the adopter's own personal credential, applies the returned edits to a clone of the sample
     repository, then makes scripted human edits and a formatter pass. It commits as the adopter, pushes a
     branch, and opens the demonstration PR (using the adopter's `gh` login).

  Results come only from the real capture and PR-check path (FR-038).
- **Rationale**: no model or key is needed, the real path is exercised, and all four outcomes and both similarity
  tiers appear. Using the adopter's own GitHub identity makes identity mapping work with no fake accounts.
- **BYO hosted key mode**: the adopter puts provider keys in a Secret. Gateway routes then point to the real
  providers, and they use the real tools (FR-039).

## R19. Scenario set, evaluation and release bar

- **Decision**: `eval/scenarios/` holds labelled scenarios. Each is a git repo recipe, model-output streams per
  API, and an answer key per line.
  - **Seed**: the spec 002 set (59 lines, 30 history-rewrite lines).
  - **Extended with**: human edits of AI lines, formatter passes (Prettier, Black, gofmt), refactors, unrelated
    code that resembles AI output, multi-author PRs, truncation and fault injection, and recorded real traffic
    per tool (FR-045).
  - **Harness**: `gca eval` runs each scenario through **each gateway**, started locally as processes (pinned
    binaries and images, as in the probe), with the mock upstream. It then attributes with the same engine as the
    PR check, and writes a quality report (schema:
    [contracts/quality-report.schema.json](./contracts/quality-report.schema.json)).
  - **CI release gate**: fails on any release-bar miss (SC-002, SC-003) or any silent loss (FR-044).
  - **Recording real traffic** (constitution II, v1.0.1): recording is done by a **standalone developer tool**,
    `eval/corpus/record.py`. It's a local recording proxy that the consenting owner runs between their coding tool
    and the gateway. It's never part of a service image or the chart, so the deployed system has no code path that
    persists content. Only synthetic tasks run by consenting owners are recorded, each with a `consent.yaml`.
- **Rationale**: Constitution V, and it's measurable without GitHub.

## R20. Testing approach

- **Decision**:
  - **Unit**: pytest, plus Hypothesis property tests for determinism (normalization, fingerprinting and
    matching are pure functions).
  - **Golden files**: fingerprints of a fixed corpus are pinned per algorithm version.
  - **Conformance** (R4).
  - **Privacy audit**: after a demo run, scan Postgres, NATS, logs and traces for fixture code strings, expecting
    zero (SC-006).
  - **End to end**: on kind, the quickstart run, timed for SC-001.
  - **Performance**: with k6 or Locust, replay 500-developer traffic through each gateway with and without
    capture, for SC-009, SC-010 and SC-013.
- **Rationale**: these map one-to-one to the constitution's quality gates.

## R21. Library release

- **Decision**:
  - The library `gcattr` is published from `lib/` to **GitHub Releases**, as a wheel and sdist with
    `SHA256SUMS`, and to **PyPI**, with **Sigstore/PyPI attestations** (SHOULD in the constitution).
  - It uses semantic versioning. The **algorithm version** (`alg`) is a separate integer recorded on every
    fingerprint and result. Any change that alters a fingerprint or outcome bumps `alg` and is at least a minor
    library release.
  - Container images and the Helm chart are released from the same tag, with checksums.
- **Rationale**: the owner asked for a versioned release on GitHub. PyPI makes reuse practical (Story 5).

## Resolved Technical Context unknowns

All plan Technical Context items now have decisions:
- language: R1;
- dependencies: R2, R3, R13–R17;
- storage: R14;
- testing: R20;
- platform: R17;
- performance and scale: R12, R14, R20.

There are no remaining NEEDS CLARIFICATION items. Items marked **Validate** have fallbacks and become explicit
tasks.
