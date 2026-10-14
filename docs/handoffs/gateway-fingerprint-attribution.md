# Handoff: AI-code attribution by fingerprinting at the gateway

*Context for a new `speckit-assess` session in a new repository. Written 2026-10-13 from the `ai-gateway`
homelab project (specs 001 and 002). Everything below is either the owner's own statement, a measured lab result,
a cited source, or a design review the owner supplied. Each is labelled. Design ideas are labelled **concept**:
they're starting points for the assessment to test, not decisions.*

---

## 1. The idea (owner's words)

> Fingerprint lines of code at the AI gateway as they come from the model, then do that fingerprinting again at
> git hook / PR push time, so we can determine what code is AI, mixed, or human created.

The point is to get line-level AI attribution **without depending on any harness plugin or hook**, so it works the
same for Claude Code, GitHub Copilot, Cursor, OpenCode and future tools, at the scale of thousands of developers.

## 2. Why this, and why now

- The owner's employer is evaluating a company-wide AI gateway. The owner built a homelab version to learn what
  central AI governance takes (spec 001), then built signed, line-level AI-code attribution on top of it (spec 002).
- Spec 002 works (results in section 6), but its **capture depends on each harness**: an OpenCode plugin and
  Claude Code hooks call a local tool before and after every agent tool call. At enterprise scale that means an
  adapter per harness, managed install on every developer machine, and no coverage at all for tools without
  hooks.
- Every line an agent writes starts as **model output**, and in a governed setup all model output already passes
  through the gateway. If the gateway records fingerprints of what the model produced, and commits are later
  fingerprinted the same way, matching the two gives attribution with nothing installed per harness.
- A prior-art search (section 7) found the matching technique in use, but **never sourced from a gateway**. This
  looks like unclaimed ground.

## 3. How it would work (concept)

### Where the first fingerprint comes from

**At the gateway, from the model's response, before anything touches the file.** Not from an IDE hook and not at
commit time. So the stored fingerprint is the model's original text, and a mismatch at PR time really does mean
the line changed after generation.

One caution on wording: a change after generation isn't always a person. A formatter, a code generator or a merge
can change a line too. In OpenCode the formatter runs *inside* the edit tool, so OpenCode lines may differ from
the model's text before any person sees them. That's why the categories below say **AI, modified** and not
"human-modified", and why formatter drift must be measured (section 4.1).

### At the gateway, on every model response

1. Take the code-bearing text of the response. In agent traffic, file content usually arrives as **tool-call
   arguments** inside the response (an edit's new text, a file write's content, a patch), plus code blocks in
   ordinary text.
2. For each line: normalise it, then compute a keyed fingerprint (section 4.8 explains why keyed and not a plain
   hash).
3. Store **one row per line**: fingerprint, algorithm version, user, session ID, model, tool-call ID, time, and the
   file path when the tool call names one. **No code is stored.**

### At PR time (and optionally in a git hook)

1. Compute the PR's added lines as **merge-base...head** (three-dot diff).
2. Normalise and fingerprint each added line with the same shared library and the same algorithm version.
3. Look the fingerprints up in one batched, scoped query (section 4.2).
4. Classify each line into one of four categories:

| Category | Rule |
|---|---|
| **AI, unmodified** | Exact fingerprint match |
| **AI, modified** | No exact match, but highly similar to a captured line from the same file and session (token or edit-distance similarity) |
| **Human** | No match and no similar captured line |
| **Indeterminate** | Trivial or common line (`}`, `else {`, `import os`, blank); left out of percentages or given its neighbours' label |

### Illustrative example (made-up fingerprints)

The model's edit tool call contains three lines. The developer changes the tax rate on the third and adds a
comment and a closing line before committing:

| committed line | fingerprint | found at gateway? | category |
|---|---|---|---|
| `def total(items):` | `3f9a1c07b2e4d811` | exact | AI, unmodified |
| `subtotal = sum(i.price for i in items)` | `a0c4e95f13d27b6e` | exact | AI, unmodified |
| `return round(subtotal * 1.0825, 2)` | `51be88d2a4f0c973` | no; similar to a captured line in the same file and session | AI, modified |
| `# reviewed by finance` | `c8e0a7154b39d2f6` | no | Human |
| *(blank line)* | — | — | Indeterminate |

