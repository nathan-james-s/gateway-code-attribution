# Problem Definition: Trustworthy, tool-neutral AI-code attribution that organizations can run themselves

- **Slug**: gateway-code-attribution
- **Created**: 2026-10-14
- **Inputs used**: intake.md, research.md (including the 2026-10-14 follow-up and the streamed tool-call probe),
  and `docs/handoffs/gateway-fingerprint-attribution.md`, cited by both

> **Framing note.** The idea arrived as a solution: fingerprint model output at the AI gateway, match it at PR
> time, and ship it as a Helm chart with a versioned algorithm library. This document works back to the problems
> those choices are meant to solve, and keeps the gateway, chart and library out of the problem statement.
> "Self-contained, deployable by others" and "versioned, reusable algorithm" appear below as **outcomes**. How to
> deliver them is for `/speckit-assess-shape`.
>
> **Owner decisions, 2026-10-14** (answers to the first open questions):
> 1. The **first adopters** are **enterprise platform teams**, and practitioners who want to see what is possible
>    with an AI gateway. A blog post by the owner will accompany the release.
> 2. **Reporting levels:** per change, per repository and team totals, with the ability to drill down per
>    developer.
> 3. **Jurisdiction:** this is a **US-based project**. It is not designed around GDPR or works-council rules.
> 4. **Demand:** the owner is a target adopter, the owner's company is a target adopter, and the owner reports
>    similar interest among enterprise IT teams in the industry.

## Problem Statement

Enterprise platform teams that let developers use several AI coding tools can't reliably tell, **line by line and
across all their tools**, which code in a change came from model output, which was changed afterwards, and which
was written by a person. What they have today is one of four things:
- self-reported surveys that disagree with direct measurement by more than 10×;
- vendor dashboards that each cover only one tool;
- tools that must be installed on every developer machine or wired into every tool;
- inference classifiers that judge blocks of code, not lines.

None of these lets an organization produce a defensible, vendor-neutral attribution result **on infrastructure it
controls**. It matters now because:
- AI-generated code is already a large and contested share of commits;
- open-source and enterprise policies increasingly require declaring it;
- the leading open-source option's maintainers have just joined a single AI vendor (OpenAI, September 2026).

## Affected Users & Stakeholders

- **Primary users (owner decision, 2026-10-14)**
  - **Enterprise platform and AI-governance teams** that run or are evaluating central AI infrastructure for many
    developers. They need attribution across every tool they allow, without maintaining a separate integration or
    install for each one. — [owner: the owner and the owner's company are target adopters, and the owner reports
    similar industry interest among enterprise IT teams; research: handoff section 2; vendor market in Users &
    Demand] (evidence: two named adopters, stated; industry interest stated by the owner, not independently
    sourced)
  - **Practitioners exploring what an AI gateway makes possible**, including readers of the owner's companion
    blog post. They want to see and try the capability end to end without building it themselves. — [owner,
    2026-10-14] (evidence: stated)
- **Secondary users (not the first focus)**
  - **Engineering leaders** measuring AI adoption and impact. They need numbers that hold up when compared with
    surveys and vendor claims (42% self-reported vs. 1.9–27% measured). — [research: Users & Demand; Jellyfish,
    DX, Span, Exceeds, git-ai Teams tier] (evidence: vendor-stated demand)
  - **Open-source maintainers** whose projects require AI disclosure (Linux kernel `Assisted-by:`, Fedora, curl)
    or ban AI code (Gentoo, NetBSD). Today they rely on contributors' unchecked declarations. — [research: Users &
    Demand] [NEEDS CLARIFICATION: is there any evidence maintainers want *verified* or *line-level* attribution,
    rather than declarations? None was found.]
  - **Compliance, security and IP owners** who need to know where AI-written code enters sensitive repositories.
    — [research: Span/Sacra positioning, low confidence] [NEEDS CLARIFICATION: no direct evidence of this need]
