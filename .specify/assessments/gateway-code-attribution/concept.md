# Concept: Gateway-sourced AI-code attribution, shipped as a self-contained reference stack

- **Slug**: gateway-code-attribution
- **Created**: 2026-10-14
- **Recommended option**: Option B — Reference stack with full four-class attribution (exact, anchored-modified
  and broad-fuzzy matching), staged toward Option C on evidence

Inputs: `problem.md` (goals G1–G8 and G5a, metrics M1–M10, owner decisions of 2026-10-14), `research.md`
(including the streamed tool-call probe) and `intake.md`. Primary adopters: enterprise platform teams, and
practitioners exploring what an AI gateway makes possible, via the owner's companion blog post.

**Owner decisions on shaping, 2026-10-14:**
1. **Both probed gateways are supported** (agentgateway and LiteLLM). The adopter chooses which one to deploy.
2. **Demo traffic:** the stack can **generate demo traffic itself**, with no model or key needed, or the adopter
   can **bring their own hosted API key** to run real agents.
3. **Forge:** **GitHub first, with the PR check delivered as a GitHub App.**
4. **The anchored "AI, modified" class is in Option B.**
5. **Broad fuzzy matching is in Option B.**
6. **Appetite:** the owner judges the larger scope manageable, because AI-assisted engineering compresses build
   time. *Assessment note:* agreed for build effort. What doesn't compress is **calibration and validation**:
   setting similarity thresholds, and measuring false "AI, modified" labels against labelled scenarios and real
   traffic. That stays the schedule risk (see the Option B appetite).

## Options

### Option A — Adopt or contribute instead of build

- **Sketch**: Don't build a new system. An enterprise platform team would choose one of two routes:
  - **Adopt:** git-ai's hook-based attribution (installed per machine and per tool), plus each vendor's native
    dashboard (Copilot metrics, Cursor tracking, Claude Code telemetry).
  - **Contribute:** add a "gateway as capture source" to an existing project. Candidates are git-ai (Apache-2.0)
    or TensorZero's commit-matching example.

  The owner's blog post would then describe what a gateway *could* add, showing the probe results as evidence,
  without shipping a product.
- **Appetite**: small (days) for adopt-and-write-up. Contributing upstream is **unknown**: it depends on
  maintainers accepting a capture source that no longer needs their per-tool hooks, and git-ai's maintainers have
  just joined OpenAI's Codex team.
- **Trade-offs**:
  - **Wins:** no maintenance burden, and git-ai already covers 8+ tools including Copilot and Cursor.
  - **Sacrifices:**
    - G2: git-ai needs an install on every machine.
    - G7: its self-hosted server sits in a paid tier.
    - G8: its future neutrality is uncertain after the OpenAI move.
    - G3: per-vendor dashboards stay one tool each and aggregate only.
  - Doesn't serve the stated first adopter: a platform team that already centralizes AI traffic.
  - Leaves the owner's employer evaluation with no vendor-neutral option.
- **Rabbit holes**: upstream politics and roadmap alignment, and waiting on maintainers whose priorities just
  changed.

### Option B — Reference stack with full four-class attribution

