# Implementation Plan: Gateway Code Attribution Reference Stack

**Branch**: `001-gateway-code-attribution` (spec directory; work on `claude/speckit-assess-intake-b6c123`) |
**Date**: 2026-10-14 | **Spec**: [spec.md](./spec.md)

***Input**: Feature specification from `specs/001-gateway-code-attribution/spec.md`

## Summary

Build an open-source reference stack, installed with one Helm chart, that attributes the lines added in each
GitHub pull request using fingerprints of the model output captured at an AI gateway.

**Capture.** The adopter picks **agentgateway 1.6.0** or **LiteLLM 1.105.1**.
- On agentgateway, an external-processing service sees the client-facing response stream (fail open).
- On LiteLLM, a `CustomLogger` callback sees the reassembled response.

Both pass the output to one Python library, **`gcattr`**. It extracts code lines from tool calls, freeform patches
and code blocks, and holds content in memory only. From that it computes keyed exact fingerprints (HMAC-SHA256)
and keyed MinHash similarity signatures, and publishes **fingerprints only** to NATS JetStream. Ingest writes them
to PostgreSQL and detects capture loss from sequence gaps and missing heartbeats.

**PR check.** A **GitHub App** attributes every added line in the PR's `merge-base...head`, using the same library:
- each line is credited to the author of the PR commit that added it;
- it's matched only against that author's captured output, in three tiers: exact, anchored similarity, broad
  similarity;
- it's given one of four outcomes: `AI, unmodified`; `AI, modified` (anchored, high confidence, or broad, lower
  confidence); `Human`; `Indeterminate`. Lines credited to an author with no gateway identity get the separate
  state `Not observed`, which isn't an outcome and is never counted in percentages.

**Reporting.**
- **Grafana** shows aggregates per change, per repository and per team, plus coverage.
- A **portal** handles GitHub sign-in, issues personal gateway credentials, enforces role-based per-developer
  drill-down, and shows per-line results.

**Demo and quality.** A keyless demo (a mock upstream model plus a scripted agent) exercises the real path. A
scenario-set evaluation harness enforces the release bar in CI.

Decisions and rationale: [research.md](./research.md).

## Technical Context

**Language/Version**: Python 3.12 for all components, in one uv workspace (R1). Helm chart and Kubernetes
manifests; Grafana dashboards as JSON.

**Primary Dependencies**:
- agentgateway 1.6.0 (standalone mode, `extProc`, `apiKey`) and LiteLLM 1.105.1 (OSS proxy, `CustomLogger`,
  virtual keys);
- grpcio and Envoy `ext_proc` v3 protos (the capture-extproc service);
- FastAPI and Jinja2 (portal, PR-check webhooks);
- githubkit (GitHub REST and GraphQL, App auth);
- nats-py (JetStream);
- SQLAlchemy 2 + Alembic + psycopg 3;
- Grafana OSS 13.2.4 (community Helm chart);
- NATS server 2.15.1 (official Helm chart);
- PostgreSQL 17 (official image).

**Storage**: PostgreSQL 17. `captured_line` is partitioned by day with 90-day retention by default. Also NATS
JetStream as a file-backed work queue (R13, R14).

**Testing**:
- pytest and Hypothesis (unit and determinism property tests);
- golden fingerprint corpus for each algorithm version;
- cross-gateway conformance suite (`tests/conformance/`);
- testcontainers (Postgres, NATS) for integration;
- end to end on kind;
- privacy audit (SC-006);
- performance with Locust (SC-009, SC-010, SC-013);
- scenario-set evaluation (`gca eval`) as the release gate (R19, R20).

**Target Platform**: Kubernetes ≥ 1.30 on Linux nodes (amd64 and arm64); kind for local and demo use. The library
supports Linux and macOS with CPython 3.12.

**Project Type**: a multi-service web application (gateway capture, ingest, PR check, portal), a reusable
library with a CLI, and a Helm chart.

