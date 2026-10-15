# Decision: Gateway-sourced AI-code attribution, shipped as a self-contained reference stack

- **Slug**: gateway-code-attribution
- **Decided**: 2026-10-14
- **Verdict**: **go**, with a release bar and a constitution prerequisite (see Verdict & Rationale)
- **Artifacts reviewed**: intake.md, research.md (including `probes/streamed-tool-calls/`), problem.md, concept.md;
  plus `docs/handoffs/gateway-fingerprint-attribution.md`, which they cite

## Scorecard

| Criterion | Rating | Justification |
|-----------|--------|---------------|
| Problem validity | **adequate** | The gap is real and specific: line-level, multi-tool, self-run, vendor-neutral attribution. Today's alternatives are self-reported surveys that disagree with measurement by more than 10×, per-vendor dashboards covering one tool each, hook tools needing an install per machine, and block-level classifiers (research: Market & Context). It is narrow, though. Teams satisfied with one vendor's dashboard or git-ai's hooks already have an answer (problem.md: Cost of Inaction). |
| Evidence strength | **adequate** | **Technical and prior-art evidence is good.** Prior art is cited, including the closest precedents (TensorZero, fetched; Cursor's tracking API; git-ai). Routing constraints per tool are sourced. A lab probe showed both gateways deliver complete, byte-exact tool-call arguments for Chat, Responses and Anthropic streams. **Demand evidence is thin but sufficient for this scope:** the first adopters are the owner and the owner's company, both stated. Industry interest is the owner's report, not independently sourced. **Weak spots:** the probe used synthetic streams, and the similarity matching in Option B has no measured basis yet. Overall research confidence: medium. |
| Value vs. inaction | **adequate** | Inaction leaves the owner's company evaluating a central AI gateway with no open, vendor-neutral attribution. The leading open-source option now has its maintainers on OpenAI's Codex team, and its self-hosted server sits in a paid tier (research: Prior Art). The reference stack plus blog post also has value as a public demonstration of what a gateway enables, independent of wide adoption. For organizations already covered by one vendor, the value is modest. |
| Feasibility / appetite | **adequate** | Option B is credible. Capture is de-risked by the probe, and both gateways and the GitHub App path are confirmed as usable. The owner accepts a medium-to-large appetite: about 8–14 weeks at a conventional pace, which the owner expects AI-assisted development to compress. The part that doesn't compress, **calibrating and validating the similarity tiers**, is acknowledged and budgeted as a release bar. One maintainer is a real constraint (concept assumption 14). |
| Strategic fit | **adequate** | It aligns with every stated owner goal: open source, out of the box, enterprise platform teams first, a companion blog post, and a versioned algorithm library on GitHub. **This repository has no constitution yet** (`.specify/memory/` is absent; the `ai-gateway` v1.1.1 constitution no longer applies), so fit can't be checked against binding principles. That's why the verdict has a prerequisite. |
| Risk posture | **adequate** | The major risks are named and each has a concept-level mitigation: false "AI, modified" labels (separate tiers, confidence levels, the with/without-broad split, a release bar); silent capture loss (a coverage signal); gateway parity (a shared test suite); blind spots (reported as "not observed"); dependency rot (no Bitnami-style dependencies). **Two remain only partly mitigated:** mapping PR authors to gateway users in a real enterprise, and a privacy-preserving similarity fingerprint for short lines. Both are bounded design problems for specification, not unknowns that would sink the project. |

No criterion is rated `weak` or `unknown`.

## Verdict & Rationale

**Go.** Every criterion is adequate. Evidence strength clears the bar because the risky technical assumption,
whether a gateway can reliably recover the code a model produced, was **tested rather than assumed**. The demand
question is answered for the stated first adopters, the owner and the owner's company. Option B is a shaped,
bounded concept with a clear in/out split and a path to Option C that depends on evidence.

The verdict is **not strong**, and the record should say why:
- demand beyond the owner and the owner's company is unproven;
- the similarity matching in Option B has no measured basis yet;
- real-traffic validation is still outstanding.

Those are handled as conditions on the go, not reasons to stop:

1. **Constitution first.** Run `/speckit-constitution` before `/speckit-specify`. This repo has no governing
   principles, and the ones it inherited from `ai-gateway` were dropped with the homelab. The assessment
   suggests these candidate principles, for the owner to accept or change:
   - never guess (prefer *unknown* / *not observed*);
   - no retained code or prompts;
   - one shared, versioned matching library;
   - vendor neutrality;
   - claims proven by measurement before they're published.
2. **Release bar (from concept.md).** Don't publish Option B, or quote its numbers in the blog post, until the
   published scenario set shows all of the following. The targets get set during specification.
   - an acceptable **false "AI, modified" rate**, measured separately for anchored and broad matches;
   - acceptable overall accuracy;
   - **no silent capture loss**.
3. **Real-traffic validation early.** Re-run the streamed tool-call probe against recorded real traffic from the
   in-scope tools before relying on synthetic fixtures.

**Kill was considered and rejected.** Option A (adopt git-ai and vendor dashboards) is a real alternative. It
fails the stated first adopter on three goals: no install per machine (G2), easy for others to try (G7) and
vendor-neutral (G8). git-ai's change in stewardship weakens it further. Nothing in the artifacts shows the problem
is already solved for a platform team that centralizes AI traffic through its own gateway.

## If needs-clarification

Not applicable. The open questions below are carried into specification. None of them blocks starting it.

## If go — Handoff to `/speckit-specify`

- **Problem**: Enterprise platform teams that let developers use several AI coding tools can't reliably tell, line
  by line and across all their tools, which code in a change came from model output, which was changed afterwards
  and which was written by a person. Nor can they produce that answer on infrastructure they control, without a
  vendor and without installing something on every developer machine or wiring every tool.
- **Chosen approach**: **Option B, a reference stack with full four-class attribution.**
  - One self-contained install. The adopter chooses **agentgateway or LiteLLM** as the gateway. It brings up
    storage, ingest buffering, dashboards, a **GitHub App** PR check, and a sample repository.
  - **Demo traffic:** generated with no model or key needed, or driven by the adopter's own hosted API key.
  - **Per-line outcomes:** AI unmodified, AI modified (with confidence), human, indeterminate.
  - **Three matching tiers:** exact (normalized), anchored similarity (high confidence) and broad similarity
    (lower confidence). Broad matches are always shown separately.
  - **Recording:** keyed fingerprints only, never code or prompts.
  - **Blind spots:** reported as "not observed", and a coverage signal shows capture failures.
  - **Reporting levels:** per change, per repository and team totals, with drill-down per developer.
  - **Library:** the matching method ships as a **versioned library released on GitHub**.
  - **Companion:** the owner's blog post.
  - The work may reasonably be split into several features during specification, for example: library, gateway
    capture, PR check, packaged stack, dashboards and demo traffic. That split is for specify and plan to decide.
- **In scope / out of scope**:
  - **In**:
    - everything listed under Chosen approach;
    - honest reporting of blind spots and confidence;
    - a published scenario set that the release bar is measured on.
  - **Out:**
    - style or ML inference;
    - watermarking;
    - legal or copyright determination;
    - productivity or performance judgments;
    - interactions that never pass through organization-controlled infrastructure (Copilot inline completions,
      Cursor Tab/Composer, pasted chat output), which are reported as *not observed*;
    - a hosted service;
    - built-in non-US employee-monitoring compliance;
    - gateways beyond agentgateway and LiteLLM;
    - a developer-side git hook;
    - signed or tamper-evident results;
    - Agent Trace export;
    - forges other than GitHub;
    - production-grade high availability;
    - defending against deliberate evasion (pending the owner's decision).
- **Success metrics** (problem.md M1–M10; targets to be set in specification):

  | # | Metric | Baseline |
  |---|---|---|
  | M1 | Line-classification accuracy on the published scenario set | Spec 002: 59/59 |
  | M2 | False "human" rate after formatters | Unknown |
  | M3 | History-rewrite survival | Spec 002: 30/30 |
  | M4 | Number of tools covered with no per-tool or per-machine install | |
  | M5 | Blind-spot honesty: unobserved or failed captures reported as such, never as "human" | |
  | M6 | No code or prompts retained | |
  | M7 | Time to first result for an adopter or blog reader | |
  | M8 | Reproducibility | |
  | M9 | External adoption (qualitative) | |
  | M10 | Overhead | Spec 002: ≤ 0.133 s per change |

  **Add for the release bar:** the false "AI, modified" rate, reported separately for anchored and broad matches.
- **Carried-forward open questions**:
  1. **Tools in scope.** Which coding tools must be covered? Claude Code, Codex CLI, Gemini CLI and OpenCode
     route through a gateway. Copilot does for chat, agent and CLI only. Cursor does for chat and agent only,
     and calls custom endpoints from its own servers. (problem.md Open Question 6)
  2. **Class definitions and thresholds.** Similarity thresholds per tier; how confidence is expressed; how
     indeterminate lines are handled in percentages; how the four outcomes map to Agent Trace's `ai` / `mixed` /
     `human` / `unknown`. (problem.md Open Question 4)
  3. **Acceptable error targets** for M1, M2 and the false "AI, modified" rate: the numbers for the release bar.
     (problem.md Open Question 5)
  4. **Per-developer view in a fresh install.** On or off by default, and who may see it.
  5. **Evasion.** Is defending against deliberate evasion in or out of scope? (problem.md Open Question 7; signed
     results are already out, in Option C)
  6. **PR-author ↔ gateway-user identity mapping** in a real enterprise. The demo can control it; real
     deployments can't. (concept assumption 5)
  7. **A similarity-preserving keyed fingerprint** for short lines, with acceptable leakage. (concept assumption 9)
  8. **The labelled scenario set**: its composition and size, and where it's measured, now that the homelab
     validation environment is gone. (concept assumption 10; problem.md Open Question 9)
  9. **Real-traffic validation** of capture for each in-scope tool and provider, including whether Codex sends
     `apply_patch` freeform and Claude Code's full edit-tool set. (problem.md Open Question 11)
  10. **agentgateway 1.6.0's native-Gemini tool-call gap**: close it upstream, work around it, or report it as
      *not observed*. (concept assumption 4)
  11. **Fidelity of generated demo traffic.** It must use real streaming formats plus realistic human edits.
      (concept assumption 11)
  12. **Dependency choices** for the bundled stack that avoid Bitnami-style breakage. (concept assumption 13)
  13. **Relationship to git-ai and Agent Trace** after git-ai's move to OpenAI: build on it, interoperate, or
      neither. (problem.md Open Question 8)
  14. **Maintainer commitment and cadence**, including calibration upkeep. (problem.md Open Question 10)
  15. **Repository constitution.** This is the prerequisite above. (problem.md Open Question 12)

### Suggested input for `/speckit-specify`

> Build an open-source, self-contained reference stack for AI-code attribution at an AI gateway, for enterprise
> platform teams and for practitioners exploring what an AI gateway enables. One install brings up the adopter's
> choice of agentgateway or LiteLLM, storage, ingest buffering, dashboards, a GitHub App PR check and a sample
> repository. Demo traffic can be generated with no model or key, or driven by the adopter's own hosted API key.
>
> The gateway records keyed fingerprints of code the model produced, never the code or prompts. On each PR, every
> added line is classified as AI unmodified, AI modified (with confidence), human or indeterminate. Matching uses
> three tiers: exact with normalization, anchored similarity, and broad similarity. Broad matches are always
> shown separately. Interactions the gateway can't see are reported as "not observed", and capture failures are
> visible.
>
> Results are reported per change, per repository and as team totals, with drill-down per developer. The matching
> method ships as a versioned library released on GitHub, so results are reproducible. Out of scope: other
> gateways, a developer-side hook, signed results, Agent Trace export, other forges, production high availability,
> and style-based inference.
>
> Release bar: no publication until a published scenario set shows an acceptable false "AI, modified" rate
> (anchored and broad separately), acceptable accuracy, and no silent capture loss. See
> `.specify/assessments/gateway-code-attribution/` for the full assessment.