### Where the matching runs (concept)

- **CI / PR check on the server:** needs **nothing on developer machines at all**, sees the final PR, can be a
  required check, and can attribute squash merges against the PR. This looks like the primary variant.
- **Git hook on the developer's machine** (pre-commit or pre-push): earlier feedback, but needs software on every
  machine. Optional.

### Overall flow (concept, from the design review)

```text
model response ─► gateway ─► queue ─► normalise + HMAC ─► fingerprints table
                                                              ▲
PR opened / synchronize ─► wait for ingest watermark ─► merge-base diff
   ─► normalise + HMAC each added line ─► batched scoped lookup
   ─► exact match / fuzzy match / stoplist ─► per-line results
   ─► per-PR summary + check run on the PR
```

## 4. Design review: what can skew the results (owner-supplied)

The main risk isn't database performance. It's **false attribution**: lines labelled human or AI wrongly because
of formatting, history rewrites or common lines. Ordered roughly by how badly each can skew results. Notes in
*italics* adapt the review to the gateway variant.

### 4.1 Both sides must normalise identically

- One **shared normalisation library** used by both the gateway and the PR check. Never two implementations.
- Define it exactly: trimming, tabs vs spaces, `\r\n` vs `\n`, Unicode normalisation (NFC), BOM, encoding.
- **Version the algorithm** and store `algo_version` on every fingerprint, so a later change still matches old
  fingerprints with the old algorithm.
- **Formatters and linters** (Prettier, Black, gofmt) are the biggest source of false "human" labels. Options:
  run the formatter before capture, or normalise more loosely (for example, hash tokens with all whitespace
  removed). *At the gateway, "format before capture" isn't available: the gateway doesn't have the repository or
  its formatter config. Looser normalisation, fuzzy matching, or formatting in the PR check before comparison are
  the realistic options. Measure on OpenCode, whose formatter runs inside the edit tool.*

### 4.2 Match on content, not line position

- Look up each line by **fingerprint within a scope**, never by `(file, line number)`. Line numbers are display
  metadata only.
- Count matches as a **multiset**: if a line appears three times in the PR but was captured once, only one copy
  matches.
- *Scoping is harder at the gateway. The review suggests repo + branch/author + time window, but the gateway
  doesn't know the repository or branch unless the harness sends it or a tool call names a path. Realistic scopes:
  gateway user (mapped from the git author through the identity provider) + time window, narrowed by file path
  where the tool call gave one. This is the biggest open design question (section 9.1).*

### 4.3 Store one fingerprint per line

A single hash over a range makes a one-character edit on line 2 mark lines 1–3 as changed. Store per-line
fingerprints; build ranges only for reporting; optionally keep a block hash as a secondary signal. *Spec 002
already does this: per-line fingerprints, with runs of three or more matching lines required for a match to
count.*

### 4.4 Common lines are ambiguous

After trimming, `}`, `return;`, `else {`, `import os` and blank lines match almost anything. Classify them as
**indeterminate** and leave them out of percentages, or attribute by context (a trivial line between two AI
lines inherits AI). Keep a frequency table or a per-language stoplist.

### 4.5 Git history rewrites

- Rebase, squash, cherry-pick, amend and force-push **change commit SHAs but keep line content**. Never require a
  commit SHA to match; use it only for provenance.
- Diff **merge-base...head** (three-dot), or lines merged in from `main` get counted as the author's work.
- **Squash merges** create a new commit; store attribution against the PR, not only its commits.

### 4.6 Timing and ordering

- A PR can open **before ingestion has caught up**. Checking too early makes every line look human. Track an
  ingestion watermark and wait until it passes the PR head, or report **pending** and re-run. *At the gateway the
  watermark is time-based (ingested up to time T), since gateway rows carry no commit or branch.*