**Performance Goals**:
- PR check result within 2 minutes for PRs of up to 1,000 added lines (SC-009);
- capture overhead ≤ 5% at p95 on response completion time (SC-010);
- all at a 500-active-developer load (SC-013).

**Constraints**:
- **Fail open:** capture never blocks or delays a model response beyond SC-010 (FR-005a).
- **No content at rest:** no code or prompt text in any storage, log, trace, metric or queue (Constitution II).
- **Deterministic:** identical output for the same algorithm version, with the Unicode version pinned (R8).
- **No paid tiers and no Bitnami** (Constitution IV, VI).
- **Images pinned** by digest.

**Scale/Scope**: up to 500 active developers per default install. That's about 90M captured lines over 90 days,
roughly 30–40 GB of Postgres (R14). In-scope tools: Claude Code, Codex CLI, Gemini CLI, OpenCode. Forge:
GitHub.com and Enterprise Cloud.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.* Constitution v1.0.1 (amended from
v1.0.0 for note N1; no gate results changed).

| Principle / section | Gate | Pre-research | Post-design |
|---|---|---|---|
| **I. Never Guess** | 4 outcomes + not observed; confidence on AI modified; broad separable; no AI without a capture match; loss counted | PASS (spec FR-009–FR-015, FR-028) | PASS. R10/R11 tiering and fallbacks; R12 loss detection from sequence gaps and heartbeats; `line_result.tier` and `confidence` in data-model.md |
| **II. No Retained Code or Prompts** | Only keyed fingerprints and metadata; nothing in logs, traces or queues; similarity leakage assessed | PASS (FR-003, FR-004) | PASS with **two design obligations**: (a) capture uses `extProc` rather than CEL logging of tool calls (R2), and LiteLLM message logging is off (R3); (b) the PR check fingerprints compare-API patches in memory and gets authors from GraphQL blame (no clone); the CLI uses memory-backed checkouts (R11). R9 documents similarity leakage. ⚠ See note N1. |
| **III. One Shared, Versioned Library** | Every component uses `gcattr`; `alg` recorded everywhere; determinism test | PASS (FR-031–FR-034) | PASS. Both capture adapters, the PR check, the CLI and eval import `gcattr`. Unicode version pinned per `alg` (R8). Golden corpus per `alg` (R20). |
| **IV. Vendor and Gateway Neutrality** | No per-machine or per-tool install; identical results across gateways; no paid tiers; Apache-2.0 | PASS (FR-001, FR-006, SC-011) | PASS. Conformance suite (R4); LiteLLM virtual keys and callbacks are OSS, and JWT auth (enterprise) is avoided (R5). Grafana (AGPL) runs as a separate, unmodified service (R15). The agentgateway native-Gemini gap is closed by parsing the raw stream (R2). |
| **V. Measure Before Claiming** | Published scenario set; release bar; probe vendor behaviour | PASS (FR-042–FR-045, SC-002, SC-003) | PASS. `gca eval` and the CI release gate (R19). Validation tasks for unproven vendor behaviour: R2 overhead, R3 Gemini via LiteLLM, R5 agentgateway reload, R6 real traffic per tool. |
| **VI. Out of the Box, Reproducibly** | One install; keyless demo through the real path; pinned versions; no deprecated or paywalled deps; time to first result measured | PASS (FR-037–FR-039, SC-001) | PASS. One chart; own templates for LiteLLM and Postgres to avoid Bitnami (R17); `demo-model` and `demo-agent` (R18); e2e measures SC-001. |
| **VII. Scope Discipline** | No Option C items | PASS | PASS. No third gateway, developer-side hook, signing, Agent Trace export, other forge or HA. CloudNativePG is documented only as a production path. |
| Security & Data Handling | Keys generated or supplied at install and rotatable; least-privilege App; per-developer access control; US statement; checksums | PASS (FR-016, FR-023, FR-029, FR-029a, FR-035, FR-036) | PASS. Key generations (data-model.md); App permissions with reasons ([contracts/github-app.md](./contracts/github-app.md)); portal role enforcement; `SHA256SUMS` + attestations (R21). |
| Development Workflow & Quality Gates | Determinism and scenario gates; conformance gate; data-path audit; clean-install gate; real traffic before support | PASS | PASS. Each maps to a CI job in R20 and quickstart.md. |

