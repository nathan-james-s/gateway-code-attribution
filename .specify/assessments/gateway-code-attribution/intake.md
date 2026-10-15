# Idea Intake: Gateway-sourced AI-code attribution, packaged as an open-source out-of-the-box stack

- **Slug**: gateway-code-attribution
- **Created**: 2026-10-14
- **Source**: pasted text (owner's message, 2026-10-14) + repo path `docs/handoffs/gateway-fingerprint-attribution.md` (handoff written 2026-10-13 from the `ai-gateway` homelab project, commit `4287d2e`)
- **Type**: new-capability

## Idea (as captured)

**Core idea**, from the handoff (section 1, owner's words):

> Fingerprint lines of code at the AI gateway as they come from the model, then do that fingerprinting again at
> git hook / PR push time, so we can determine what code is AI, mixed, or human created.

The handoff adds that the point is line-level AI attribution **without depending on any harness plugin or hook**,
so it works the same for Claude Code, GitHub Copilot, Cursor, OpenCode and future tools, at the scale of thousands
of developers.

**Scope and audience**, from the owner's message for this intake (verbatim, `@docs` reference refers to the handoff
above):

> This will be something that can be used by people other than me, so not just a learning place. This will end up
> getting published to open-source, so others can see and use it. Like some companies do, I want this to be an out
> of the box solution. So if someone wanted for example to deploy a helm chart, we would have all that they would
> need to get an example of this spun up with its database, queue, ai gateway, grafana for dashboarding, etc. The
> algorithm library would be a versioned release on the github repository.

No secrets or credential-bearing URLs appeared in either source. No URLs were fetched; the handoff's prior-art
links (section 7) are recorded there and were not followed.

## Restated

Build an open-source system that records keyed per-line fingerprints of model output as it passes through an AI
gateway, then fingerprints a pull request's added lines the same way and matches them to classify each line as AI
(unmodified), AI (modified), human, or indeterminate, with no per-harness plugins. Ship it as an out-of-the-box
deployable example (e.g. a Helm chart bringing up the gateway, database, queue and Grafana dashboards), with the
shared fingerprinting/matching algorithm library published as versioned releases on the GitHub repository.

## Origin & Context

- **Raised by**: The repository owner (author of the `ai-gateway` homelab project, specs 001 and 002).
- **Trigger**:
  - The owner's employer is evaluating a company-wide AI gateway (handoff section 2).
  - Spec 002's working attribution tool (`aiattr`) depends on per-harness capture (Claude Code hooks, an OpenCode
    plugin), which at enterprise scale means an adapter per harness, managed installs on every machine, and no
    coverage for tools without hooks (handoff section 2).
  - A 2026-10-13 prior-art search found the matching technique in use (e.g. aigit) but never sourced from a
    gateway (handoff sections 2 and 7).
  - New in this intake: the owner wants this to be a public, reusable open-source product, not only a learning
    project — which shifts it away from the homelab-report framing of specs 001 and 002.
- **Supporting material**: The handoff contains the concept flow, a design review of what can skew results
  (sections 3–4), the homelab inventory (section 5), spec 002's measured baseline (section 6), lab findings
  (section 8), hard problems (section 9) and open questions (section 10). Later stages should read it in full.

### Owner clarification (2026-10-14, at the start of research)

> The homelab does not apply to this anymore. We are moving from homelab learning to creating a self-contained
> implementation of the idea.

So the homelab hardware, its agentgateway deployment, and the harness machines in handoff section 5 are no longer
the target or test bed. The homelab-specific constraints in handoff section 11 are **not** assumed to carry over.
The handoff stays useful for its design review (section 4), lab findings (section 8), and spec 002's baseline
(section 6). Whether to reuse spec 002's code or record format is still open. The homelab-related unknowns below
are kept for traceability and marked resolved.

### Handoff open questions this message appears to address

Recorded as the owner's stated direction, not as decisions validated by assessment:

- *Goal: learning/report vs. enterprise-adoptable design* (handoff section 10) → the owner says usable by others,
  published open-source, "not just a learning place".
- *Reuse the homelab or start fresh?* → partially addressed: the deliverable is a self-contained deployable example
  (Helm chart). Whether the homelab still serves as the test bed is not stated.