- **Affected, but not adopters**
  - **Developers.** They are the *subjects* of attribution: a wrong label, such as their reformatted AI code
    counted as "human" or their own code counted as "AI", misrepresents their work. Per-developer drill-down makes
    results HR-adjacent. — [handoff section 4.8; owner decision 2026-10-14 (per-developer drill-down)]
- **Stakeholders**
  - **The project owner and maintainer(s).** They decide scope and carry the maintenance load. The team appears to
    be one person. — [intake; research: Evidence Against #7] [NEEDS CLARIFICATION: intended maintainer capacity]
  - **Adopters' security, legal and HR functions.** They decide, inside each adopting company, who may see
    per-developer results. — [handoff section 4.8] (The project is US-based and isn't designed around GDPR or
    works councils; owner decision 2026-10-14. Research on those rules is kept for adopters elsewhere.)
  - **Upstream communities** whose projects an adopter would depend on, including AI gateways and the Agent Trace
    specification. Their roadmaps and gaps limit what is achievable, for example agentgateway 1.6.0's missing
    native-Gemini tool-call capture. — [research: Probe; Prior Art]
  - **AI tool vendors** (GitHub, Cursor, OpenAI/Codex with git-ai, Anthropic). Their native metrics compete with
    this, and their routing rules decide which interactions an organization can observe at all. — [research:
    Market & Context; Evidence Against #2 and #9]
  - **Adopting organizations' decision-makers**, who choose whether to deploy and fund it. [NEEDS CLARIFICATION:
    who signs off on adopting an open-source attribution system inside a company: platform, security, legal?]

## Goals

1. **Line-level attribution with four outcomes.** Each added line in a change is classified as *AI, unmodified*,
   *AI, modified*, *human*, or *indeterminate*. Results are reported per change and can be rolled up. —
   [handoff section 3; intake]
2. **Tool-neutral coverage.** The result doesn't depend on which AI coding tool produced the code, so adding a
   tool the organization already governs needs no new per-tool or per-machine work. — [handoff sections 1–2]
3. **Honest about blind spots.** Interactions the organization can't observe, such as completions that never
   leave a vendor's own service, are reported as *not observed* or *unknown*, never silently counted as "human".
   Capture failures are visible, not silent. — [research: Evidence Against #2; Probe (silent capture loss);
   spec 002's "never guess" rule]
4. **Robust to how code really changes.** Attribution survives formatting, common or trivial lines, rebases,
   squashes and cherry-picks without systematic mislabelling. — [handoff section 4; research: Data & Constraints]
5. **Privacy-preserving by default.** Attribution doesn't need anyone to keep copies of developers' code or
   prompts. The adopting organization can control who sees per-developer results. — [handoff section 4.8]
5a. **Results at the levels adopters manage.** Results are available **per change, per repository and as team
   totals**, with **drill-down to individual developers**. — [owner decision 2026-10-14]
6. **Reproducible and reusable.** The same inputs and the same algorithm version always give the same result.
   Results from earlier algorithm versions stay interpretable. Other projects can reuse the attribution method
   independently, as a versioned artifact. — [intake (owner: "versioned release"); handoff section 4.1]
7. **Self-contained and easy for others to try.** Someone other than the owner can stand up a complete, working
   example on their own infrastructure, with everything it depends on, and see attribution on a sample change
   without assembling parts themselves. That includes a reader following the companion blog post. — [intake
   (owner: "out of the box", "all that they would need"); owner 2026-10-14]
8. **Open and vendor-neutral.** Published under an open-source license, usable without a paid tier, and not tied
   to one AI vendor. — [intake; research: Prior Art (git-ai's move to OpenAI; its self-hosted server sits in a
   paid tier)]

## Non-Goals

- **Inferring authorship from code style.** No ML classifiers or stylometry, and no attribution without a record
  of what the model actually produced. — [research: Prior Art (Span, stylometry); spec 002 precedent]
- **Watermarking model output.** It needs control over generation, which adopters using hosted models don't have.
  — [research: Prior Art]
- **Legal ownership, copyright or licence determination.** Agent Trace makes the same exclusion. — [research:
  Prior Art]
- **Judging code quality, productivity, ROI or developer performance.** Attribution measures provenance only.
  What adopters do with it is their policy. — [research: Evidence Against #8]
- **Attributing interactions that never pass through anything the organization controls**, such as Copilot
  inline completions, Cursor Tab/Composer, or chat output pasted from elsewhere. These are reported as blind
  spots (Goal 3), not solved. — [research: Market & Context]
- **Operating a hosted service.** The deliverable is something others run themselves. — [intake]
- **Homelab-specific constraints and hardware.** These were dropped by the owner on 2026-10-14. — [intake]
- **Building in compliance with non-US employee-monitoring law** (GDPR, works councils). The project is US-based.
  Adopters in other jurisdictions are responsible for their own compliance. — [owner decision 2026-10-14]
- [NEEDS CLARIFICATION: Is **defending against deliberate evasion** out of scope? Examples: a developer
  laundering AI output through edits, or routing around governed infrastructure. Spec 002 assumed cooperating
  users, but that assumption came with the homelab constitution, which no longer applies.]
- [NEEDS CLARIFICATION: Is **tamper-evident, signed or verifiable results** out of scope for a first version?
  Spec 002 signed its records.]

## Success Metrics

| # | Signal | Baseline | Target |
|---|---|---|---|
| M1 | **Line classification accuracy** on a shared, published scenario set (share of added lines labelled correctly across the four outcomes) | Spec 002 (hook-based, lab): 59/59 lines correct, 0 wrong. Cursor's API is directional only. Span claims ~95%, block-level. | [NEEDS CLARIFICATION] |
| M2 | **False "human" rate for AI lines after a formatter runs** (Prettier, Black, gofmt, and harness-internal formatters) | Unknown. Cursor documents formatter breakage; no published data. | [NEEDS CLARIFICATION] |
| M3 | **History-rewrite survival**: AI lines still attributed after rebase onto a moved base, squash merge and cherry-pick | Spec 002: 30/30 kept, 0 misattributed | [NEEDS CLARIFICATION] |
| M4 | **Covered tools**: number of AI coding tools whose governed interactions are attributable, with no per-tool or per-machine install | Per-vendor dashboards cover 1 tool each. Hook tools need an install per machine and an adapter per tool. | [NEEDS CLARIFICATION: which tools are in scope] |
| M5 | **Blind-spot honesty**: share of unobserved or failed captures reported as such rather than as "human" | Unknown for existing tools. In the probe, agentgateway dropped capture silently on schema-deviant streams. | 100% (qualitative target; [NEEDS CLARIFICATION]) |
| M6 | **Code and prompt retention**: amount of developer source code or prompt text the system keeps | Some precedents keep full code (TensorZero example); git-ai stores prompts locally | None (owner direction in handoff section 3; [NEEDS CLARIFICATION: confirm]) |
| M7 | **Time to first result** for a new adopter or blog reader: from nothing to seeing attribution on a sample change, following the published instructions | Unknown. git-ai's self-hosted server sits in a paid tier; Langfuse is a precedent for a bundled stack. | [NEEDS CLARIFICATION] |
| M8 | **Reproducibility**: re-running attribution on the same change with the same algorithm version gives identical results | n/a | 100% |
| M9 | **External adoption** (qualitative / leading indicator): independent deployments, outside issues or contributions, forks | 0 (project not yet published) | [NEEDS CLARIFICATION] |
| M10 | **Attribution overhead**: added latency to model responses and to PR checks | Spec 002: ≤ 0.133 s per change, ≤ 0.119 s per commit (p95), hook-based | [NEEDS CLARIFICATION] |

## Cost of Inaction

If nothing is built, organizations keep using what they have today:
- self-reported surveys whose AI-share figures disagree with direct measurement by more than 10×;
- per-vendor dashboards (Copilot metrics, Cursor's Enterprise-only alpha API, Claude Code telemetry), each limited
  to one tool and aggregated rather than per line;
- block-level ML detectors whose accuracy figures are mostly the vendors' own;
- unchecked commit trailers (`Assisted-by:`, `Co-Authored-By:`);
- hook-based tools that need an install on every machine. The most prominent, git-ai, now has its maintainers on
  OpenAI's Codex team, and its self-hosted server sits in a paid tier.

The owner's employer would evaluate a company-wide gateway with **no open, vendor-neutral way** to attribute code
across the tools it governs. OSS maintainers keep relying on declarations.

**The cost of inaction is not severe for everyone.** Organizations happy with one tool's dashboard, or with
git-ai's hooks, already have a workable answer. The gap is specific: **multi-tool, line-level, self-run,
vendor-neutral**. That is the gap enterprise platform teams evaluating central AI gateways would hit. The owner
and the owner's company are two such adopters, and the owner reports similar interest among enterprise IT teams.
Beyond them, the size of this group isn't independently evidenced (research: demand evidence is
low-confidence). — [research: Market & Context; Users & Demand; Evidence Against #1 and #9]

## Open Questions

1. ~~Demand evidence.~~ **Resolved 2026-10-14 (owner):** the owner and the owner's company are target adopters,
   and the owner reports similar interest among enterprise IT teams. *Residual risk for `/speckit-assess-decide`:*
   demand beyond these two adopters isn't independently evidenced.
2. ~~Primary adopter.~~ **Resolved 2026-10-14 (owner):** enterprise platform teams first, plus practitioners
   exploring what an AI gateway makes possible. A companion blog post will accompany the release.
3. ~~Default granularity of results.~~ **Resolved 2026-10-14 (owner):** per change, per repository and team
   totals, with drill-down per developer. The project is US-based and not designed around GDPR or works councils.
   - [NEEDS CLARIFICATION: Should the per-developer view be **on or off by default** in a fresh install, and who is
     expected to be allowed to see it?]
4. [NEEDS CLARIFICATION: **Class definitions.** What exactly makes a line "AI, modified" rather than "human"? How
   should confidence be expressed? Do indeterminate lines stay out of percentages or take their neighbours'
   label? And how do the four outcomes map to Agent Trace's `ai` / `mixed` / `human` / `unknown`?]
5. [NEEDS CLARIFICATION: **Acceptable error.** What accuracy (M1), formatter false-human rate (M2) and coverage
   (M4) would an adopter accept before trusting the numbers?]
6. [NEEDS CLARIFICATION: **Tools in scope.** Which AI coding tools must be covered for this to be useful, knowing
   that Copilot inline completions and Cursor Tab can't be observed by anything the organization controls?]
7. [NEEDS CLARIFICATION: **Evasion and verifiability.** Are deliberate evasion, and signed or tamper-evident
   results, in or out of scope (see Non-Goals)?]
8. [NEEDS CLARIFICATION: **Relationship to git-ai and Agent Trace.** After git-ai's move to OpenAI, is there room
   to build on, fork, contribute to or interoperate with it? Is Agent Trace the output format to support?]
9. [NEEDS CLARIFICATION: **Validation environment.** With the homelab dropped, where are M1–M3 and M10 measured?
   Is spec 002's scenario set reused as the benchmark?]
10. [NEEDS CLARIFICATION: **Maintainer commitment.** What release cadence, support and team size can the project
    sustain for something others deploy?]
11. [NEEDS CLARIFICATION: **Real-traffic validation.** The probe used synthetic streams. Recorded traffic from real
    providers and real coding tools (Claude Code, Codex, Gemini CLI, OpenCode) is still needed to confirm the
    capture assumptions behind Goals 2–3.]
12. [NEEDS CLARIFICATION: **Governance of the repo.** Does it get its own constitution? The `ai-gateway` v1.1.1
    constitution no longer applies.]