**N1 (resolved by constitution v1.0.1):** Principle II's "demo data" rule now covers data the system produces or
stores, and exempts authored synthetic inputs (demo fixtures, the sample repository, the scenario set). The design
already complied: the demo's fixtures contain synthetic code by design, and SC-006's audit checks that nothing the
system produces or stores contains code. Under v1.0.1, the recorded real-traffic corpus (`eval/corpus/`) must come
from consenting owners.

**Gate result: PASS.** No unjustified violations; Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-gateway-code-attribution/
├── plan.md              # This file
├── research.md          # Phase 0 decisions (R1–R21)
├── data-model.md        # Phase 1 entities, fields, states, validation
├── quickstart.md        # Phase 1 runnable validation guide
├── contracts/           # Phase 1 interface contracts
│   ├── library-api.md
│   ├── capture-event.schema.json
│   ├── gateway-capture.md
│   ├── github-app.md
│   ├── portal-http.md
│   ├── helm-values.md
│   └── quality-report.schema.json
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks; not created here)
```

### Source Code (repository root)

```text
lib/                              # gcattr: the single, versioned matching library (Constitution III)
├── pyproject.toml
├── src/gcattr/
│   ├── algorithm.py              # alg version, pinned Unicode version, thresholds, common-lines list version
│   ├── normalize.py              # NFC, line endings, BOM
│   ├── lexer.py                  # language-agnostic tokenizer
│   ├── fingerprint.py            # keyed exact fingerprint (HMAC), key generations
│   ├── similarity.py             # keyed shingles, MinHash, LSH bands
│   ├── trivial.py                # indeterminate rules + versioned common-lines list
│   ├── streams/                  # raw SSE reassembly: openai_chat, openai_responses, anthropic, gemini
│   ├── adapters/litellm.py       # LiteLLM response objects → CapturedToolOutput
│   ├── extract.py                # CapturedToolOutput → code lines (+ path) per R7
│   ├── match.py                  # tiered, author-scoped, multiset matching (R11)
│   ├── classify.py               # outcomes, confidence, not observed
│   └── cli.py                    # `gca` CLI: fingerprint, attribute (local git), eval, setup
└── tests/                        # unit, property (Hypothesis), golden corpus per alg

services/
├── core/                         # shared: config, DB models (SQLAlchemy), Alembic migrations, NATS client, roles
├── capture-extproc/              # agentgateway ext_proc gRPC server (pass-through + background capture)
├── capture-litellm/              # LiteLLM CustomLogger module + pinned LiteLLM image build
├── ingest/                       # JetStream consumer → Postgres; sequence/heartbeat loss detection; watermark
├── prcheck/                      # GitHub App: webhooks or polling, attribution worker, check runs
├── portal/                       # GitHub sign-in, credentials, overrides, roles, per-developer + per-line views
└── demo/                         # demo-model (mock upstream) + demo-agent (scripted tools + demo PR)

charts/gateway-code-attribution/  # single Helm chart: gateway choice, Postgres, NATS, Grafana, services, demo
  dashboards/                      # Grafana JSON (aggregate-only SQL views); inside the chart so Helm can read it

eval/
├── scenarios/                    # labelled scenario set (seeded from spec 002) + answer keys
├── corpus/                       # recorded real traffic per tool and API (fixtures; synthetic or consented)
└── harness/                      # runs each gateway locally + mock upstream → quality report

tests/
├── conformance/                  # cross-gateway parity (FR-006, SC-007)
├── privacy/                      # stored-data / log / trace audit (SC-006)
├── e2e/                          # kind install + demo + time-to-first-result (SC-001)
└── perf/                         # Locust: SC-009, SC-010, SC-013

