# Feature Specification: Gateway Code Attribution Reference Stack

**Feature Branch**: `001-gateway-code-attribution` (spec directory; work happens on
`claude/speckit-assess-intake-b6c123`)

**Created**: 2026-10-14

**Status**: Complete (2026-10-16). Every task in [tasks.md](./tasks.md) is done, and the clean-machine run is
recorded in [docs/validation/quickstart-run.md](../../docs/validation/quickstart-run.md). The first public release
(v0.1.0) is deferred by the owner; SC-012 (adoption) follows it.

**Owner decision (2026-10-17)**: the open-source release this spec assumes is dropped. The repository is made
public with no license file (a demo and reference implementation), not under Apache-2.0, and no release
to PyPI or ghcr.io is planned. Everywhere this spec, the plan and the constitution say "open-source" or
"Apache-2.0", read it as the plan at the time; the rest of the spec stands as the record of what was built.

**Input**: User description: "@.specify/assessments/gateway-code-attribution/decision.md" (the assessment's go
decision and its suggested input). The core of that input:

> Build an open-source, self-contained reference stack for AI-code attribution at an AI gateway, for enterprise
> platform teams and practitioners exploring what an AI gateway enables. One install brings up the adopter's
> choice of agentgateway or LiteLLM, storage, ingest buffering, dashboards, a GitHub App PR check and a sample
> repository. Demo traffic can be generated with no model or key, or driven by the adopter's own hosted API key.
>
> The gateway records keyed fingerprints of code the model produced, never the code or prompts. On each PR, every
> added line is classified as AI unmodified, AI modified (with confidence), human or indeterminate. Matching uses
> three tiers: exact with normalization, anchored similarity and broad similarity. Broad matches are always shown
> separately. Interactions the gateway can't see are reported as "not observed", and capture failures are
> visible.
>
> Results are reported per change, per repository and as team totals, with drill-down per developer. The matching
> method ships as a versioned library released on GitHub. Release bar: no publication until a published scenario
> set shows an acceptable false "AI, modified" rate (anchored and broad separately), acceptable accuracy, and no
> silent capture loss.

Governing documents: `.specify/memory/constitution.md` v1.0.0 and
`.specify/assessments/gateway-code-attribution/`.

## Clarifications

### Session 2026-10-14

- Q: Which coding tools are in scope for v1? → A: Claude Code, Codex CLI, Gemini CLI and OpenCode. Copilot and
  Cursor are out of scope for v1 (FR-041).
- Q: What are the release-bar targets? → A: accuracy ≥ 95%; false "AI modified" ≤ 2% anchored and ≤ 5% broad;
  formatter false "human" ≤ 10% (SC-002, SC-003, FR-044). *(Historical answer. The current values are in SC-002 and
  SC-003, which CI checks against `contracts/quality-report.schema.json`.)*
- Q: What is the default for per-developer drill-down in a fresh install? → A: on. Visible to administrators (all
  developers) and to team leads (their own teams only). Configurable by the adopter (FR-029).
- Q: How should a PR author be linked to the gateway identity that produced their AI output? → A: Developers sign in
  with GitHub to get a personal gateway credential, which links the two identities by construction. Admins can add
  overrides for exceptions (FR-016).
- Q: When a PR has commits from several people, whose AI output is matched, and who gets credit? → A: Matching uses
  the captured output of every commit author in the PR. Each line is credited to the author of the PR commit that
  added it (FR-012, FR-015).
- Q: If the attribution side of the stack is down or behind, do developers' AI requests still go through? → A:
  Yes, fail open. Requests always go through, missed captures are counted as capture loss, and affected changes
  are flagged as having incomplete coverage (FR-005a).
- Q: How do people sign in to the dashboards, and where do roles and teams come from? → A: Sign in with GitHub.
  Teams come from the organization's GitHub teams, team maintainers are team leads, and organization owners are
  admins. Admins can override any of it (FR-027, FR-029a).
- Q: How many developers should a default install handle while meeting the speed targets? → A: Up to 500
  developers, with documented guidance for going beyond (SC-009, SC-010, SC-013).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Stand up the stack and see attribution on a sample change (Priority: P1)