- **Sketch**: One install, on a cluster or a laptop, brings up a working example. It includes the adopter's
  **choice of AI gateway** (agentgateway or LiteLLM), storage, ingest buffering, dashboards and a PR check
  delivered as a **GitHub App**. A sample repository comes with two ways to make traffic: a **built-in demo-traffic
  mode** that needs no model or key, or **the adopter's own hosted API key** to drive real agents. Either way, a
  blog reader sees results within one sitting.
  - **Day-to-day:** developers point their coding tools at the gateway and do nothing else. When a PR opens, the
    check reports per-line results in all four outcomes: **AI, unmodified**, **AI, modified**, **human** and
    **indeterminate**. Every "AI, modified" result carries a **confidence level**. The dashboards show totals
    per change, per repository and per team, with drill-down per developer.
  - **Matching runs in three tiers, strongest evidence first:**
    1. **Exact**, with whitespace- and formatting-tolerant normalization → *AI, unmodified*.
    2. **Anchored similarity**: exact matches in the same file pin down the generating model output, and the
       line is highly similar to a line in that output → *AI, modified*, **high confidence**.
    3. **Broad similarity**: the line is similar to captured output from the same developer and time window, with
       no exact-match anchor → *AI, modified*, **lower confidence**.

    Anything below the thresholds falls back to *human* or *indeterminate*: **never guess**.
  - **Broad matches are kept distinct.** They are never blended silently into the headline numbers. An adopter
    or blog reader can always see results **with and without** broad matches.
  - **What gets recorded:** keyed fingerprints of the code the model produced, including the similarity-preserving
    form that tiers 2–3 need, but **never the code or prompts**.
  - **Not covered:** interactions the gateway can't see, which are reported as **not observed** rather than
    "human".
  - **Library:** the fingerprinting and matching method ships as its own versioned release, so the same version
    gives the same answer anywhere.
  - **Coverage signal:** capture failures are visible on a coverage panel.
- **Appetite**: **medium-to-large.** At a conventional pace for one maintainer the assessment would budget roughly
  **8–14 weeks**. The extra over the earlier 6–10 weeks is the similarity fingerprinting, the two similarity tiers
  and their calibration. **The owner judges this manageable with AI-assisted engineering** (decision 6). The part
  that doesn't compress is **calibration and validation**: building a labelled scenario set, recording real
  traffic, tuning thresholds and measuring the false "AI, modified" rate. Budget for that explicitly, whatever
  the build speed.
- **Trade-offs**:
  - **Wins:**
    - **G1 fully met**, with all four outcomes from day one, so edited AI lines are no longer counted as "human".
    - G2: nothing per machine, nothing per tool for tools routed through the gateway.
    - G3: honest blind spots, and confidence-labelled "modified" results.
    - G5: no code retained.
    - G5a: the requested reporting levels.
    - G6: reproducible, versioned method.
    - G7: try-it-yourself.
    - G8: open.
  - It addresses formatter drift (M2) on two fronts: loose normalization, plus similarity matching for what
    normalization misses.
  - It exercises the hardest unknowns early in a controlled environment: linking a PR to gateway traffic, and
    similarity without guessing.
  - **Sacrifices:**
    - **False "AI, modified" labels become possible.** Broad matching can credit common patterns, or another
      session's output, to AI. This is the false attribution the design review ranks most harmful, now in the
      AI direction. Separating tiers and showing confidence limit the damage; they don't remove it.
    - **Privacy margin narrows.** Similarity-preserving fingerprints reveal more about short lines than
      whole-line keyed hashes do. Keeping them keyed protects against outsiders, not against the key holder.
    - **Two gateways must give identical results**, now including similarity results, or results stop being
      comparable. Adopters on a third gateway (Envoy AI Gateway, Portkey, Kong) still need an adapter later.
    - **The blog's headline number depends on thresholds.** It must be published with the method version and
      the with/without-broad split.
