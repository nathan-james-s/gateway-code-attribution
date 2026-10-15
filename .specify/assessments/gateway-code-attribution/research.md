# Idea Research: Gateway-sourced AI-code attribution, packaged as an open-source out-of-the-box stack

- **Slug**: gateway-code-attribution
- **Created**: 2026-10-14
- **Evidence confidence (overall)**: medium. Prior art and platform constraints are reasonably well evidenced.
  Demand from adopters is **low** confidence: no interviews, and nearly all market signal comes from vendors.

**Scope note.** The owner clarified on 2026-10-14 that the homelab no longer applies. The idea is now a
self-contained, open-source implementation that others deploy. This research therefore leaves out homelab
hardware and constraints, and looks at the idea as a product for third-party adopters.

**How sources were gathered.** Every web claim below comes from **search-result summaries**. No page on a
non-allowlisted host was fetched, and the fetch tool can't pin connections to a validated address, so the URL
Trust Policy rules out direct fetches. Repository metadata (stars, license, last push) came from the GitHub API
via `gh`. A summary is not the primary text, so most web claims are marked **medium** or **low** confidence even
where cited. Later stages should read the primary sources before relying on a specific figure.

**Follow-up, 2026-10-14 (owner-directed).**
1. The owner confirmed fetching the TensorZero write-up, and it was fetched (policy: confirmed-by-user).
2. The owner stated that git-ai and its maintainers were acquired by OpenAI in September 2026. Recorded under
   Prior Art with the public reporting.