An evaluator (an enterprise platform engineer, or a reader of the owner's blog post) wants to see what
gateway-based attribution can do before committing to it.
1. They follow the published install instructions and choose one of the two supported gateways.
2. They start the built-in demo traffic, which needs no model and no API key.
3. They open the sample repository's demonstration pull request.

The PR check shows every added line classified as AI unmodified, AI modified (with confidence), human or
indeterminate. The dashboard shows the same change in the totals.

**Why this priority**: This is the first thing both primary adopters do, and it's the companion blog post's core
promise. It exercises the whole pipeline end to end (capture, matching, PR check and reporting) and proves the
stack is self-contained. Without it, nothing else can be evaluated.

**Independent Test**: On a clean environment, follow only the published instructions, install with each gateway
in turn, run the demo, and check that the demonstration PR shows all four outcomes with the expected counts.
Measure the elapsed time.

**Acceptance Scenarios**:

1. **Given** a clean environment that meets the documented prerequisites, **When** the evaluator runs the
   documented install and chooses agentgateway, **Then** the complete stack becomes ready without any further
   component setup. The same holds when they choose LiteLLM.
2. **Given** a running stack, **When** the evaluator starts demo traffic, **Then** model output that looks like
   real agent tool calls flows through the chosen gateway's real capture path, and no model or API key is needed.
3. **Given** captured demo traffic and the sample repository's demonstration PR, **When** the PR check runs,
   **Then** the PR shows per-line results in all four outcomes. AI-modified lines show their confidence, and broad
   matches are marked as broad.
4. **Given** the demonstration PR is attributed, **When** the evaluator opens the dashboard, **Then** the change
   appears in the per-change, per-repository and team totals.
5. **Given** the same demo run on each gateway, **When** results are compared, **Then** every line's outcome is
   identical.

---

### User Story 2 - Attribute real pull requests for developers using AI coding tools (Priority: P2)

A platform team runs the stack for real. Developers point their AI coding tools at the gateway and change
nothing else: no plug-in, no hook, no per-machine install. When a developer opens or updates a pull request in a
repository where the GitHub App is installed, the PR check attributes each added line. It uses the output
captured from that developer's AI tool sessions, and it handles formatting changes, history rewrites and common
lines without mislabelling them.

**Why this priority**: This is the actual value for enterprise platform teams: tool-neutral, line-level
attribution on their own infrastructure. It depends on the stack from Story 1 but can be tested separately with a
real repository and a real coding tool.

**Independent Test**: With the stack installed and the GitHub App on a test repository, use an in-scope coding
tool through the gateway (bring-your-own hosted key) to make changes. Hand-edit some generated lines, run a
formatter, then open a PR. Compare the PR check's per-line results with a hand-labelled answer key.

**Acceptance Scenarios**:

1. **Given** a developer who got a personal gateway credential by signing in with GitHub, and whose coding tool
   uses it, **When** they open a PR containing lines the model produced and they didn't change, **Then**
   those lines are reported as **AI unmodified**.
2. **Given** model-produced lines the developer then edited, **When** the PR check runs, **Then** each edited line
   that meets the anchored criteria is reported as **AI modified (high confidence)**. Lines meeting only the broad
   criteria are **AI modified (lower confidence, broad)**. Lines meeting neither are **human**.
3. **Given** lines the developer typed with no corresponding captured output, **When** the PR check runs, **Then**
   those lines are reported as **human**, and never as any AI outcome.
4. **Given** a PR with blank lines, lone braces or very common statements, **When** the PR check runs, **Then**
   those lines are **indeterminate** and are left out of the AI and human percentages.
5. **Given** a PR whose commits are rebased, squashed, amended or cherry-picked after opening, **When** the PR
   check re-runs, **Then** the AI lines keep their attribution.
6. **Given** a PR opened before capture has caught up with the developer's recent AI activity, **When** the PR
   check runs, **Then** it reports **pending** rather than labelling lines human. It completes automatically once
   capture catches up.
7. **Given** a PR whose commit authors have no mapped gateway identity, **When** the PR check runs, **Then** the
   change is reported as **not observed**, not as human.
   **Given** a PR where only some commit authors are mapped, **Then** the lines added by unmapped authors' commits
   are **not observed**, and the rest are attributed normally.
8. **Given** a PR with commits from two mapped developers, **When** the PR check runs, **Then** each line is
   matched against, and credited to, the author of the commit that added it. Team and per-developer totals reflect
   that credit.
9. **Given** a PR that receives new pushes, **When** each push arrives, **Then** attribution is recomputed for the
   new head. The result at merge time is kept as final.

---

### User Story 3 - Review attribution across changes, repositories and teams (Priority: P3)

A platform or engineering lead wants to understand AI-generated code across the organization. They open the
dashboards and see attribution totals per change, per repository and per team over a chosen period. Where
permitted, they drill down to individual developers. Every figure can be viewed with and without broad-similarity
matches, and shows the algorithm version that produced it.

**Why this priority**: Aggregated views are how adopters act on attribution, but they depend on per-change
results (Story 2) existing first.

**Independent Test**: Load a set of already-attributed changes across several repositories and teams. Check that
each aggregate equals the sum of its underlying per-change results, that the with/without-broad toggle changes
only broad-match counts, and that per-developer views follow the configured access rules.

**Acceptance Scenarios**:

1. **Given** attributed changes in several repositories, **When** the lead selects a repository and period,
   **Then** they see counts and percentages for each outcome, which match the sum of that repository's change
   results.
2. **Given** developers grouped into teams, **When** the lead views team totals, **Then** each team's figures
   cover exactly its members' changes.
3. **Given** a fresh install with default settings:
   - **When** an administrator drills down, **Then** they can see any developer's figures.
   - **When** a team lead drills down, **Then** they can see figures only for members of their own teams.
   - **When** any other viewer tries, **Then** per-developer figures aren't shown.
4. **Given** any figure, **When** the viewer switches broad matches off, **Then** broad AI-modified lines are
   excluded and the figure is recomputed. The algorithm version is shown either way.

---

### User Story 4 - See coverage and blind spots (Priority: P4)

A platform administrator needs to know how far the numbers can be trusted. A coverage view shows:
- which AI interactions were observed;
- how many captures failed and why (truncated, unreadable, unexpected format);
- which PR authors have no mapped gateway identity;
- which tool, API or gateway combinations aren't captured.

It also lists the documented interactions that never pass through the gateway (for example, inline completions
served directly by a vendor).

**Why this priority**: This is required for honest reporting (constitution Principle I), but it builds on
capture and attribution being in place.

**Independent Test**: Inject known capture faults into demo traffic (truncated calls, streams in an unexpected
format) and include a PR from an unmapped author. Check that every fault and the unmapped author appear in the
coverage view with correct counts, and that none of them is counted as human.

**Acceptance Scenarios**:

1. **Given** demo traffic containing a known number of injected capture faults, **When** the administrator opens
   the coverage view, **Then** the reported failure count equals the injected count, with the cause of each.
2. **Given** a gateway that can't capture a particular tool or API combination, **When** traffic of that kind
   occurs, **Then** it is reported as **not observed** for that combination.
3. **Given** a change whose attribution period includes capture failures for any of its commit authors, **When** its result is
   shown, **Then** the result carries an **incomplete coverage** notice.
4. **Given** the attribution components are stopped while a developer uses an in-scope coding tool, **When** the
   developer makes AI requests, **Then** every request succeeds. **When** the components restart, **Then** the
   coverage view reports the loss for that period.

---

### User Story 5 - Reuse the versioned matching library (Priority: P5)

A developer at another organization, or a maintainer of this project, wants to use the normalization,
fingerprinting and matching method on its own. They take a specific released version of the library, which
produces the same fingerprints and outcomes as the stack for that version, and use it in their own tooling.

**Why this priority**: It's an owner goal (a versioned algorithm library on GitHub) and the basis of
reproducibility. External reuse is secondary to the stack itself.

**Independent Test**: Run the same input through the released library and through the stack's PR check, at the
same algorithm version, and confirm identical fingerprints and outcomes. Repeat on a different operating system
and confirm identical output.

**Acceptance Scenarios**:

1. **Given** a released library version, **When** a consumer computes fingerprints and outcomes for a fixed input,
   **Then** the results match the stack's results for that version exactly, on any supported platform.
2. **Given** a library change that alters any fingerprint or outcome, **When** it is released, **Then** it carries
   a new algorithm version, and results record which version produced them.
3. **Given** output captured under an earlier algorithm version or fingerprint key generation, **When** a later PR
   is attributed, **Then** matching uses the version and key generation of that captured output, and earlier
   results stay interpretable.

---

### User Story 6 - Measure attribution quality before publishing (Priority: P6)

Before a release, or before quoting numbers in the blog post, the maintainer runs the published, labelled
scenario set against the stack with each supported gateway. The resulting quality report gives:
- overall and per-outcome accuracy;
- the false "AI modified" rate, with anchored and broad matches measured separately;
- the rate of formatter-caused false "human" labels;
- history-rewrite survival;
- capture-loss counts;
- whether the two gateways agree.

A release goes ahead only if the report meets the release bar.

**Why this priority**: It's the gate on publication (constitution Principle V). It needs the full pipeline in
place, so it comes last, but it must exist before any release.

**Independent Test**: Run the scenario set and check that the report covers every listed measure for each
gateway. Then deliberately degrade the matching thresholds and confirm the release bar fails.

**Acceptance Scenarios**:

1. **Given** the published scenario set, **When** the maintainer runs an evaluation, **Then** a report gives each
   listed measure per gateway, with the algorithm version.
2. **Given** a report that misses any release-bar target, **When** a release is attempted, **Then** the release is
   blocked, and the failing measures are named.
3. **Given** an in-scope coding tool, **When** it is listed as supported, **Then** recorded real traffic from that
   tool is part of the evaluation corpus.

---

### Edge Cases

- **Formatters and linters** run after generation (including ones built into coding tools). Lines that differ
  only in whitespace or line endings still match exactly after normalization. Other formatter changes are caught
  by similarity matching or reported as human. Their rate is measured (Story 6).
- **The same line is generated once but appears several times in a PR.** Matches are counted as a multiset: each
  captured occurrence can account for only one PR line.
- **Two developers generate the same snippet.** Each line is matched only against the captured output of the
  commit author it's credited to, within the time window. One developer's AI output is never credited to another
  developer's line.
- **Unapplied output.** Model output that was proposed but never applied (refused permissions, failed or
  abandoned edits) leaves captures that never match a PR. It must not raise the AI share.
- **Lines merged in from the base branch.** These are not part of the PR's own changes and are not attributed.
- **Truncated model output** (stopped by an output limit mid-tool-call). Complete lines before the cut-off may be
  used, the incomplete remainder is discarded, and the event is counted as a capture failure of type
  "truncated".
- **Streams in an unexpected format** from an upstream that is "compatible" but not exact. Capture loss must be
  counted and shown, never silent.
- **Very large or excluded files** (lockfiles, generated, vendored, minified, binary). Excluded by configurable
  rules, and the exclusions are listed in the PR result.
- **Duplicate or retried PR events.** Results are unchanged.
- **Fingerprint key rotation** between generation and PR. Matching still works for output captured under the
  previous key generation, within the retention period.
- **A PR touching files with no AI activity at all.** Every non-trivial line is human, and the result states the
  observation scope (the gateway, and the commit authors' mapped identities).
- **Attribution components are down or falling behind** (capture, ingest buffering or storage). Developers' AI
  requests still succeed (fail open). The output that can't be captured is counted as capture loss, and PRs whose
  matching window overlaps the outage are flagged as having incomplete coverage.
- **Nothing to attribute.** A PR with only deletions or only excluded files reports no attributable lines, not
  0% AI.

## Requirements *(mandatory)*

### Functional Requirements

**Capture at the gateway**

- **FR-001**: The stack MUST support agentgateway and LiteLLM as AI gateways. The adopter chooses one at install
  time.
- **FR-002**: The system MUST capture the code-bearing content of model responses passing through the chosen
  gateway, including streamed responses. That covers structured tool-call arguments, freeform tool input such as
  patches, and code in ordinary response text. Content split across stream fragments MUST be reassembled
  completely before fingerprinting.
- **FR-003**: The system MUST store only keyed fingerprints of normalized lines, plus attribution metadata: gateway
  identity, session, model, time, tool-call reference, file path when the tool call names one, algorithm version
  and fingerprint key generation.
- **FR-004**: Source code, model output text and prompts MUST NOT appear in any stored data, logs, traces,
  metrics, queued messages, crash reports or demo data. They may only be held in memory while being fingerprinted.
- **FR-005**: Every capture failure (dropped, unreadable, truncated or unexpected-format output) MUST be counted
  with its cause and made visible. No failure may be discarded silently.
- **FR-005a**: Capture MUST **fail open**. Developers' AI requests through the gateway MUST succeed, and MUST NOT
  be delayed beyond the latency target in SC-010, whether or not capture, ingest buffering or storage are
  available or keeping up.
  - Output that can't be captured MUST be counted as capture loss, with its cause (FR-005).
  - Changes whose matching window overlaps the loss MUST carry the **incomplete coverage** notice (FR-022).
- **FR-006**: For the same traffic, both supported gateways MUST produce identical fingerprints and identical
  attribution outcomes.
- **FR-007**: Any tool, API or gateway combination that the chosen gateway can't capture MUST be reported as **not
  observed** and documented.

**Attribution of a change**

- **FR-008**: For each pull request, the system MUST attribute only the lines the PR adds relative to its merge
  base with the target branch.
- **FR-009**: Each attributable added line MUST receive exactly one outcome: **AI unmodified**, **AI modified**,
  **human** or **indeterminate**.
  - A line is **attributable** if it's an added line, not in an excluded path, and credited to a commit author
    with a mapped gateway identity.
  - Lines credited to unmapped authors are **not attributable**. They get the state **not observed** (FR-015),
    which isn't an outcome. They're counted separately and never appear in outcome counts or percentages.
- **FR-010**: Matching MUST run in tiers, strongest evidence first:
  1. **exact** (after normalization of whitespace, line endings and Unicode form, tolerant of formatting) →
     AI unmodified;
  2. **anchored similarity** (the line is highly similar to a line in a capture event that also produced **at
     least one exact match in the same file**; if that capture event names a file path, the path must also match
     the file) → AI modified, high confidence;
  3. **broad similarity** (the line is similar to output captured for the same developer within the matching
     window, with no exact-match anchor in the file; a path match alone is not an anchor) → AI modified, lower
     confidence.

  "Highly similar" and "similar" mean similarity at or above the anchored and broad thresholds. Those are fixed per
  algorithm version (research R9), calibrated against the scenario set, and must meet SC-003.
- **FR-011**: A line MUST NOT receive any AI outcome without a match to captured model output. Lines below the
  similarity thresholds MUST be **human**. Trivial or very common lines MUST be **indeterminate**.
- **FR-012**: Matching MUST be limited to output captured for the mapped gateway identities of the PR's **commit
  authors** (identified by GitHub account), within a configurable time window. It MUST never draw on output from
  anyone who didn't author a commit in the PR.
  - Each attributable line MUST be **credited** to the author of the PR commit that added it, for per-developer
    and team reporting.
  - A line's AI outcome MUST come from a match against that credited author's own captured output.
  - If an author squashes or rewrites the PR's commits before merging, credit follows the commits as they stand
    at each PR head.
- **FR-013**: Matches MUST be counted as a multiset: each captured line occurrence can account for at most one PR
  line.
- **FR-014**: Indeterminate lines MUST be left out of AI and human percentages and reported as a separate count.
- **FR-015**: Lines credited to a commit author with no mapped gateway identity, including commits whose author
  isn't linked to any GitHub account, MUST be given the state **not observed** (not an outcome; see FR-009), and
  never attributed as human. They are counted separately and left out of AI and human percentages. If no
  commit author in the PR is mapped, the whole change MUST be reported as **not observed**.
- **FR-016**: Developers MUST obtain their personal gateway credential by signing in with their GitHub account.
  This links their GitHub identity to their gateway identity by construction. PR authors are identified by their
  GitHub account, never by commit email.
  - Administrators MUST be able to add, change and remove overrides for exceptions, such as service accounts or a
    developer using several GitHub accounts.
  - Revoking a credential MUST stop future capture under it, without removing captures already made.
  - The demo MUST come with its sample developers' credentials and links preconfigured.
- **FR-017**: If capture hasn't caught up to the time of the PR's latest change, the result MUST be **pending**,
  and the system MUST complete attribution automatically once capture catches up.
- **FR-018**: Attribution MUST be recomputed for each new head of a PR. Results MUST be stored per head, and the
  result at merge time MUST be kept as final.
- **FR-019**: Attribution MUST NOT depend on commit identity, so that it survives rebase, squash, amend and
  cherry-pick.
- **FR-020**: Processing the same PR event more than once MUST NOT change the result.
- **FR-021**: The system MUST apply configurable exclusion rules, with defaults for lockfiles, generated,
  vendored, minified and binary files. Excluded paths MUST be listed in the result.
- **FR-022**: A change's result MUST carry an **incomplete coverage** notice when capture failures were recorded
  for any of its commit authors during the matching window.

**PR check**

- **FR-023**: The PR check MUST be delivered as a GitHub App that the adopter can install on chosen repositories
  or an organization. Its documentation MUST list each permission and event it needs, with the reason.
- **FR-024**: On each PR head, the check MUST report:
  - counts and percentages for each outcome, with AI modified split by confidence (anchored and broad);
  - coverage status (complete, incomplete, pending or not observed);
  - excluded paths;
  - the algorithm version;
  - a way to see each line's outcome.
- **FR-025**: By default, the check MUST be informational: it reports and doesn't block merging.

**Reporting**

- **FR-026**: The system MUST report attribution per change, per repository and as team totals over a selectable
  period, with drill-down to individual developers.
- **FR-027**: Teams and their membership MUST be taken from the GitHub organization's teams by default, and kept
  in sync as those teams change. Administrators MUST be able to override membership, or define extra teams, in the
  stack.
- **FR-028**: Every figure MUST be viewable both with and without broad-similarity matches, and MUST show the
  algorithm version or versions it is based on.
- **FR-029**: Access to per-developer views MUST be controllable by the adopter. In a fresh install,
  per-developer drill-down MUST be **on**. By default it is visible to **administrators** (all developers) and to
  **team leads** (members of their own teams only), and to no one else. Adopters MUST be able to designate team
  leads, turn per-developer views off, or change which roles can see them.
- **FR-029a**: Viewers MUST sign in to the dashboards with their GitHub account. Viewer roles MUST default to:
  - **administrator**: GitHub organization owners;
  - **team lead**: maintainers of a GitHub team, for that team only;
  - **other**: everyone else.

  Administrators MUST be able to grant or revoke administrator and team-lead roles in the stack, overriding the
  GitHub-derived defaults. Role changes MUST take effect within 60 seconds:
  - in-stack grants and revokes take effect at the viewer's next page load;
  - GitHub-side changes (organization ownership, team maintainership) take effect within 60 seconds, by checking
    the viewer's current GitHub role, not only the periodic sync.
- **FR-030**: A coverage view MUST show:
  - observed versus not-observed tool, API and gateway combinations;
  - capture failure counts by cause over time;
  - PR authors without a mapped identity;
  - the documented list of interactions that never pass through the gateway.

**Matching library and keys**

- **FR-031**: Normalization, fingerprinting and matching MUST be provided by a single library, and every component
  MUST use it.
- **FR-032**: The library MUST be released on GitHub under semantic versioning. Any change that can alter a
  fingerprint or an outcome MUST receive a new algorithm version.
- **FR-033**: The same input with the same algorithm version MUST give identical fingerprints and outcomes on
  every supported platform.
- **FR-034**: When a PR is attributed, its lines MUST be fingerprinted with the algorithm version and key
  generation of the captured output they're compared against.
- **FR-035**: Fingerprint keys and GitHub App credentials MUST be generated or supplied at install. No default
  secret may ship with the stack.
- **FR-036**: Fingerprint keys MUST be rotatable without losing the ability to match output captured under the
  previous key generation during the retention period.

**Install, demo and documentation**

- **FR-037**: A single documented install MUST bring up the complete stack: the chosen gateway, storage, ingest
  buffering, dashboards, the PR check service and a sample repository with a demonstration PR. No component may
  need to be assembled separately.
- **FR-038**: The stack MUST provide a demo traffic mode that needs no model and no API key. Demo traffic MUST:
  - use the real streaming formats of the supported model APIs;
  - pass through the real capture path;
  - include scripted human edits (defined per demo session, see research R18), so that the demonstration PR
    exercises all four outcomes and both similarity tiers;
  - never fabricate results after capture.
- **FR-039**: The stack MUST support a bring-your-own hosted API key mode, so adopters can drive real coding
  agents through the gateway.
- **FR-040**: The documentation MUST cover:
  - how to route each in-scope coding tool through the gateway;
  - the interactions that can't be observed;
  - what each outcome means;
  - the jurisdiction statement (US-based; adopters elsewhere are responsible for their own compliance).
- **FR-041**: The coding tools in scope for v1 are **Claude Code, Codex CLI, Gemini CLI and OpenCode**. Each routes
  all its model traffic through the gateway with only an endpoint change. GitHub Copilot and Cursor are out of
  scope for v1. The documentation MUST list them, with the reason, among the interactions that can't be observed
  (FR-040). Where a supported gateway can't capture one of the in-scope tools, that combination MUST be reported as
  not observed until it's resolved (FR-007). Gemini CLI's native API through LiteLLM was validated on 2026-10-14
  (research R3, docs/validation/R3-litellm-gemini.md). On agentgateway it's captured by parsing the raw stream (research R2).

**Quality measurement and release bar**

- **FR-042**: The project MUST publish a labelled scenario set. It MUST cover unmodified AI lines, human-edited AI
  lines, formatter output, refactors, unrelated code that resembles AI output, human-written code, trivial lines
  and history rewrites.
- **FR-043**: An evaluation run MUST produce a quality report per gateway containing:
  - overall and per-outcome accuracy;
  - the false "AI modified" rate, separately for anchored and broad matches;
  - the formatter-caused false "human" rate;
  - history-rewrite survival;
  - capture-loss counts;
  - cross-gateway agreement;
  - the algorithm version.
- **FR-044**: A release MUST NOT be published, and its figures MUST NOT be quoted publicly, unless the quality
  report meets every release-bar target with each supported gateway and shows zero silent capture loss. The
  targets are the ones in SC-002 and SC-003. They're defined once, as the release-bar constants in
  `contracts/quality-report.schema.json`, and CI checks that this spec and the schema agree.
- **FR-045**: A coding tool MUST NOT be listed as supported until recorded real traffic from it is part of the
  evaluation corpus.

### Key Entities

- **Captured output record**: one keyed fingerprint of one normalized line of model output, in the forms needed
  for exact and similarity matching. It holds the gateway identity, session, model, time, tool-call reference,
  optional file path, algorithm version and key generation. It contains no code.
- **Capture event**: one model response as seen by the gateway. It records whether capture succeeded, and if not,
  the failure cause and the tool, API and gateway combination.
- **Identity mapping**: links a developer's GitHub account to their gateway identity. It's created when the
  developer signs in with GitHub to get a personal gateway credential, and admins can override it. Unmapped
  authors make a change "not observed".
- **Gateway credential**: a developer's personal credential for calling the gateway. It's issued on GitHub
  sign-in, is revocable, and every capture records the identity behind it.
- **Team**: a group of developers used for team totals. It's taken from a GitHub team by default and can be
  overridden by administrators. Each team has one or more team leads (by default, the GitHub team's maintainers),
  who by default can see per-developer figures for that team.
- **Viewer role**: administrator, team lead or other. It's derived from GitHub (organization owner, team
  maintainer) unless overridden, and it decides which reports a person can see (FR-029, FR-029a).
- **Change**: a pull request in a repository. It has a series of heads, a merge base and an author.
- **Change result**: the attribution of one change head. It includes:
  - per-outcome counts, with AI modified split by confidence tier;
  - coverage status;
  - excluded paths;
  - the algorithm version;
  - a final flag at merge.
- **Line result**: one added line's outcome (or *not observed*), with confidence, the tier that matched, the
  credited developer (the author of the PR commit that added it), and its position (for display only, never for
  matching).
- **Algorithm version**: the released library version that defines normalization, fingerprinting and matching.
- **Key generation**: the identity of the fingerprint key in use, which changes on rotation.
- **Scenario set and quality report**: the labelled scenarios, and the measured results per gateway and algorithm
  version that the release bar is checked against.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An evaluator who follows only the published instructions reaches the first attributed demonstration
  PR within 30 minutes of starting the install. This excludes provisioning the underlying cluster or machine, and
  is measured with each supported gateway.
- **SC-002**: On the published scenario set, overall line-classification accuracy is **at least 95%**, measured
  with each supported gateway.
- **SC-003**: On the published scenario set, with each supported gateway:
  - **false "AI modified" rate** (lines labelled AI modified that are actually human) is **at most 2% for
    anchored** matches and **at most 5% for broad** matches, each measured separately;
  - **formatter-caused false "human" rate** (AI lines labelled human only because a formatter changed them) is
    **at most 10%**.

  Together, SC-002 and SC-003 are the release-bar targets (FR-044).
- **SC-004**: 100% of AI lines in the scenario set's history-rewrite cases (rebase onto a moved base, squash merge,
  amend, cherry-pick) keep their attribution. The baseline from the earlier hook-based tool is 30/30.
- **SC-005**: 100% of injected capture faults are reported in the coverage view with the correct cause, and none is
  counted as human (zero silent capture loss).
- **SC-006**: An audit of all stored data, logs, traces and metrics after a full demo run finds zero occurrences of
  source code or prompt text.
- **SC-007**: Running the scenario set through each supported gateway gives identical outcomes for 100% of lines.
- **SC-008**: Re-running attribution on the same change with the same algorithm version gives identical results
  100% of the time, including on a different supported platform.
- **SC-009**: For a PR of up to 1,000 added lines, the PR check result appears within 2 minutes of the PR being
  opened or updated, once capture has caught up. This holds on a default install at the SC-013 load.
- **SC-010**: Developers using an in-scope coding tool through the gateway notice no slowdown: response completion
  time increases by no more than 5% at the 95th percentile, compared with the same gateway without attribution.
  This holds on a default install at the SC-013 load.
- **SC-011**: The in-scope coding tools need zero per-machine or per-tool installs. Pointing the tool at the
  gateway is the only developer-side step.
- **SC-012** (qualitative): The owner's company runs the stack on at least one real repository, and its platform
  team judges the per-line results trustworthy enough to report internally. External deployments, issues and
  contributions are tracked after publication as an adoption signal.
- **SC-013**: A default install supports **up to 500 active developers**. That means their captured output across
  the full retention period (90 days by default) and their PRs, with SC-009 and SC-010 still met. The
  documentation gives guidance for going beyond 500 developers. High availability isn't guaranteed (it's out of
  scope for v1).