- **Rabbit holes**:
  - **Calibrating similarity thresholds** so tier 3 neither guesses nor collapses into "human". This needs labelled
    data: edits, refactors, formatter output and unrelated code that resembles AI output. It is the top schedule
    risk.
  - **Which captured output a broad match may be compared against** (developer, time window, repository) when the
    PR side has no session ID. A window too wide gives false positives; too narrow and tier 3 adds nothing.
  - **Choosing a similarity-preserving keyed fingerprint** (token shingles, MinHash-style sketches, edit-distance
    proxies) that works for short lines and doesn't leak too much.
  - **Linking PRs to gateway traffic** (git author → gateway user, time window, file path). The demo can control
    the identity mapping; real enterprises can't. Keep the demo simple and make the enterprise mapping an
    explicit open item.
  - **Gateway parity.** Each gateway exposes captured tool calls through a different mechanism, with different
    gaps. agentgateway 1.6.0 doesn't capture native-Gemini tool calls, and it can drop capture silently on
    streams that don't match its schema. The two can drift apart on edge cases, such as truncated calls, or
    differ in coverage reporting. Keeping them at parity needs a shared test suite run against both.
  - **Demo traffic that is realistic but needs no model.** Generated traffic must look like real agent tool
    calls (edit, write and patch formats, for each API) and include realistic human edits, so that every
    matching tier is exercised honestly. It must not fake results downstream. A bring-your-own-key path depends
    on each provider's terms and costs for the adopter.
  - **Per-tool response parsing** (Claude Code, Codex `apply_patch`, OpenCode tools) vs. fingerprinting all
    code-bearing text. File paths from tool calls sharpen anchoring, but schema-specific parsing is where scope
    grows.
  - **Common and trivial lines** (stoplist, minimum run length) can quietly dominate accuracy, more so with
    similarity matching.
  - **Ingestion timing:** PRs opened before capture catches up look all-human.
  - **Dependency charts and images** (the Bitnami change) and keeping a multi-component install patched.
  - **Silent capture loss** on streams that don't match the gateway's schema (probe finding). The coverage
    signal must be real, not cosmetic.

### Option C — Production-grade attribution platform

- **Sketch**: Everything in Option B, plus:
  - **Gateways beyond the two in Option B**, through adapters.
  - An optional **developer-side hook** for earlier feedback.
  - **Signed, verifiable results.**
  - Export to **Agent Trace**.
  - Configurable exclusion rules beyond sensible defaults.
  - **Production-grade** defaults: high availability, retention policies, role-based access to per-developer
    views.
  - Several forges.

  An enterprise platform team could run it as a supported internal service, not only as a reference stack.
