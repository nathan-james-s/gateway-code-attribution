# Gateway Code Attribution Constitution

## Core Principles

### I. Never Guess

Attribution MUST state what the evidence supports and nothing more.

- Every attributed line MUST receive exactly one outcome: *AI, unmodified*, *AI, modified*, *human*, or
  *indeterminate*.
- *AI, modified* results MUST carry a confidence level. Results from broad (unanchored) similarity MUST be
  distinguishable from anchored ones everywhere they are reported. Any headline figure MUST be available
  both with and without broad matches.
- A line MUST NOT be labelled *AI* of any kind without a match against captured model output.
- Interactions the system cannot observe MUST be reported as *not observed*, never counted as *human*.
- A capture failure (dropped, unparsable or truncated output) MUST be counted and surfaced. Silent loss is a
  defect.
- When evidence is below a defined threshold, the result MUST fall back to *human* or *indeterminate* as the
  specification defines. It MUST NOT round up to *AI*.

*Rationale:* false attribution in either direction is the most harmful failure this project can have. The
assessment found silent capture loss and blind spots that can't be removed.

### II. No Retained Code or Prompts

The system MUST NOT persist source code, model output text or prompts.

- Only keyed fingerprints, including any similarity-preserving forms, and the metadata needed for attribution
  (identity, time, model, tool-call and path references) MAY be stored.
- Content MAY be processed in memory only, for as long as fingerprinting needs it.
- Logs, traces, metrics, queues, crash reports, and any data the system produces or stores (including during
  demo runs) MUST NOT contain code or prompt text. This includes gateway features that would log completions.
  Authored inputs that are synthetic code by design are exempt: demo fixtures, the sample repository, and the
  scenario set. Those inputs MUST NOT contain real users' code or prompts, unless it's recorded traffic that its
  owner consented to include.
- Fingerprints MUST be keyed with a server-side secret. Unkeyed hashes of code lines MUST NOT be stored.
- Any new similarity-preserving fingerprint MUST come with a documented assessment of what it reveals about
  short lines before it ships.

*Rationale:* privacy by default (problem.md G5) is a core reason to adopt this over tools that store code.

### III. One Shared, Versioned Matching Library

Normalization, fingerprinting and matching MUST live in one library, and every component MUST use it: gateway
capture, the PR check, and any CLI or demo. Duplicate or "equivalent" reimplementations are forbidden.

- The library MUST be released on GitHub under Semantic Versioning.
- Any change that can alter a fingerprint or an attribution outcome MUST bump the algorithm version.
- Every stored fingerprint and every result MUST record the algorithm version that produced it.
- The same input with the same algorithm version MUST produce identical output on every platform. A
  determinism test MUST enforce this.

*Rationale:* both sides of a match must normalize identically (handoff section 4.1), and results must be
reproducible and comparable over time (problem.md G6, M8).

### IV. Vendor and Gateway Neutrality

- The project MUST NOT depend on any single AI vendor, model or coding tool for attribution.
- For tools that route through the gateway, no install per developer machine or per tool MAY be required.
- Every supported gateway (currently agentgateway and LiteLLM) MUST produce identical attribution on the same
  traffic. A shared conformance suite run against each gateway MUST verify this.
- A gateway-specific gap MUST be either closed or reported as *not observed* (Principle I). It MUST NOT be
  hidden.
- No feature MAY require a paid tier of any dependency.
- The project MUST be released under the **Apache License 2.0** (`LICENSE` at the repository root). Every
  dependency MUST carry a license compatible with it.
  *Amended 2026-10-17 (v1.1.0):* the owner dropped the open-source release. The repository is public with no
  license file, as a demo and reference implementation, and no release is planned. The rest of this principle (tool and gateway
  neutrality, no paid tiers, identical results across gateways) is unchanged. No in-flight spec or plan is
  affected: spec 001 is complete and carries the same note.

*Rationale:* vendor-neutral, tool-neutral attribution is the gap this project exists to fill (problem.md G2,
G8).

### V. Measure Before Claiming

- Every published number about attribution quality (accuracy, false-*AI, modified* rate, formatter
  false-*human* rate, coverage, overhead) MUST come from the published scenario set or recorded traffic. The
  method and algorithm version MUST be stated alongside it.
- **Release bar:** a release that changes attribution behaviour MUST NOT be published, and its numbers MUST
  NOT be quoted (including in the companion blog post), until the scenario set shows targets met for all of:
  - the false *AI, modified* rate, with anchored and broad measured separately;
  - overall accuracy;
  - zero silent capture loss.
- Vendor and upstream behaviour (gateways, providers, coding tools, the GitHub App platform) MUST be proven by
  a probe or test before the project depends on it.