docs/                             # install, per-tool routing, outcomes, privacy (R9), jurisdiction, sizing
```

**Structure Decision**:
- **Workspace**: one uv workspace with the library in `lib/` and one package per service under `services/`,
  sharing `services/core`.
- **Library publishing**: the library is versioned and released on its own (R21). Services pin an exact `gcattr`
  version, which is how the algorithm version deployed is controlled.
- **Repo-level folders**: the chart, dashboards, evaluation and cross-cutting tests live at the repository root,
  because they span services.

## Phase 0 and Phase 1 Outputs

- **Phase 0**: [research.md](./research.md). Decisions R1–R21, with every Technical Context unknown resolved.
  Items marked **Validate** become explicit tasks, each with a fallback.
- **Phase 1**:
  - [data-model.md](./data-model.md)
  - [contracts/](./contracts/), with seven contracts
  - [quickstart.md](./quickstart.md)
- **Agent context**: this Spec Kit install has no agent-context update script, so there's nothing to run.
  `CLAUDE.md` will be created in implementation if needed.

## Follow-ups (outside this plan)

- ~~Constitution PATCH (N1)~~: done in v1.0.1.
- **Validation tasks with fallbacks**, to be scheduled by `/speckit-tasks`:
  - R2: ext_proc overhead and failOpen;
  - R3: Gemini CLI through LiteLLM;
  - R5: agentgateway key reload;
  - R6: real traffic per tool;
  - R14: sizing.

## Implementation findings (recorded during /speckit-implement)

- **R2 validated with two liveness gaps** (`docs/validation/R2-extproc.md`). agentgateway 1.6.0's `failOpen`
  covers only requests that start after the processor fails. A processor that crashes mid-stream truncates
  in-flight responses, and a slow processor stalls them (there's no processor timeout). `extProc` is kept with
  mitigations (worker process, self-deadline, graceful drain, replicas). **Residual risk, accepted by the owner on
  2026-10-14:** responses in flight during a processor *crash* are cut short. This is narrower than FR-005a. It's
  documented in docs/coverage.md and reported upstream to agentgateway.
- **R5 validated** (`docs/validation/R5-key-reload.md`): about 13 s gateway reload, and about 2 minutes end to end
  with the ConfigMap sync.
- **LiteLLM image**: the upstream image runs Python 3.13 / Unicode 15.1.0, which `gcattr` alg 1 refuses (R8). The
  stack builds `gca-litellm` on `python:3.12-slim` (research R3 packaging finding).
- **Portal sessions** are opaque random ids held server-side (the GitHub token never leaves the portal process),
  so there is no cookie-signing secret. One portal replica; people sign in again after a restart.
- **Dashboards live in the chart** (`charts/gateway-code-attribution/dashboards/`): Helm can only read files
  inside a chart.
- **Grafana and the GitHub secret**: a subchart can't read the parent's `github.existingSecret`, so the Grafana
  values name the Secret directly and `validate.yaml` fails the install when the two disagree.
- **Grafana sign-in needs the user's email**: the App also requests the *Email addresses: read* account
  permission (contracts/github-app.md), and registers Grafana's callback URL next to the portal's.
- **First live install (kind, agentgateway, 2026-10-14)** found four defects that unit tests missed, all fixed with
  regression tests: (1) the capture ext_proc forked its worker pool after gRPC started, crashing the worker and
  wedging the process, so the gateway failed open and nothing was captured. Workers now `spawn`, start before
  gRPC, a broken pool is replaced and counted as loss, and a liveness probe answered from the event loop restarts
  a wedged process; (2) the portal couldn't create the live gateway config before migrations, which run after
  `helm --wait`: it now creates it with no keys, then re-syncs every 30 s; (3) githubkit's `.rest` holds only a
  weak reference to its client, and App JWTs need `githubkit[auth-app]`; (4) githubkit's web-flow exchange spends
  the one-time sign-in code before its own request, so the portal exchanges it with one direct request.
- **Open gap (FR-005, SC-005)**: when the gateway fails open because it can't reach a *healthy* capture service,
  heartbeats look normal and no loss is recorded. Detecting it needs a request count from the gateway itself
  (agentgateway metrics) compared with `responses_seen`. To be planned with US4 (T088). Losses from a stopped or
  wedged capture process are covered once T088 records missed heartbeats.
- **End-to-end test design (T065)**: credentials come from an operator command run inside the portal pod
  (`python -m gca_portal.admin_cli issue-credential`), since GitHub sign-in needs a browser; it needs exec access
  to the pod, so it grants nothing new. Before the second gateway runs, captured fingerprints are cleared: the
  demo code is identical across runs, so the second PR would otherwise match the first gateway's captures and the
  parity check would prove nothing (seen with PR #3). One CI job runs both gateways, then the privacy audit.
- **Demo "broad" case**: multiset matching (FR-013) lets an unchanged AI line consume its captured occurrence,
  so the demo shows a broad match by *moving* an AI-written method to another file and adapting it.
- **Team sync runs in the PR check (T082)**, which holds the App key and receives the `membership`, `team` and
  `organization` webhooks; the portal never gets the App key. Sync creates no developers: an account without a
  Developer row is unmapped and its lines stay not observed (FR-015), so only people who have signed in can be
  members. A developer's first membership row starts at their sign-in time (not at the next sync), so team
  totals count what they merged in between, and sync re-runs within a minute of a new sign-in.
- **Helm settings never reached the database** before US3: `attribution.*` and `perDeveloper.*` were rendered
  but `portal_settings` kept its column defaults. The migrations Job now applies them
  (`gca_core.bootstrap.apply_settings`), writing only values that changed since the chart last applied them
  (`portal_settings.helm_values`, migration 0004), so upgrades don't undo the settings page.
- **Capture outages (T088)**: a clean shutdown sends a `shutting_down` heartbeat, so scaling capture to zero
  recorded no loss at all, while the gateway failed open and nothing was captured. Ingest now opens a
  `heartbeat_missed` loss with no instance when no instance of the installed gateway (`GCA_GATEWAY_TYPE`) has
  been active for 15 seconds; rolling updates keep one replica up and don't trigger it. A stale instance's loss
  also closes when a replacement instance starts, since a crashed process never resumes under its old ID.
- **Loss accounting is exact under redelivery (T088)**: sequence numbers are assigned only on a successful
  publish, so a gap is real loss; a late message splits its gap row (`seq_first`/`seq_last`), and failure
  reports are deduplicated by `source_seq`. Before this, a redelivered failure report was counted twice.
- **Coverage views (T091)** are three views rather than one: `v_coverage_daily` (loss), `v_capture_daily`
  (observed combinations, with `alg`) and `v_unmapped_daily` (counts only). The portal lists unmapped accounts to
  admins only, looking logins up with the admin's own token; only account IDs are stored.
- **Unsupported routes (T090)**: the agentgateway processor now reports a model route it can't read (for example
  legacy `/v1/completions`) as `unsupported_combination` instead of dropping it; routes that can't carry code
  (models, embeddings, token counting, audio, images, files) are ignored. LiteLLM capture now records the tool
  from the request headers LiteLLM passes to callbacks.
- **Fault injection (T092, T093)**: `gca demo run --inject-faults truncated=N,unexpected_format=M [--faults-only]`.
  The Responses parser is lenient, so `response.completed` missing `created_at` alone isn't a fault for it; the
  injected event also loses its `type`, which is. The capture processor has two test-only delays,
  `GCA_CAPTURE_TEST_PARSE_DELAY_SECONDS` and `GCA_CAPTURE_TEST_ECHO_DELAY_SECONDS` (0 by default). Per R2 there's no
  gateway timeout on the echo path, so T093(d) checks that a slow echo still completes, not that it's cut off.
- **One reading of a change (T096)**: the diff parser and exclusion globs moved from the PR check into
  `gcattr.diff`, and the per-response fingerprinting loop (tool-call numbering) into `gcattr.io`, used by both
  capture adapters and `gca fingerprint`. `gca attribute` therefore reads a local range exactly as the PR check
  reads a PR; T097 confirmed it line for line on a live demo PR (93 lines). One known difference: when GitHub's
  compare API omits a large file's patch, the PR check rebuilds it from both blobs with `difflib`, while
  `gca attribute` always uses git's diff, so the two can number added lines differently for those files only.
- **Golden corpus (T094, T095)**: inputs are frozen inside `lib/tests/golden/alg-<n>/inputs`, so later fixture
  edits can't move the expected outputs; `.gitattributes` keeps those files byte-exact. `check-alg-bump.sh` allows
  exactly one exception to "never change a corpus": the first corpus for the current `ALG`. The contract's
  defaults `alg=ALG` on `attribute()` and `extract()` were missing and are now in place.
- **Eval runner (T106)**: both real gateways run locally through `gca_eval.gateways` (the conformance harness now
  uses the same module). Captured messages go through ingest's real store into a testcontainers PostgreSQL in
  publication order; NATS is only transport, so it isn't run, and a `dropped` fault removes one message there.
  Lines are read with `gcattr.gitlocal` (shown equal to the PR check in T097) and matched with the PR check's own
  `match_lines`. Each (scenario, alias) gets its own test account, so scenarios can't match each other.
- **Silent loss found on LiteLLM (T106)**: given a schema-deviant Responses stream, LiteLLM 1.105.1 ends the
  client's response mid-stream and calls only the failure callback, which capture ignored: silent loss. The
  callback now records `unexpected_format` for a generative call that fails after the provider accepted it (not a
  4xx refusal), because output may already have reached the developer.
- **First quality measurements (T107, T109)**: 16 scenarios, 246 labelled lines. No line was wrongly called AI
  modified at any threshold, rewrite survival is 100% and silent loss 0, but accuracy is about 92% at the
  provisional thresholds (0.50 anchored / 0.75 broad) and 94.8% at the best calibrated pair (0.40 / 0.70), under
  the 95% bar. The misses are human edits of short AI lines (a renamed identifier or a changed literal on a line of
  6-10 tokens): token 3-gram shingling scores those below 0.40, so no threshold recovers them without risking false
  matches. Calibration splits by line, stratified by outcome and tier (a split by scenario put every broad example
  in the held-out part). Thresholds are not written yet: T113 calibrates on the scenario set plus the real-traffic
  corpus and freezes them, and `check-alg-bump.sh` now freezes a golden corpus only once a release contains it.
- **Matching changes from the eval (T109; alg 1, not yet released, so no new `ALG`)**: the full two-gateway run
  also showed formatter output mostly coming out human (85% of formatter-changed AI lines). Four changes, each
  checked against the scenario set: (1) shingles are token 2-grams, so one changed token on a short line costs
  two shingles instead of three; (2) a string literal's quote style is canonical (`'x'` and `"x"` are one token
  when the body has no `"`), so black's requoting is not a modification; (3) a *wrapped* tier joins runs of
  consecutive unmatched lines and matches them as one line, for one AI line a formatter spread over several;
  (4) a *split* tier joins an unmatched fragment to the neighbouring lines that matched a candidate by similarity
  when that raises their similarity to it, for a fragment split off a line whose main part matched (`if missing:`
  from its `raise`, one link of a method chain). The two new tiers need no new fingerprint and report anchored or
  broad as before; they're research R11 steps 7-8. Result at the provisional thresholds: accuracy 87.4% → 96.7%,
  formatter false human 85% → 0%, still no line wrongly called AI modified, rewrite survival 100%, silent loss
  0. The remaining misses are heavier human edits of AI lines (8 lines). Calibration on this set now picks the
  lowest pair on the grid (0.35 / 0.50; 98.4%): the synthetic set has too few close human lookalikes to push the
  thresholds back up, so they stay provisional until T113 adds the real-traffic corpus. Calibration also
  requires anchored ≤ broad and breaks ties toward the higher broad threshold.