## Assumptions

- **Users and environment**
  - The primary adopters are enterprise platform teams and practitioners exploring AI gateways; the owner's
    company is the first real adopter.
  - Developers cooperate by routing their coding tools through the gateway. Defending against deliberate evasion
    (laundering AI output, or routing around the gateway) is out of scope for v1, pending the owner's decision
    (assessment open question 5).
  - The install targets a Kubernetes cluster, in line with the owner's packaging intent. A small single-node
    cluster is enough for the demo.
  - The default install is sized for up to 500 active developers (SC-013). Larger organizations follow the
    documented guidance, without a performance guarantee in v1.
  - GitHub (GitHub.com, including Enterprise Cloud) is the only forge. Compatibility with GitHub Enterprise Server
    is not guaranteed in v1.
- **Defaults**
  - The matching window defaults to 14 days.
  - Fingerprint retention defaults to 90 days.
  - Both are configurable.
- **Not observed by design**
  - Interactions that never pass through organization-controlled infrastructure are reported as not observed:
    Copilot inline and next-edit completions, Cursor Tab, Composer and inline edit, and chat output pasted from
    elsewhere.
  - GitHub Copilot and Cursor as a whole are out of scope for v1 (owner decision, 2026-10-14), even for the
    interactions they can route through a customer endpoint.
  - Lines from those interactions that end up in a PR can't be told apart from human-written lines, so "human"
    means **"no match to observed AI output"**. Every result states its observation scope.