3. A **lab probe** of streamed tool-call reassembly was run through LiteLLM 1.105.1 and agentgateway 1.6.0. See
   [Probe: Streamed Tool-Call Reassembly](#probe-streamed-tool-call-reassembly) and
   `probes/streamed-tool-calls/`.

---

## Users & Demand

- **Measured AI share of code is contested, which is a demand for defensible measurement.** Self-reported surveys
  put AI's share of committed code at about 42% (Sonar 2026 State of Code, 1,100+ developers). Direct measurements
  range from 1.9% of enterprise production code (Software Improvement Group, State of Software 2026) to 26.9%
  (a ShiftMag analysis of 4.2M developers, via a secondary summary). Big-tech disclosures (Google "over 30%",
  Microsoft "20–30%") each measure something different (lines accepted, characters completed, and so on). —
  [source: sonarsource.com, softwareimprovementgroup.com, lenz.io / 13labs.au summaries] (confidence: medium;
  cited; figures are secondary)
- **Engineering leaders are a paying audience for AI-impact measurement.** Jellyfish, DX, Span, Exceeds, LinearB
  and Larridin all sell some form of it, and git-ai sells a Teams and Enterprise tier on top of its open-source
  CLI. — [source: jellyfish.co, usegitai.com/pricing, sacra.com/c/span, handoff section 7] (confidence: medium;
  cited; vendor self-descriptions, which signal **stated** market demand, not observed user behavior)
- **Open-source projects now require provenance declarations, at the commit level rather than the line level.**
  The Linux kernel requires an `Assisted-by:` tag (documented in `coding-assistants.rst`; sources date it between
  Dec 2025 and Apr 2026). Fedora (Oct 2025) and curl require disclosure. Gentoo (Apr 2024) and NetBSD ban LLM
  output. QEMU banned it and has a pending relaxation patch (May 2026). A GCC policy (Jul 2026) is reported by a
  single blog. — [source: phoronix.com, opensourceforu.com, ssdnodes.com, youngju.dev summaries] (confidence:
  medium; cited; mostly secondary)
- **The draft attribution standard is drawing early interest.** Agent Trace (Cursor, v0.1.0 RFC, Jan 2026) was
  placed at "Assess" on the Thoughtworks Technology Radar in Apr 2026. Backing from Cognition, Cloudflare, Vercel,
  Google Jules, Amp and OpenCode is reported by one secondary source. — [source: thoughtworks.com/radar,
  infoq.com, morphllm.com] (confidence: medium for the radar placement, low for the backer list)
- **Observed adoption of the nearest open-source tool.** git-ai has 2,840 GitHub stars and was last pushed
  2026-10-12. A third-party profile reported 179 releases in under a year. — [source: GitHub API; rywalker.com]
  (confidence: high for stars and activity, low for the release count)
- **The only direct statement of need for this design is the owner's.** The owner's employer is evaluating a
  company-wide gateway, and the owner identified per-harness hooks as the scaling problem. — [source: handoff
  sections 2 and 9] (confidence: medium; single stakeholder, **stated** want)
- **No evidence was gathered from would-be adopters:** platform teams, OSS maintainers, compliance owners or
  developers. — [ASSUMPTION gap] (see Gaps)

## Prior Art

- **git-ai** (Apache-2.0, 2,840 stars, active) is the strongest open-source precedent. Agents call
  `git-ai checkpoint` when they change files. Line attribution is stored in Git Notes and survives rebase, amend,
  cherry-pick, squash, reset, stash and revert, according to its docs. It provides `git ai blame` and
  `git ai stats`, and one issue lists support for Claude Code, Codex, Copilot, Cursor, Continue, OpenCode,
  Windsurf and Gemini CLI. A **self-hosted SCM app** (webhook receiver, worker and database, docker-compose for up
  to about 100 repos) sits in the paid Enterprise tier per the pricing page, though aggregators say Teams. (On its
  move to OpenAI, see the next entry.) — Why it matters: it already offers wide harness coverage through hooks,
  and it shows the out-of-the-box self-hosted package is something people pay for. —
  [source: github.com/git-ai-project/git-ai, usegitai.com/docs/metrics/self-hosted, usegitai.com/pricing,
  aicatchup.com, Zoo-Code issue #1867] (confidence: high for license and stars, medium for the rest)
- **git-ai has moved to OpenAI.** The owner states that git-ai and its maintainers were **acquired by OpenAI in
  September 2026**. Public reporting (The New Stack, 2026-09-12, "OpenAI hires Git AI") says co-founders Aidan
  Cunniffe and Sasha Varlamov join OpenAI's **Codex** team to give businesses data on coding-agent performance and
  ROI. OpenAI's Thibault Sottiaux said the technology would help businesses understand Codex's impact. The
  reporting calls it a hire and gives no deal terms. **What happens to the Apache-2.0 project is not stated
  anywhere found.** The repo was still being pushed on 2026-10-12. — Why it matters:
  - The leading open-source tool is now tied to one AI vendor's product, which may make a vendor-neutral
    alternative more valuable.
  - The project's future roadmap, maintenance and neutrality are uncertain.
  - The leading model vendor now owns a line-attribution capability, which raises the odds that native features
    overtake the field.

  [source: owner statement 2026-10-14; thenewstack.io/openai-hires-git-ai; aicatchup.com; GitHub API]
  (confidence: high that the team moved to OpenAI; low for the project's future)
- **Cursor AI Code Tracking API** (Enterprise only, alpha). Cursor "keeps a log of the signature of every AI
  line… suggested", then matches those signatures against later commits **by the same author**. This is the same
  record-then-match idea, captured in the client. Documented gaps: formatters invalidate signatures; no coverage
  for Background Agents or the CLI; only commits made from Cursor count; only the top-level repo; and lines
  accepted but never committed still count. — Why it matters: a large vendor validates the matching technique,
  and its failure modes match the handoff's design review (formatter drift, author scoping). —
  [source: cursor.com/docs/account/teams/analytics, forum.cursor.com threads, jellyfish.co/library/cursor-usage-analytics]
  (confidence: medium)
- **TensorZero's write-up ("Automatically Evaluating AI Coding Assistants with Each Git Commit")** — Viraj Mehta,
  Aaron Hill and Gabriel Bianconi, **2025-06-26**, fetched 2026-10-14.
  - **Capture:** the TensorZero LLM gateway records "each inference Cursor made" (via their Cursor integration)
    in their own database. The pipeline parses the output, which implies the **full generated code is stored**;
    hashes are not mentioned.
  - **Linkage:** a **post-commit git hook** runs a small Rust binary. It fetches inferences recorded **between the
    previous commit and this one** that have no feedback yet, optionally filtered by user. The link is purely
    time-based, with no session or episode ID.
  - **Matching:** tree-sitter parses both sides. For each generated snippet it does an exhaustive search over the
    commit's added-hunk subtrees for the minimum **tree-edit distance** (Zhang–Shasha), normalised by snippet
    size. The reward is 1 − (Σ distances / Σ snippet sizes). No thresholds.
  - **Output:** a **per-inference similarity score** used as a reward signal, with matched commit code stored as
    "demonstrations" for possible fine-tuning. It does **not** label lines AI or human.
  - **Status:** an open-source example (`examples/integrations/cursor/feedback` in `tensorzero/tensorzero`), used
    internally, not a product feature.
  - **Acknowledged limits:** many inferences never get committed; commits mix human and generated code; separating
    code-generating inferences from planning and shell calls is open; similar trees can hide semantic changes.
  - **Results:** anecdotal, for one engineer's usage.

  — Why it matters: it is **direct precedent for gateway-sourced capture matched at commit time**, so the
  handoff's "never sourced from a gateway" claim (section 2) is false. The gap that remains is narrower:
  **line-level classification** (AI unmodified / modified / human / indeterminate), **privacy-preserving storage**
  (keyed fingerprints, not full code), **tool neutrality** (beyond Cursor), **non-time-only scoping**, and
  **PR-level server-side checks**. Its AST tree-edit-distance approach is a concrete candidate for the "AI,
  modified" step, though it needs the code, not just hashes, on both sides. — [source: tensorzero.com/blog
  (fetched)] (confidence: high for what the article says)
- **llm-interceptor** is a MITM proxy that logs Claude Code, Cursor and Codex traffic to model APIs, including
  streamed responses. It shows network-layer capture of agent output works without an editor plugin. It is a
  debugging tool and does no attribution. — [source: github.com/chouzz/llm-interceptor summary] (confidence: medium)
- **aigit** (client-side, reads Claude Code session logs, SHA-256 plus TLSH fuzzy matching) has 2 stars and an
  unclear license (`NOASSERTION`) — a precedent for the technique, not a competitor. — [source: GitHub API;
  handoff section 7] (confidence: high)
- **Agent Trace** (v0.1.0 RFC, Jan 2026) is a JSON trace record mapping line ranges to conversations and
  contributors (`human` / `ai` / `mixed` / `unknown`). Model IDs and **content hashes** are optional. Storage is
  left to implementers (files, git notes, databases), and it covers Git, Jujutsu and Mercurial. It explicitly
  does not cover legal ownership. — Why it matters: it is the obvious interoperability target for output.
  `cursor/agent-trace` returned 404 from the GitHub API; the repo location needs checking. —
  [source: agent-trace.dev, infoq.com/news/2026/02/agent-trace-cursor, github.com/cursor/agent-trace README
  (search result)] (confidence: medium)
- **Harness telemetry offers counts, not line matching.** The Copilot usage metrics API reports lines suggested
  and added per user, feature and model (NDJSON reports, 1-day lag; CLI lines reported from v1.0.57). Its own
  guides call the numbers "directional". Copy-pasted code isn't counted, and users with IDE telemetry disabled are
  left out. Claude Code exports `claude_code.lines_of_code.count` (added/removed) through OpenTelemetry (beta). —
  Why it matters: this is what adopters already have, aggregated and limited to one vendor each. —
  [source: github.blog changelog 2026-07-02, jellyfish.co/library/github-copilot-analytics,
  docs.anthropic.com/en/docs/claude-code/monitoring-usage] (confidence: medium)
- **Classifier detection is inference, not a record.** Span's `span-detect-1` claims about 95% accuracy with a
  5% abstain option. It works on 2,000–3,000-character blocks, is reported to degrade below about 700 characters,
  and supports only some languages. A competitor argues it degrades under distribution shift. — Why it matters:
  this is the main alternative that needs no capture at all, but it doesn't work per line. —
  [source: businesswire.com (Sep 2025), fast.io, blog.exceeds.ai, Show HN] (confidence: low-medium; mostly vendor
  claims)
- **Watermarking LLM code output** (SWEET and successors) needs control over generation and is fragile. Comment
  removal, variable renaming, refactoring and `black` reformatting degrade detection (MATRIX, arXiv 2604.16001).
  — Why it matters: it can't be used with hosted models the adopter doesn't control. It also shows that
  formatter-style transforms break signals that depend on surface text. — [source: arxiv.org/abs/2305.15060,
  arxiv.org/abs/2604.16001, arxiv.org/html/2512.14753] (confidence: medium)
- **Winnowing / MOSS** (Schleimer et al.) uses established code-fingerprinting methods: normalize (strip
  whitespace and punctuation, lowercase), hash k-grams, keep the minimum hash per window. Formatting-only changes
  don't change the fingerprints. — Why it matters: proven prior art for normalization that survives formatters,
  relevant to handoff section 4.1. — [source: Princeton-hosted p76-schleimer.pdf, arxiv.org/abs/2010.01700]
  (confidence: medium-high; academic and long established)
- **Out-of-the-box Helm packaging precedent: Langfuse.** By default its chart deploys the app (web plus worker)
  **with** Postgres, ClickHouse, Redis (queue and cache) and S3/MinIO, and each can be pointed at an external
  instance. Documented gotchas: Redis needs `maxmemory-policy=noeviction`, all data stores must run in UTC, and
  secrets come from existing Kubernetes secrets. — Why it matters: a working model for the "everything in one
  chart, swappable later" experience the owner describes. — [source: langfuse.com/self-hosting/kubernetes-helm]
  (confidence: medium)
- **Internal precedent:** spec 002 (`aiattr`, hook-based, signed in-toto/DSSE records, 59/59 lines correct in the
  lab) and the handoff's design review. No `.specify/specs/` or past decisions exist in this repository. —
  [source: handoff sections 4–6; repo inspection] (confidence: high for existence, medium for portability)

## Market & Context

- **Gateways that could host capture are open source and active**: agentgateway (Apache-2.0, 5,320 stars),
  LiteLLM (61,190 stars; license reported by GitHub as `NOASSERTION`), Portkey gateway (MIT, 13,181 stars, last
  push 2026-05-25). The `envoyproxy/ai-gateway` API lookup resolved to `theagentrouter/agent-router` (Apache-2.0,
  2,224 stars), apparently a rename or transfer; not investigated. — [source: GitHub API] (confidence: high for
  metadata)
- **Gateways can expose response bodies, by different mechanisms:**
  - agentgateway: OpenTelemetry export "including request and response bodies", an "include prompts and
    completions" log setting, and an `llm.toolCalls` CEL field that has to be referenced explicitly. Tool calls
    aren't collected by default. [source: agentgateway.dev LLM observability and access-log docs] (confidence: medium)
  - LiteLLM: `CustomLogger` stream hooks and an async-iterator hook see each chunk. Reassembling streamed
    tool-call argument fragments is left to the implementer, and the "agentic loop hook" can't inspect streamed
    tool calls. [source: litellm source mirrors, docs.litellm.ai] (confidence: medium-low)
  - Envoy Gateway: `ext_proc` with `response.body: Streamed` streams response bodies to an external gRPC
    processor. [source: gateway.envoyproxy.io ext-proc docs] (confidence: medium)
  - Portkey and Kong: not researched in this pass.
  - **Implication (revised after the probe):** capture needs one integration per gateway, but **not one per
    model-API format**. Both gateways tested already reassemble streamed tool calls and give a plug-in one
    normalised shape across Chat, Responses and Anthropic Messages. agentgateway uses CEL `llm.toolCalls`; LiteLLM
    uses an OpenAI-shaped `response_obj`. See [Probe](#probe-streamed-tool-call-reassembly). — [source: lab probe
    2026-10-14] (confidence: medium-high; synthetic streams)
- **Which coding tools can be routed through a customer gateway:**
  - Claude Code: yes (base-URL override; observed in spec 002's lab). [source: handoff section 5] (confidence: high)
  - Codex CLI: yes, via `~/.codex/config.toml` provider/base URL. A logged-in ChatGPT session overrides it.
    [source: vendor guides] (confidence: medium)
  - Gemini CLI: yes, via `GOOGLE_GEMINI_BASE_URL`. [source: vendor guides] (confidence: medium)
  - OpenCode: yes (observed in spec 002's lab). [source: handoff section 5] (confidence: high)
  - GitHub Copilot: **only chat, agent, CLI and the Copilot app** via enterprise BYOK (Jun 2026). **Inline
    ghost-text completions, next-edit suggestions and semantic search can't be routed.** [source: github.blog
    changelogs 2026-06-17 and 2026-06-23, truefoundry.com, docs.orq.ai] (confidence: medium-high)
  - Cursor: the custom base URL is **called from Cursor's servers, not the editor**, so the gateway must be
    reachable from the internet. Only chat/agent uses it; Composer, inline edit (Cmd+K) and Tab stay on Cursor's
    backend. One forum report (Jul 2026) describes different behavior. [source: forum.cursor.com, docs.orq.ai,
    respan.ai, docs.prem.io] (confidence: medium)
- **What adopters rely on today (the cost of doing nothing):** self-reported surveys; per-vendor dashboards that
  each cover one tool (Copilot metrics, Cursor tracking, Claude Code OTel); hook-based git-ai; commit-trailer
  declarations; or ML classifiers. None gives line-level, tool-neutral attribution without something installed on
  every machine or tool. — [source: the findings above] (confidence: medium)

## Data & Constraints

- **Bitnami images went paid or legacy (Aug–Sep 2025).** `docker.io/bitnami` images moved to an unmaintained
  `bitnamilegacy` repository. Paid "Bitnami Secure Images" is reportedly priced around $50k–$72k a year
  (unconfirmed). Charts still resolve, but the images they reference may no longer exist, and the PostgreSQL chart
  is affected. — Constraint: an out-of-the-box chart that pulls in Bitnami subcharts (Postgres, Redis, Kafka)
  would ship broken or unpatched. — [source: northflank.com, linuxiac.com, chainguard.dev, gitlab.com issue
  21360] (confidence: medium-high; many independent reports, though dates vary)
- **Per-developer attribution has legal friction in the EU, especially in Germany.** Under §87(1) no. 6 BetrVG,
  a works council has co-determination rights over systems "objectively suitable for monitoring employees". This
  is usually settled through a works agreement, alongside GDPR and §26 BDSG proportionality, and "total
  monitoring" is prohibited. — Constraint: adopters in these jurisdictions may not be able to switch on
  per-developer results by default. — [source: twobirds.com HR guide, cov.com (Jul 2026) works-council PDF,
  compound.law] (confidence: medium; general guidance, not specific to developer tools; not legal advice)
- **Gateway coverage gaps are structural, not configuration gaps.** Copilot inline completions and Cursor's
  Tab/Composer/inline edit never reach a customer gateway (see Market & Context). In a gateway-only design those
  lines would count as "human". — [source: as above] (confidence: medium-high)
- **Formatters break surface-level matching, and a vendor confirms it.** Cursor documents formatter invalidation.
  Watermark research shows `black` reformatting degrades signals. Winnowing-style normalization is the known
  countermeasure. — [source: Cursor docs; arxiv.org/abs/2604.16001; Schleimer et al.] (confidence: medium)
- **Short fragments are unreliable for any technique.** Classifiers degrade below about 700 characters. Trivial
  lines match anything (handoff section 4.4). — [source: fast.io review; handoff] (confidence: medium)
- **Licenses of likely building blocks:** agentgateway Apache-2.0, Portkey MIT, git-ai Apache-2.0, and
  agent-router Apache-2.0 are permissive. LiteLLM is reported as `NOASSERTION`; reportedly it is MIT with a
  separately licensed enterprise directory (ASSUMPTION from general knowledge, not verified). aigit is
  `NOASSERTION`. — [source: GitHub API] (confidence: high for the API values)
- **Fingerprint volume and retention:** no data found. Rows per response × responses per developer per day ×
  retention window is not estimated anywhere in the sources. — [ASSUMPTION gap]
- **Streamed tool-call formats differ, and the documented ones are now tested.**
  - OpenAI Chat streams `delta.tool_calls[i].function.arguments` fragments keyed by `index`, which can be
    interleaved across parallel calls.
  - The Responses API streams `response.function_call_arguments.delta`, and a **`.done` event carries the full
    arguments**. Freeform custom tools (such as `apply_patch`) use `response.custom_tool_call_input.delta/.done`,
    with **raw text, not JSON**.
  - Anthropic streams `input_json_delta.partial_json`, ends a block with `content_block_stop`, and has **no
    full-value event**. With fine-grained tool streaming (`eager_input_streaming`), the docs warn of **invalid or
    partial JSON**, and `max_tokens` can cut a value off.
  - Gemini sends `functionCall.args` whole per part. Its `streamFunctionCallArguments` / `partial_args` option is
    documented for Vertex but "not supported in Gemini API". Its OpenAI-compatible mode is reported to omit
    tool-call `index`.

  [source: Anthropic streaming and fine-grained-tool-streaming docs, OpenAI community Responses-events guide,
  Gemini SDK `FunctionCallingConfig` reference, discuss.ai.google.dev] (confidence: medium-high for Anthropic;
  medium for the others). See the probe below for gateway behaviour.
- **Release mechanics for the algorithm library** (GitHub Releases, package registries, signing/provenance
  attestations): not researched in this pass. — [gap]

## Probe: Streamed Tool-Call Reassembly

*Lab probe run 2026-10-14. Full method, scripts and raw results are in `probes/streamed-tool-calls/`.*

**Setup.** No provider API keys were available, so a mock provider replayed **synthetic** streams built to each
provider's documented SSE format:
- OpenAI Chat: two **parallel, interleaved** tool calls.
- OpenAI Responses: a function call plus a **freeform `apply_patch`** custom tool with Codex-style patch text.
- Anthropic Messages: Claude Code-shaped `Write` and `Edit`, plus a variant **truncated by `max_tokens`**.
- Gemini: a native `streamGenerateContent` call.

The code in the arguments contained tabs, `\r\n`, an escaped `\n` in a string literal, quotes, `é` and a 4-byte
emoji. Fragments split JSON escapes, and the server wrote 7-byte HTTP chunks, so SSE lines and UTF-8 characters
were split mid-way. Results were checked for exact argument equality and for equal per-line HMAC fingerprints.

| Capture path | Chat | Responses (fn + `apply_patch`) | Anthropic | Anthropic truncated | Gemini native |
|---|---|---|---|---|---|
| Reference reassembler (about 150 lines, stdlib), direct | ✅ | ✅ | ✅ | ✅ flagged invalid | ✅ |
| **LiteLLM 1.105.1** `CustomLogger.async_log_success_event` | ✅ | ✅ | ✅ (translated to OpenAI shape) | ✅ raw invalid JSON passed, `finish_reason: length` | ✅ via OpenAI-format route only (native `/gemini` route not tested) |
| **agentgateway 1.6.0** CEL `llm.toolCalls` in JSON access log | ✅ | ✅ | ✅ | ✅ raw string passed | ❌ **not captured** |
| Client stream through either gateway | unchanged ✅ | ✅ | ✅ | ✅ | ✅ |

Findings:
- **Reassembly is a solved, small problem for the documented formats.** It is not a reason to reject the idea.
  Both gateways reassemble internally and give a plug-in complete, byte-exact arguments. Gateway-side
  fingerprints matched ground truth in every complete case. (confidence: medium-high; synthetic streams)
- **agentgateway 1.6.0 doesn't capture tool calls on the native Gemini streaming path.** Confirmed in source:
  `crates/llm/src/conversion/vertex_gemini.rs` `passthrough_stream` accumulates usage and completion text only. A
  native-Gemini client such as Gemini CLI would be invisible to `llm.toolCalls`. (confidence: high)
- **Capture can fail silently.** A first Responses fixture that left out `created_at` and the usage `*_details`
  fields still streamed to the client, but agentgateway logged `llm.toolCalls = null` with no error. Its typed
  parser treats non-matching events as raw. Any upstream that is "Responses-compatible" but not exact (for
  example a self-hosted model server) could lose capture without anyone noticing. A capture component therefore
  needs a **coverage signal** (tool calls seen vs. captured). (confidence: high for the behaviour; real-world
  frequency unknown)
- **Truncated tool calls arrive as invalid JSON** at both gateways. Capture must detect and handle them, never
  crash. LiteLLM marks them `finish_reason: length`.
- **LiteLLM appends a non-standard `data: [DONE]`** to Responses streams. That's harmless for clients that ignore
  it, but a strict parser downstream of the gateway breaks on it (my first parser did).
- **Not tested:**
  - Real provider recordings.
  - Real Claude Code, Codex, Gemini CLI and OpenCode tool schemas (including whether Codex sends `apply_patch` as
    a freeform tool, and Claude Code's other edit tools).
  - Overhead and buffer limits on large writes (agentgateway warns of "performance impacts for large responses").
  - LiteLLM's native `/gemini` pass-through, Envoy AI Gateway, Portkey and Kong.

## Evidence Against the Idea

1. **The main open-source alternative already covers the harnesses the gateway can't.** git-ai is Apache-2.0,
   popular, active, supports 8+ agents including Copilot and Cursor, survives history rewrites, and has a
   self-hosted server. The handoff's premise that hooks don't scale is partly undercut: git-ai has done the
   per-harness work. It still needs an install on every machine. — [source: git-ai repo, usegitai.com] (medium-high)
2. **The gateway is blind to the most-used completion surfaces.** Copilot inline completions and Cursor's
   Tab/Composer/inline edit can't be routed through a customer gateway. A gateway-only design systematically
   under-reports AI and labels those lines "human", which is the false attribution the design review ranks most
   harmful. — [source: GitHub changelogs, Cursor sources] (medium-high)
3. **"Unclaimed ground" is false as stated.** TensorZero (a gateway vendor) published and open-sourced
   gateway-captured Cursor output matched against commits (June 2025). Cursor ships record-then-match at the
   client. The novelty is narrower: tool-neutral, line-level classification, keyed fingerprints instead of stored
   code, scoping beyond a time window, and a server-side PR check, packaged as open source. — [source:
   tensorzero.com (fetched), Cursor docs] (medium-high)
4. **The adapter problem moves rather than disappears, but less than feared.** The probe shows gateways already
   normalise the model-API formats, so the remaining cost is **one integration per gateway** (agentgateway CEL/OTel,
   LiteLLM Python callback, Envoy ext_proc gRPC). Each has its own gaps, such as agentgateway 1.6.0's native-Gemini
   path, and can lose capture **silently** when events don't match its schema. An "out of the box" stack would
   likely pick one gateway, and adopters on another would need an adapter. — [source: lab probe 2026-10-14;
   gateway docs and source] (medium-high)
5. **The same failure modes as the vendor version.** Cursor's matching is invalidated by formatters and scoped by
   author. A gateway can't run the repo's formatter before capture (handoff section 4.1). — [source: Cursor
   docs; handoff] (medium)
6. **The output is legally sensitive.** In works-council jurisdictions, per-developer AI attribution likely needs a
   works agreement. That limits the "deploy the chart and see dashboards" experience for EU adopters unless
   aggregate views are the default. — [source: Bird & Bird, Covington] (medium)
7. **An out-of-the-box multi-component stack is costly to maintain.** The gateway, database, queue, Grafana,
   PR-check service and library all need upkeep. The Bitnami change shows how dependency charts can break under a
   project. The maintainer team appears to be one person. — [source: Bitnami reports; ASSUMPTION for team size]
   (medium)
8. **AI-share-of-code is a contested metric.** Surveys and measurements differ by more than 10×, and vendors are
   shifting their pitch toward outcomes (cycle time, quality). A precise line count may answer a question buyers
   are moving away from. — [source: SIG vs. Sonar figures; jellyfish.co. The "volume, not value" critique is
   ASSUMPTION; no independent critique was retrieved] (low-medium)
9. **The field is consolidating.**
   - git-ai's maintainers went to OpenAI's Codex team in September 2026. The owner calls it an acquisition; press
     calls it a hire.
   - Agent Trace is backed by Cursor, and Copilot and Cursor ship native metrics.
   - Model and tool vendors now own the attribution capability for their own agents. A small open-source project
     could be overtaken by native features. (A counter-reading: vendor capture leaves room for a vendor-neutral
     option, but that is an argument for the idea, not evidence of demand.)

   — [source: owner statement; thenewstack.io; GitHub changelogs] (medium)

## Gaps & Open Questions

- [NEEDS CLARIFICATION: Who are the adopters? No interviews or issue threads from platform teams, OSS maintainers
  or compliance owners were found asking for gateway-sourced attribution specifically. Is a small survey or a few
  conversations in scope before define?]
- ~~Read the TensorZero write-up in full.~~ **Resolved 2026-10-14:** fetched. It is an open-source example (not a
  product feature), Cursor-only, time-window-linked via a post-commit hook, and scores per inference (not per
  line). See Prior Art.
- [NEEDS CLARIFICATION: After git-ai's move to OpenAI, will its Apache-2.0 project stay maintained and
  vendor-neutral? Does it (or Agent Trace) accept or plan a server-side, gateway-fed capture source? A fork or a
  contribution could be an alternative to a new project. Not checked in its issues.]
- ~~Can gateways reassemble streamed tool-call arguments for the main formats?~~ **Largely resolved 2026-10-14 by
  the lab probe:** yes for OpenAI Chat, Responses (including freeform tools) and Anthropic Messages, on both
  LiteLLM 1.105.1 and agentgateway 1.6.0; no for agentgateway's native Gemini path. Still open:
  - [NEEDS CLARIFICATION: Which gateway does the stack target first?]
  - [NEEDS CLARIFICATION: Re-run the probe against **recorded real streams** from each provider and each harness
    (Claude Code, Codex, Gemini CLI, OpenCode), which needs API keys or a local model server. Confirm Codex's
    `apply_patch` shape and Claude Code's full edit-tool set.]
  - [NEEDS CLARIFICATION: Capture overhead and buffer limits for large file writes through `llm.toolCalls` or
    callbacks.]
  - [NEEDS CLARIFICATION: How will capture detect silent loss (tool calls seen vs. captured), given agentgateway's
    behaviour on schema-deviant streams?]
- [NEEDS CLARIFICATION: How much do formatters drift, by language and harness? No published data was found.]
- [NEEDS CLARIFICATION: What share of AI-generated lines arrives through surfaces a gateway can't see (inline
  completions, Cursor Tab)? No usage-share data was found; it bounds the achievable coverage.]
- [NEEDS CLARIFICATION: Fingerprint row volume and storage per 1,000 developers, and the retention needed for PR
  matching.]
- [NEEDS CLARIFICATION: Where does Agent Trace live now (`cursor/agent-trace` returned 404), what is its license
  and governance, and can its optional content-hash field carry keyed fingerprints?]
- [NEEDS CLARIFICATION: Status of the Envoy AI Gateway repo (`envoyproxy/ai-gateway` → `theagentrouter/agent-router`).]
- [NEEDS CLARIFICATION: Library release and supply-chain expectations (SemVer, GitHub Releases plus a registry,
  signed artifacts and provenance attestations). Not researched.]
- [NEEDS CLARIFICATION: Portkey and Kong AI Gateway body-access mechanisms. Not researched.]
- [NEEDS CLARIFICATION: LiteLLM's exact license terms for any components the stack would use.]

## Sources

Policy key. **allowlisted**: GitHub API via `gh` (github.com). **search-summary**: seen only as a web-search
result summary, not fetched. These hosts are not on the intake allowlist, the fetch tool can't pin connections, so
no fetch was made. **confirmed-by-user**: fetched after the owner asked for it (2026-10-14). No fetch was refused
outright (`auto-refused` is unused).

Follow-up sources (2026-10-14):
- https://www.tensorzero.com/blog/automatically-evaluating-ai-coding-assistants-with-each-git-commit/ (host: www.tensorzero.com, policy: confirmed-by-user; fetched)
- https://thenewstack.io/openai-hires-git-ai/ (host: thenewstack.io, policy: search-summary)
- https://docs.anthropic.com/en/api/messages-streaming (host: docs.anthropic.com, policy: search-summary)
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/fine-grained-tool-streaming (host: platform.claude.com, policy: search-summary)
- https://community.openai.com/t/responses-api-streaming-the-simple-guide-to-events/1363122 (host: community.openai.com, policy: search-summary)
- https://googleapis.github.io/js-genai/release_docs/interfaces/types.FunctionCallingConfig.html (host: googleapis.github.io, policy: search-summary)
- https://discuss.ai.google.dev/t/gemini-openai-compatibility-issue-with-tool-call-streaming/59886 (host: discuss.ai.google.dev, policy: search-summary)
- https://docs.litellm.ai/docs/anthropic_unified/native_passthrough (host: docs.litellm.ai, policy: search-summary)
- https://github.com/agentgateway/agentgateway at tag `v1.6.0`: `schema/cel.md`, `crates/llm/src/conversion/responses.rs`, `crates/llm/src/conversion/vertex_gemini.rs`, `crates/llm/src/tests/response/responses/stream-custom-tool.json`, `examples/datadog/standalone/config-content.yaml` (host: github.com, policy: allowlisted; via `gh api`)
- https://github.com/agentgateway/agentgateway/releases/tag/v1.6.0, asset `agentgateway-darwin-arm64` (host: github.com, policy: allowlisted; downloaded for the probe, sha256 verified)
- https://pypi.org/project/litellm/ 1.105.1 (host: pypi.org; installed into an isolated scratch venv for the probe)
- Lab probe: `probes/streamed-tool-calls/` (this assessment directory)

GitHub API (allowlisted; `gh api repos/<owner>/<repo>`; gh followed one redirect automatically, noted):
- https://github.com/git-ai-project/git-ai (host: github.com, policy: allowlisted)
- https://github.com/getaigit/getaigit (host: github.com, policy: allowlisted)
- https://github.com/cursor/agent-trace (host: github.com, policy: allowlisted; returned 404)
- https://github.com/agentgateway/agentgateway (host: github.com, policy: allowlisted)
- https://github.com/envoyproxy/ai-gateway → resolved to https://github.com/theagentrouter/agent-router (host: github.com, policy: allowlisted; redirect followed by `gh`, recorded here)
- https://github.com/BerriAI/litellm (host: github.com, policy: allowlisted)
- https://github.com/Portkey-AI/gateway (host: github.com, policy: allowlisted)

Prior art and standards:
- https://github.com/git-ai-project/git-ai (host: github.com, policy: search-summary)
- https://github.com/Zoo-Code-Org/Zoo-Code/issues/1867 (host: github.com, policy: search-summary)
- https://usegitai.com/pricing (host: usegitai.com, policy: search-summary)
- https://usegitai.com/docs/metrics/self-hosted (host: usegitai.com, policy: search-summary)
- https://rywalker.com/research/git-ai (host: rywalker.com, policy: search-summary)
- https://aicatchup.com/news/openai-welcomes-git-ai-agent-attribution (host: aicatchup.com, policy: search-summary)
- https://agent-trace.dev/ (host: agent-trace.dev, policy: search-summary)
- https://github.com/cursor/agent-trace/blob/main/README.md (host: github.com, policy: search-summary)
- https://www.infoq.com/news/2026/02/agent-trace-cursor/ (host: www.infoq.com, policy: search-summary)
- https://www.thoughtworks.com/radar/platforms/agent-trace (host: www.thoughtworks.com, policy: search-summary)
- https://www.morphllm.com/agent-trace-spec (host: www.morphllm.com, policy: search-summary)
- https://cursor.com/docs/account/teams/analytics (host: cursor.com, policy: search-summary)
- https://forum.cursor.com/t/details-on-ai-code-tracking-api/128253 (host: forum.cursor.com, policy: search-summary)
- https://forum.cursor.com/t/ai-code-tracking-api-only-returning-10000-commits/138252 (host: forum.cursor.com, policy: search-summary)
- https://jellyfish.co/library/cursor-usage-analytics/ (host: jellyfish.co, policy: search-summary)
- https://www.tensorzero.com/blog/automatically-evaluating-ai-coding-assistants-with-each-git-commit/ (host: www.tensorzero.com, policy: search-summary)
- https://github.com/chouzz/llm-interceptor (host: github.com, policy: search-summary)
- https://www.businesswire.com/news/home/20250916147051/en (host: www.businesswire.com, policy: search-summary)
- https://fast.io/resources/best-ai-code-detectors-2026/ (host: fast.io, policy: search-summary)
- https://blog.exceeds.ai/span-ai-code-detector-features (host: blog.exceeds.ai, policy: search-summary)
- https://sacra.com/c/span (host: sacra.com, policy: search-summary)
- https://arxiv.org/pdf/2305.15060 (host: arxiv.org, policy: search-summary)
- https://arxiv.org/pdf/2604.16001 (host: arxiv.org, policy: search-summary)
- https://arxiv.org/html/2512.14753v1 (host: arxiv.org, policy: search-summary)
- https://www.cs.princeton.edu/courses/archive/spring05/cos598E/bib/p76-schleimer.pdf (host: www.cs.princeton.edu, policy: search-summary)
- https://arxiv.org/pdf/2010.01700 (host: arxiv.org, policy: search-summary)

Demand, market and metrics:
- https://www.sonarsource.com/blog/state-of-code-developer-survey-report-the-current-reality-of-ai-coding/ (host: www.sonarsource.com, policy: search-summary)
- https://www.softwareimprovementgroup.com/wp-content/uploads/State-of-Software-2026.pdf (host: www.softwareimprovementgroup.com, policy: search-summary)
- https://lenz.io/q/percentage-of-code-written-by-ai-2026 (host: lenz.io, policy: search-summary)
- https://13labs.au/blog/vibe-coding-statistics-2026 (host: 13labs.au, policy: search-summary)
- https://github.blog/changelog/2026-07-02-improved-accuracy-and-coverage-in-copilot-usage-metrics-reports (host: github.blog, policy: search-summary)
- https://jellyfish.co/library/github-copilot-analytics/ (host: jellyfish.co, policy: search-summary)
- https://docs.anthropic.com/en/docs/claude-code/monitoring-usage (host: docs.anthropic.com, policy: search-summary)
- https://jellyfish.co/blog/jellyfish-partners-with-kiro-to-measure-ai-engineering-impact/ (host: jellyfish.co, policy: search-summary)
- https://www.phoronix.com/news/QEMU-Patch-Allows-Some-AI (host: www.phoronix.com, policy: search-summary)
- https://www.opensourceforu.com/?p=97794 (host: www.opensourceforu.com, policy: search-summary)
- https://www.ssdnodes.com/learn/ai-assisted-code-open-source-policies (host: www.ssdnodes.com, policy: search-summary)
- https://www.youngju.dev/blog/2026-07-31-gcc-ai-policy-open-source-contributions.en (host: www.youngju.dev, policy: search-summary)

Gateways and harness routing:
- https://agentgateway.dev/docs/kubernetes/main/integrations/llm/observability/ (host: agentgateway.dev, policy: search-summary)
- https://agentgateway.dev/docs/standalone/main/documentation/observability/access-logs/view/ (host: agentgateway.dev, policy: search-summary)
- https://agentgateway.dev/docs/kubernetes/main/traffic-management/transformations (host: agentgateway.dev, policy: search-summary)
- https://docs.litellm.ai/docs/proxy/agentic_loop_hook (host: docs.litellm.ai, policy: search-summary)
- https://gateway.envoyproxy.io/docs/tasks/extensibility/ext-proc (host: gateway.envoyproxy.io, policy: search-summary)
- https://aigateway.envoyproxy.io/release-notes (host: aigateway.envoyproxy.io, policy: search-summary)
- https://github.blog/changelog/2026-06-17-copilot-cli-supports-enterprise-bring-your-own-key-byok-models/ (host: github.blog, policy: search-summary)
- https://github.blog/changelog/2026-06-23-github-copilot-app-support-for-byok (host: github.blog, policy: search-summary)
- https://www.truefoundry.com/docs/ai-gateway/github-copilot (host: www.truefoundry.com, policy: search-summary)
- https://docs.orq.ai/docs/ai-studio/integrations/code-assistants/github-copilot (host: docs.orq.ai, policy: search-summary)
- https://forum.cursor.com/t/cursor-managed-models-are-routed-through-override-openai-base-url/169088 (host: forum.cursor.com, policy: search-summary)
- https://docs.orq.ai/docs/ai-gateway/integrations/code-assistants/cursor (host: docs.orq.ai, policy: search-summary)
- https://respan.ai/docs/integrations/gateway/cursor (host: respan.ai, policy: search-summary)
- https://docs.prem.io/guides/cursor (host: docs.prem.io, policy: search-summary)
- https://www.getmaxim.ai/articles/how-to-route-gemini-cli-and-codex-through-an-ai-gateway/ (host: www.getmaxim.ai, policy: search-summary)
- https://evolink.ai/blog/one-endpoint-coding-clis (host: evolink.ai, policy: search-summary)

Packaging and constraints:
- https://langfuse.com/self-hosting/kubernetes-helm (host: langfuse.com, policy: search-summary)
- https://northflank.com/blog/bitnami-deprecates-free-images-migration-steps-and-alternatives (host: northflank.com, policy: search-summary)
- https://linuxiac.com/bitnami-ends-free-stable-images-users-forced-to-migrate-or-pay/ (host: linuxiac.com, policy: search-summary)
- https://www.chainguard.dev/supply-chain-security-101/a-practical-guide-to-migrating-helm-charts-from-bitnami (host: www.chainguard.dev, policy: search-summary)
- https://gitlab.com/gitlab-com/gl-infra/delivery/-/issues/21360 (host: gitlab.com, policy: search-summary)
- https://www.twobirds.com/en/insights/2024/germany/quick-hr-guide-key-considerations-for-implementing-ai-to-your-german-workforce (host: www.twobirds.com, policy: search-summary)
- https://www.cov.com/-/media/files/corporate/publications/2026/07/works-council-rights-in-ai-implementation-projects.pdf (host: www.cov.com, policy: search-summary)
- https://compound.law/en-DE/compliance/ai-employee-monitoring/ (host: compound.law, policy: search-summary)

Internal:
- `docs/handoffs/gateway-fingerprint-attribution.md` (repo path; read in full)
- `.specify/assessments/gateway-code-attribution/intake.md` (repo path)