## First-Glance Unknowns

**Product and packaging (raised by the new scope)**

- [NEEDS CLARIFICATION: Who is the target adopter — individuals/homelabbers, platform teams at companies, or both?
  What does "out of the box" have to mean for them: a demo/reference stack, or something intended for production use?]
- [NEEDS CLARIFICATION: Which AI gateway ships in the stack — agentgateway (as in the homelab), a different one, or a
  pluggable gateway integration so adopters can use LiteLLM/Portkey/Kong/etc.?]
- [NEEDS CLARIFICATION: Which database and queue — and are they meant to be swappable?]
- [NEEDS CLARIFICATION: Does the example stack include a model host (e.g. Ollama) so it works end to end with no
  external provider, or does it assume the adopter brings model access?]
- [NEEDS CLARIFICATION: Is Helm/Kubernetes the only deployment target, or also Docker Compose / Podman for a quicker
  local spin-up? Which Kubernetes distributions must it work on?]
- [NEEDS CLARIFICATION: How does the PR check ship — a GitHub App, a GitHub Action, a webhook service in the chart,
  or several? Which forges beyond GitHub, if any?]
- [NEEDS CLARIFICATION: Algorithm library — what language(s)? Since both the gateway side and the PR side must use one
  shared normalisation implementation (handoff section 4.1), how do non-native consumers use it? Is it published
  to a package registry (PyPI, npm, crates.io, container images) in addition to GitHub Releases?]
- [NEEDS CLARIFICATION: Versioning policy — how do library releases relate to the fingerprint `algo_version` stored
  on each row, and to chart releases?]
- [NEEDS CLARIFICATION: Open-source license, and whether any prior-art code (e.g. aigit, license not stated) or
  spec 002's `aiattr` code would be reused.]
- [NEEDS CLARIFICATION: What Grafana dashboards are expected, and who is allowed to see per-developer results in a
  default install (handoff section 4.8 flags this as HR-adjacent data)?]
- [NEEDS CLARIFICATION: How does a default install manage the HMAC key (generation, storage, rotation), and is HMAC
  vs. plain hashes still open (handoff section 10)?]

**Constraints and governance**

- ~~[NEEDS CLARIFICATION: Do the carried-over `ai-gateway` constitution constraints still apply (handoff section 11) —
  e.g. "runs on the owner's existing hardware", "no OpenShift", "success must be met with local models" — given the
  goal is now a product others deploy? Does the repo get its own constitution?]~~ **Resolved 2026-10-14:** the
  homelab constraints do not carry over. Still open: whether the repo gets its own constitution.
- ~~[NEEDS CLARIFICATION: Is the homelab still the validation environment ...]~~ **Resolved 2026-10-14:** no. Still
  open: what the validation environment is (e.g. the shipped example stack itself), and whether spec 002's
  scenario set (handoff section 6) is reused as the benchmark.
- [NEEDS CLARIFICATION: Expected maintenance commitment once published (issues, releases, support for adopters).]

**Carried over from the handoff, still open** (sections 9–10)

- [NEEDS CLARIFICATION: How a PR is linked to gateway traffic (git author → gateway user, time window, file path,
  org-wide) — the handoff calls this the biggest open design question.]
- [NEEDS CLARIFICATION: Can the chosen gateway read response bodies, including streamed tool-call arguments, without
  an add-on? Unverified in the homelab.]
- [NEEDS CLARIFICATION: Is the PR check the primary variant with the git hook optional?]
- [NEEDS CLARIFICATION: Must results be signed and verifiable like spec 002, or is measured attribution enough at
  first?]
- [NEEDS CLARIFICATION: Are the four categories the reporting model, and how do they map onto Agent Trace's `ai` /
  `mixed` / `human` / `unknown`?]
- [NEEDS CLARIFICATION: Is fuzzy matching acceptable in the first version, or exact matches only?]
- [NEEDS CLARIFICATION: Which harnesses are in scope, and how are traffic paths that bypass the gateway (Copilot inline
  completions, pasted chat output) presented to adopters?]
- [NEEDS CLARIFICATION: Relationship to spec 002 — replace hooks, complement them, or compare head to head?]
- [NEEDS CLARIFICATION: Fingerprint volume and retention defaults for an adopter's install.]