*Rationale:* the assessment's evidence was strongest where it was measured (the streamed tool-call probe) and
weakest where it was assumed.

### VI. Out of the Box, Reproducibly

- A single documented install MUST bring up the complete reference stack: a gateway of the adopter's choice,
  storage, ingest buffering, dashboards, the GitHub App PR check and a sample repository.
- The stack MUST offer demo traffic that needs no model or API key, and a bring-your-own-hosted-key path.
- Generated demo traffic MUST use real streaming formats and pass through the real capture path. It MUST NOT
  fabricate results downstream.
- All images, charts and dependencies MUST be pinned to exact versions.
- The stack MUST NOT depend on images or charts that are deprecated, frozen or paywalled (the Bitnami lesson).
- Time to first result for a new adopter MUST be measured and published (problem.md M7).

*Rationale:* adopters, and readers of the companion blog post, must be able to see it work without assembling
parts themselves (problem.md G7).

### VII. Scope Discipline

Work MUST stay inside the scope agreed in `.specify/assessments/gateway-code-attribution/decision.md` unless
this constitution or a later assessment changes it.

- Explicitly out of scope:
  - style- or ML-based authorship inference;
  - watermarking;
  - legal or copyright determination;
  - judging productivity or developer performance;
  - operating a hosted service.
- Option C capabilities MUST NOT be built ahead of the graduation criteria in `concept.md`:
  - gateways beyond the supported two;
  - a developer-side hook;
  - signed results;
  - Agent Trace export;
  - other forges;
  - production high availability.

*Rationale:* one maintainer, and a release bar that depends on calibration rather than build speed.

## Security & Data Handling

- **Keys and secrets:**
  - Fingerprint keys and GitHub App credentials MUST be generated or supplied at install. They MUST never ship
    as defaults, and MUST never be committed.
  - Fingerprint keys MUST support rotation without losing the ability to interpret earlier results. Results
    record the key generation along with the algorithm version.
- **GitHub App:** it MUST request the minimum permissions and events the PR check needs, and the documentation
  MUST list each one with its reason.
- **Per-developer results:** results are available per change, per repository and as team totals, with
  drill-down per developer. Access to per-developer views MUST be controllable by the adopting organization.
- **Jurisdiction:** the project is US-based and isn't designed around GDPR or works-council requirements.
  Documentation MUST state this. Adopters elsewhere are responsible for their own compliance.
- **Releases:** release artifacts (the library, images and charts) MUST publish checksums, and SHOULD publish
  provenance attestations.
- **License:** Apache License 2.0 (Principle IV). It is compatible with agentgateway (Apache-2.0). LiteLLM's
  licensing (open-source core plus a separately licensed enterprise directory) MUST be checked so that only
  its open-source parts are used.

## Development Workflow & Quality Gates

- **Workflow:** features follow the Spec Kit sequence: specify → clarify (as needed) → plan → tasks →
  implement. Each plan MUST pass a Constitution Check against Principles I–VII.
- **Required gates before merge:**
  - **Library changes:** the determinism test and the full scenario set pass. A diff of attribution outcomes
    against the previous algorithm version is attached to the PR.
  - **Gateway capture changes:** the cross-gateway conformance suite passes for every supported gateway. That
    suite covers interleaved parallel calls, freeform tool input, truncated calls, and schema-deviant streams
    (which must report loss, not drop silently).
  - **Data-path changes:** a check confirms that no code or prompt text reaches storage, logs or traces
    (Principle II).
  - **Stack changes:** a clean install from scratch reaches a first result, measured against M7.
- **AI-assisted development** is allowed and expected. It doesn't relax any gate.
- **Real-traffic validation:** recorded traffic from each in-scope coding tool MUST be added to the test
  corpus before that tool is listed as supported.

## Governance

This constitution supersedes other project practices. Where a spec, plan or task conflicts with it, the
constitution wins until it is amended.

- **Amendments:**
  - An amendment is a pull request that edits this file and includes a Sync Impact Report covering version
    change, affected principles, added or removed sections, and follow-ups.
  - The amendment states its effect on in-flight specs and plans.
  - Amendments are approved by the project maintainer(s).
- **Versioning** (Semantic Versioning):
  - MAJOR: a principle is removed or redefined incompatibly.
  - MINOR: a principle or section is added or materially expanded.
  - PATCH: clarifications and wording only.
- **Compliance review:**
  - Every `/speckit-plan` Constitution Check and every PR review MUST verify compliance.
  - A deviation MUST be justified in the plan's complexity tracking, or the constitution amended first.
  - The constitution is reviewed at each release against the release bar (Principle V).

**Version**: 1.1.0 | **Ratified**: 2026-10-14 | **Last Amended**: 2026-10-17