- **Outcomes must not depend on the key (T109)**: with 2-grams, the demo's `scn-edited` line (one identifier
  renamed on a 7-token AI line, true similarity 0.50) came out AI modified under 57% of random keys at the 0.50
  anchored threshold: 32 MinHash values estimate it anywhere from 0.22 to 0.84. Its answer key had said "human",
  which described the 3-gram algorithm, not the edit; the line is AI modified, and the demo now says so. Fix: 128
  signature values (estimates 0.34-0.67 for that line) and an anchored threshold of 0.35, the highest that keeps
  it AI modified under ≥ 99% of keys (99.95%). More values alone don't help an edit whose true similarity equals
  the threshold. Calibration now requires this key stability, and lib/tests/test_match.py checks it. On the
  scenario set calibration is flat from anchored 0.30 to 0.40 and broad 0.50 to 0.85 (no line wrongly called AI
  modified anywhere), so broad stays at 0.75 until T113. LSH bands still use 8 × 4 over the first 32 values.
  Quality report afterwards, both gateways: accuracy 98.0%, no line wrongly called AI modified, formatter false
  human 0%, rewrite survival 100%, silent loss 0, agreement 100%.
- **Sizing at 128 values** (Postgres 17, real tables and indexes, 200k lines): 2,678 bytes per captured line
  (2,290 with 32; the 8 band rows are about 75% of it; banding all 128 values would be 7,923). For 1,300
  developers capturing 10,000 lines a day each with 180-day retention: about 6.3 TB at steady state (5.4 TB with
  32), 4.5 TB counting weekdays only.