- **PRs change.** Re-run on every push (GitHub's `synchronize` event), store results **per head SHA**, and treat
  the result at merge time as final.
- Make the check **idempotent**, so retries and duplicate webhooks are safe.

### 4.7 More than two categories

The four categories in section 3. The fuzzy step only runs on lines with no exact match, and only against captured
lines **from the same file and session, never globally**. *The commit side has no session ID. Concept: exact
matches in the same file identify the candidate sessions, and the fuzzy step compares only against those.*

### 4.8 Trust and security (matters if this feeds reporting or compliance)

- **Plain hashes of short lines can be reversed** with a dictionary of common code. Use an **HMAC with a
  server-side key**. It also stops anyone outside the system from producing valid fingerprints. *Trade-off against
  spec 002: its plain SHA-256 fingerprints let anyone look up a file from a copy, offline. With HMAC, every
  lookup has to go through the service holding the key.*
- **Capture from developer machines can be faked.** If results matter, capture on the server or sign the capture
  payloads. *Gateway capture is server-side by construction, which is a real advantage over spec 002, where each
  user's machine signed its own claims. The PR check also runs on the server.*
- Per-developer attribution is **sensitive, HR-adjacent data**. Decide who can see it, with access controls and
  retention rules.

### 4.9 Exclusions

Skip lockfiles, generated code, vendored directories, minified files, binaries and very large diffs, or they
flood both the tables and the statistics. Make exclusions configurable (glob patterns, like `.gitattributes`).

### 4.10 Storage sketch (concept, for the plan stage, not the assessment)

Alongside the fingerprint table, a per-line results table and a per-PR summary table (counts per category) for
dashboards. Each PR check is one batched lookup of a few hundred fingerprints, so latency isn't a concern.

```sql
CREATE TABLE pr_line_attribution (
  repo_id           INT,
  pr_number         INT,
  head_sha          BYTEA,
  file_id           BIGINT,
  line_no           INT,
  fingerprint       BYTEA,
  category          SMALLINT,   -- ai_exact / ai_modified / human / indeterminate
  matched_fp_commit BIGINT NULL,
  algo_version      SMALLINT,
  PRIMARY KEY (repo_id, pr_number, head_sha, file_id, line_no)
);
```

The review suggests a fingerprint index on `(repo_id, fingerprint) INCLUDE (...)` so lookups stay scoped and
can't match across repositories. *Gateway rows have no `repo_id` (section 4.2), so the gateway-side index would
key on the chosen scope instead, for example `(user, fingerprint)` with a time range.*

## 5. What exists in the homelab today (facts)

*Redacted before publication.* This section inventoried the owner's private lab: its machines, the users set up on
them, the interim model host, and the state of the earlier gateway (spec 001) and attribution tool (spec 002, `aiattr`)
built there. Nothing in this repository depends on it: the lab was dropped as the target and test bed on 2026-10-14
(`.specify/assessments/gateway-code-attribution/intake.md`). What later stages reused from it is kept below: spec 002's
measured baseline (section 6) and the lab findings (section 8).

## 6. Baseline to compare against (spec 002 measured results, 2026-10-13)

The new approach should be measured on the **same scenario set** so the trade-off is concrete.

| Criterion | Spec 002 result (hook-based capture), per harness |
|---|---|
| Accuracy | 59/59 lines correct, 0 wrong |
| Rewrites (rebase onto a moved base, `merge --squash`) | 30/30 agent lines kept, 0 misattributed |
| Lookup from a plain copy, no git | 9/9 files |
| Tampered / unknown-signer records | all refused |
| Suppressed record detected | yes, the only one reported, no false alarms |
| Overhead | ≤ 0.133 s per change, ≤ 0.119 s per commit (p95) |
| Real coding task per harness | both completed; every commit attributed and valid |
| Pending | durability after 24 h; coverage over a week of normal use |

## 7. Prior art (search 2026-10-13)

| What | Approach | Relevance |
|---|---|---|
| **aigit** ([repo](https://github.com/getaigit/getaigit), [write-up](https://dev.to/gocoolp/i-built-a-tool-to-measure-how-much-of-my-codebase-is-ai-written-heres-how-it-works-12hg)) | Reads Claude Code's **local session logs**, extracts code from Write/Edit tool calls and code blocks, normalises (strip comments, collapse whitespace, lowercase), matches git diff hunks: exact SHA-256 (confidence 1.0), TLSH fuzzy distance < 30 (0.9), < 100 (0.7); `git blame --porcelain` for line tracking | **Closest match.** Same matching idea, sourced from the client instead of the gateway. Claude Code only; needs local logs; no history before install. License not stated |
| **git-ai** ([repo](https://github.com/git-ai-project/git-ai)), Apache-2.0 | Agents call a checkpoint hook; line attribution stored in Git Notes | Hook-based, git-bound, unsigned |
| **Entire CLI**, MIT | Hook-based; checkpoint branch in git | Hook-based, git-bound |
| **Exceeds** ([blog](https://blog.exceeds.ai/analyze-git-commits-ai-code/)) | Commit-time attribution with Git Notes, per-tool checkpoints, git hooks | Vendor; hook-based |
| **LinearB, Larridin** ([Larridin](https://larridin.com/developer-productivity-hub/ai-code-share-percentage-ai-generated)) | IDE telemetry tags accepted suggestions, then follows them into commits | Vendor; editor instrumentation |
| **Cursor AI Code Tracking API** | Enterprise-only; AI lines per commit | Proprietary; its documented failure modes are formatters, commits made outside Cursor, edited AI lines still counted as AI, and rebases losing attribution |
| **LiteLLM, Portkey, Kong AI Gateway** ([comparison](https://northflank.com/blog/best-open-source-ai-gateways)) | Keys, budgets, cost tracking, usage logs | **No code-provenance feature found** |
| **Stylometry research** ([Ghaleb](https://arxiv.org/pdf/2601.17406), [Code Fingerprints](https://arxiv.org/html/2603.04212)) | Infer which agent or model wrote code from its style (e.g. 97.2% F1 identifying agents across 33,580 PRs) | Inference, not matching against a record. Spec 002 treated heuristic detection as unreliable and out of scope |
| **Commit trailers** (`Assisted-by:`, `Co-Authored-By:`) | Declaration | Unchecked; no line detail |

One search can miss closed-source vendor features; the assessment's research step should search more deeply.

## 8. Lab findings that matter for this idea

- **Model names differ by vantage point.** Claude Code's transcript records the upstream name
  (`qwen3-coder-64k`); the gateway and OpenCode record the requested name (`qwen3-coder`). The gateway is the
  consistent source, which favours this idea.
- **Tool-call formats differ by harness.** Claude Code's edits carry old and new text; OpenCode has its own tools;
  other harnesses use patch formats or write files through shell commands (heredocs, `sed`). Parsing each schema
  brings back per-harness work, at the gateway instead of on the client. **Concept to test:** fingerprint *every*
  line of response text regardless of structure, and let scoping, run-matching and the stoplist filter noise.
  That needs no schema knowledge, but loses the file path that would narrow fuzzy matching.
- **The gateway sees what the model proposed, not what was applied.** Refused permissions, failed tool calls (in
  OpenCode a failed call never reports finishing) and abandoned edits all leave fingerprints. Matching at PR time
  filters most of this, since unapplied lines never appear in a PR. They do enlarge the candidate set for fuzzy
  matching.
- **Not all agent-made code is model text.** Code produced by running a generator, a formatter, `npm install`,
  or copying a file won't match. OpenCode runs formatters inside its edit tool, so its committed lines may already
  differ from the model's text.
- **Git operations look like edits.** Branch switches, cherry-picks, rebases and squash merges change files with
  no agent involved. Spec 002 needed specific handling; matching by content on a three-dot PR diff sidesteps most
  of it (section 4.5).
- **Fast-forward merges aren't new commits.** Counting them would flag every fetched commit.
- **Streaming.** Responses arrive streamed, and tool-call arguments arrive as fragments. The gateway must
  reassemble them before fingerprinting.
- **Small models misbehave.** On the interim GPU, Claude Code needed a 64k context window and an explicit stop
  instruction to finish tasks. Scripted lab tasks should include one.
- **Python 3.13+ verifies TLS strictly**; the lab's internal certificate lacked an Authority Key Identifier.

## 9. Hard problems the assessment should weigh

1. **Linking a PR to gateway traffic.** Spec 002 had the session ID on both sides. A PR has an author, commits,
   paths and times; gateway rows have a user, session, time and sometimes a path. How is the lookup scoped: git
   author → gateway user through the identity provider, time window, file path, or org-wide? Org-wide matching
   risks crediting one person's PR with another person's AI session (two people asking for the same snippet). The
   design review's repo-scoped index (section 4.10) assumes a `repo_id` the gateway doesn't have.
2. **Formatter drift** (section 4.1). Likely the largest source of false "human" labels, and the gateway can't
   format before capture.
3. **Common lines** (section 4.4). Which stoplist, which minimum line length or run length, and do indeterminate
   lines inherit neighbours' labels or stay out of percentages?
4. **Fuzzy matching without guessing** (section 4.7). How similar is "AI, modified", how is confidence reported,
   and how are candidate sessions chosen when the commit side has no session ID? Spec 002's rule was "never guess;
   say `unknown`".
5. **Trust model** (section 4.8). The gateway is a server-side witness, which is stronger than spec 002's
   self-signed claims. Does the PR result need signing too, and who holds the HMAC key?
6. **Privacy.** The gateway reads response bodies, which spec 001 deliberately avoided. HMAC fingerprints aren't
   reversible without the key, but per-developer results are HR-adjacent data.
7. **Volume and retention.** Fingerprint rows per response × thousands of developers; long enough for PR-time
   matching (days to weeks), versus 30 minutes for request records.
8. **Ingestion timing** (section 4.6). Pending results and re-runs per head SHA.
9. **Traffic that bypasses the gateway.** Copilot inline completions go to the vendor's own servers and can't be
   routed through a customer gateway. Chat output pasted into an editor never passes through it either. Both will
   show as human.
10. **Relationship to spec 002.** Replace hooks, complement them (hooks where available, gateway elsewhere), or
    compare them head to head on the same scenario set?

## 10. Open questions for intake

- Does the new repository **reuse the homelab** (its gateway, the harness machines, `aiattr`'s
  fingerprinting and record format), or start fresh?
- Is the **goal learning and a published report** (as for specs 001 and 002), or a design an enterprise could
  adopt, or both?
- Is the **PR check** the primary variant, with the git hook optional? Which forge: GitHub, or a self-hosted one
  in the homelab?
- Must results be **signed and verifiable** like spec 002, or is a measured attribution enough at first?
- **HMAC or plain hashes?** HMAC protects short lines but rules out offline lookup from a file copy.
- Are the **four categories** (AI unmodified, AI modified, human, indeterminate) the reporting model, and how do
  they map onto Agent Trace's `ai` / `mixed` / `human` / `unknown`?
- Is **fuzzy matching** (TLSH, token or edit-distance similarity) acceptable, or exact matches only at first?
- Which harnesses are in scope for the lab? The lab has OpenCode and Claude Code. Cursor and Copilot can only be
  included if they can be pointed at the gateway.
- Does the new repository get its **own constitution**, or inherit `ai-gateway`'s v1.1.1 (section 11)?

## 11. Constraints carried over (from the `ai-gateway` constitution v1.1.1, unless the new repo decides otherwise)

*Redacted before publication.* These were the private lab's own operating rules (hardware, hosting, access). The intake
recorded on 2026-10-14 that they do not carry over, and this repository got its own constitution
(`.specify/memory/constitution.md`).

## 12. Glossary

- **Harness:** an AI coding tool that runs an agent against files (Claude Code, OpenCode, Cursor, Copilot agent mode).
- **Gateway:** the proxy every model request passes through; checks identity and policy, records each request.
- **Session:** one agent conversation; harnesses send its ID with each request.
- **Tool call:** one agent action (edit a file, run a command), with its own ID in the model's response.
- **Fingerprint:** a short keyed hash of one normalised line; matches identical lines without storing code.
- **HMAC:** a hash computed with a secret key, so only the key holder can produce or check fingerprints.
- **Run:** consecutive matching lines; spec 002 requires at least three for a match to count.
- **Three-dot diff (merge-base...head):** only the changes made on the PR branch, excluding anything merged in
  from the base branch.
- **Ingestion watermark:** the point up to which captured fingerprints have been stored; PR checks wait for it.
- **AI unmodified / AI modified / human / indeterminate:** exact match to model output; similar to model output
  from the same file and session; no match; too common to tell.
- **TLSH:** a fuzzy hash whose distance measures how similar two texts are, used by aigit for edited code.