- **Appetite**: large (months). Confidence is low until Option B's measurements and adopter feedback exist.
- **Trade-offs**:
  - **Wins:** improves M4, adds verifiability and is closest to what an enterprise would adopt as-is.
  - **Sacrifices:** a long time before a public, blog-ready release, and much higher maintenance load for a
    likely single maintainer (research: Evidence Against #7).
- **Rabbit holes**:
  - Parity across more than two gateways, each with different gaps.
  - Signing and key custody.
  - High-availability packaging.
  - Supporting several forges.
  - Mapping enterprise identities at scale.

## Recommendation

**Option B, with full four-class attribution, staged toward Option C.**

- **Fits the first adopters.** Option B serves both of them. An enterprise platform team that already
  centralizes AI traffic gets attribution with **no per-machine or per-tool install** (G2) and **no retained code**
  (G5), at the **reporting levels requested** (G5a). A blog reader can **stand it up and see it work** (G7, M7).
- **Meets the core goal from the start.** It produces **all four outcomes** (G1), so the core value, telling AI
  from mixed code, is present at launch rather than deferred.
- **Shows its limits.** It is **honest about blind spots and confidence** (G3, M5).
  - The probe shows capture can fail silently, so a visible coverage signal is a must-have.
  - Broad similarity matches stay separate and confidence-labelled, which keeps the never-guess principle while
    widening coverage.
- **Has the evidence it needs.** The streamed tool-call probe shows that capture works on the main formats.
- **Defers only what doesn't serve the first adopters yet:** gateways beyond two, signing, Agent Trace export,
  production high availability and other forges.
- **Why not Option A:** it fails G2, G7 and G8 for the stated adopter.
- **Why not Option C now:** its extra scope is about running in production and verifiability, which the first
  release doesn't need. It would delay the public release and the blog post.

**Release bar for Option B.** Targets are to be set in specification (problem.md M1, M2, M5). Option B shouldn't
be published, or the blog's headline numbers quoted, until it shows all of the following on the published scenario
set:
- an acceptable **false "AI, modified" rate**, measured separately for anchored and broad matches;
- acceptable overall accuracy;
- coverage reporting with no silent capture loss.

**Graduation to Option C**, a later shaping pass, if Option B shows both of the following:
- at least one adopter outside the owner, such as the owner's company, runs it and asks for production features;
- the measured error profile is stable enough to justify signing or verifying the results.

## Out of Scope (for the recommended option)

**Inherited from problem.md non-goals:**
- style or ML inference (similarity is computed **only against captured model output**, never inferred from style);
- watermarking;
- legal ownership or copyright;
- judging productivity or developer performance;
- attributing interactions that never pass through organization-controlled infrastructure (Copilot inline
  completions, Cursor Tab/Composer, pasted chat output), which are reported as **not observed**;
- a hosted service;
- homelab constraints;
- built-in compliance with non-US employee-monitoring law.

**Newly excluded for Option B (candidates for Option C):**
- support for **gateways beyond agentgateway and LiteLLM**;
- a **developer-side git hook**;
- **signed or tamper-evident results**;
- **Agent Trace export**;
- **forges other than GitHub** (GitHub App confirmed by the owner);
- **production-grade** high availability, scaling and retention tuning beyond a sensible default;
- **defending against deliberate evasion**, pending the owner's decision in problem.md Open Question 7.

## Assumptions to Validate

1. **Four-class attribution with tiered confidence is understandable and useful** to enterprise platform teams
   and blog readers. In particular, they'll read the "with and without broad matches" split correctly. (Validate
   with the owner's company as first adopter.)
2. **The coding tools in scope route through the gateway** with only a base-URL change. Research says yes for
   Claude Code, Codex CLI, Gemini CLI and OpenCode, and partly for Copilot (chat, agent and CLI via BYOK). Cursor
   calls custom endpoints from its own servers, chat and agent only. (Confirm the final tool list, problem.md
   Open Question 6.)
3. **Real provider and tool streams behave like the probe's synthetic streams**: complete, byte-exact arguments
   available to the gateway plug-in. (Validate with recorded real traffic, problem.md Open Question 11.)
4. **Both gateways can produce identical attribution** from the same traffic, including similarity tiers.
   **Decided:** both agentgateway and LiteLLM are supported, and the adopter chooses. To validate: agentgateway's
   native-Gemini gap is either closed upstream, worked around, or reported as **not observed** for Gemini CLI on
   that gateway.
5. **A PR's author can be mapped to gateway users** reliably enough in an enterprise, for example through a shared
   identity provider or email. The demo can control this mapping; real deployments can't. Broad matching depends
   on this more than exact matching does.
6. **Fingerprinting code-bearing response text without parsing each tool's schema** gives acceptable precision for
   all three tiers. Otherwise per-tool parsing comes back at the gateway.
7. **Capture keeps up with PR timing** (ingest latency well below the time from generation to PR), or a "pending"
   result is acceptable.
8. **Keyed fingerprints are acceptable** even though they rule out offline lookup from a plain file copy (a spec
   002 capability).
9. **A similarity-preserving keyed fingerprint exists** that supports anchored and broad matching on short lines
   with acceptable leakage, without storing code. (Validate in specification with a small comparison of
   candidates.)
10. **A labelled scenario set can be built**, covering unmodified AI lines, human edits of AI lines, formatter
    output, refactors, unrelated look-alike code and human code, large enough to set thresholds and measure the
    false "AI, modified" rate. (This is the release bar's dependency.)
11. **Generated demo traffic is faithful enough** to exercise the real capture path and every matching tier.
    **Decided:** generated demo traffic, or bring your own hosted API key. To validate: it reproduces each API's
    real streaming tool-call format, plus realistic human edits.
12. **A GitHub App can deliver the PR check** with the permissions and events it needs (PR opened and
    synchronize, check runs), installable by an enterprise platform team. **Decided:** GitHub App, GitHub first.
13. **The bundled dependencies can avoid Bitnami-style breakage** with maintained images and charts. [Validate in
    specification.]
14. **One maintainer, with AI-assisted engineering, can sustain** Option B's release, patch and calibration
    cadence (owner decision 6; problem.md Open Question 10).