- **Scope decisions already made**
  - Out of scope for this feature (constitution Principle VII):
    - gateways other than agentgateway and LiteLLM;
    - a developer-side hook;
    - signed results;
    - Agent Trace export;
    - other forges;
    - production-grade high availability;
    - style- or ML-based inference;
    - watermarking;
    - legal or copyright determination;
    - productivity judgments;
    - a hosted service.
  - The project is US-based and isn't designed around GDPR or works-council requirements.
  - Licensed under Apache-2.0. *(Superseded on 2026-10-17: no license, see the status note above.)*
- **Accepted risk (owner, 2026-10-14)**
  - On agentgateway, a response in flight when the capture processor *crashes* (not a graceful restart) is cut short
    for the developer, because agentgateway 1.6.0's fail-open covers only requests that start after the failure
    (docs/validation/R2-extproc.md). Every other request satisfies FR-005a. Mitigations: a worker process, a
    self-deadline, graceful drain and replicas. The LiteLLM path is unaffected.
- **Known risks carried from the assessment**
  - Gemini CLI's native streaming API through LiteLLM 1.105.1 is unvalidated (research R3). Until validated, that
    combination is reported as not observed. agentgateway 1.6.0's own native-Gemini tool-call gap doesn't affect
    capture, because the stack parses the raw stream through `extProc` (research R2).
  - Capture behaviour was validated on synthetic streams; real-traffic validation is required before tools are
    listed as supported (FR-045).
- **Seed data**
  - The earlier hook-based tool's scenario set (59 lines, 30 history-rewrite lines) seeds the published scenario
    set, which is extended to cover similarity tiers and formatters.