- **One large response blocked capture (found while sizing)**: each response was one NATS message, and NATS
  refuses payloads over 1 MiB (`max_payload`). A response of about 1,700 lines (640 at 128 values) raised
  `MaxPayloadError`, which the publisher treated as a lost connection and retried forever: every later event and
  heartbeat on that replica waited behind it until the 10,000-message buffer overflowed and dropped it as
  `buffer_overflow`. Reproduced against NATS 2.15.1. Now: the signature is packed binary (about 950 bytes per
  line on the wire instead of 1,640 as JSON numbers; capture message schema `gca.capture.v2`), an event over
  900 KB is sent as `part`s of one `event_id` that ingest stores as one event (lines unique per event, tool call
  and line, so a redelivered part adds nothing; migration 0006), and a message the server refuses anyway is
  dropped at once and reported as `publish_failed`.
- **The PR check no longer loads the whole matching window (T109)**: it loaded every captured line of each
  credited developer in the window into memory (1.8M lines, about 10 GB at 128 values, for 10,000 lines a day
  over 180 days). `gcattr.lookup_keys` lists the exact fingerprints and band hashes `attribute` can look up
  (including the wrapped tier's joined windows), and the PR check fetches only exact hits, band hits and the
  lines of capture events with an exact hit, through the existing indexes. Outcomes are identical by
  construction; a library test checks it on generated PRs and a database test against the full load.
- **Migration 0006 deletes pre-release fingerprints**: rows written before these changes (3-gram, 32-value
  alg 1) can't be compared with new ones. Their capture events keep their metadata.
- **Release gate (T110)**: `release-gate.yml` runs on PRs to `main` and is called by `release.yml`, so nothing is
  published below the bar. It failed on the first measurements above; with the matching changes the scenario
  set meets the bar on both gateways. It isn't a required merge check yet.
- **Role details (T083, T084)**: `portal.adminLogins` are always admins (break-glass, and the only admins on a
  personal account), so a revoke doesn't remove them; an admin can't revoke their own admin role. One override
  per (developer, role, team), latest wins; clearing it returns to the GitHub default. `visible_roles` may also
  hold `other`, which lets every signed-in viewer see every developer.

## Complexity Tracking

No constitution violations to justify.
