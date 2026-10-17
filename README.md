<h1 align="center">Gateway Code Attribution</h1>

<p align="center">
  <b>How much of that pull request did the AI write?</b><br>
  Line-by-line answers, measured at the AI gateway. Nothing installed on developers' machines. No code ever stored.
</p>

<p align="center">
  <a href="https://github.com/nathan-james-s/gateway-code-attribution/actions/workflows/ci.yml"><img alt="ci" src="https://github.com/nathan-james-s/gateway-code-attribution/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/nathan-james-s/gateway-code-attribution/actions/workflows/release-gate.yml"><img alt="release gate" src="https://github.com/nathan-james-s/gateway-code-attribution/actions/workflows/release-gate.yml/badge.svg"></a>
  <img alt="python 3.12" src="https://img.shields.io/badge/python-3.12-blue">
</p>

> **Status:** a complete, working reference implementation, published to be read and tried. It is
> **public but not open source**: no releases, no roadmap, no contributions. See [License](#license).

---

## The idea in thirty seconds

Every line an AI coding tool writes starts life as **model output**, and in a governed setup all model output
already passes through one place: the AI gateway. So watch it there.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/overview-dark.svg">
    <img alt="Coding tools send requests through the AI gateway, which forwards them to the model provider and returns responses untouched. A copy of each response goes to capture, which reassembles tool calls, fingerprints every code line with an HMAC and drops the text; the fingerprints flow through NATS and ingest into PostgreSQL, which never holds code or prompts. When a pull request is opened, the PR check fingerprints each added line with the same library and key, looks it up among the author's captures from the last 14 days, and labels every line AI unmodified, AI modified, human or indeterminate on a check run and in the portal and Grafana dashboards." src="docs/images/overview.svg" width="1000">
  </picture>
</p>

1. **Capture.** As a model response streams through the gateway, the stack reassembles its tool calls (`Write`,
   `Edit`, `apply_patch`, `write_file`, …), normalizes each line of code and stores a **keyed fingerprint**
   (HMAC) of it. The code itself is never written anywhere.
2. **Match.** When a PR is opened, a GitHub App fingerprints every added line with the same library and the same
   key, and looks for it among what *that developer's* tools produced in the last 14 days.
3. **Report.** A check on the PR classifies every line. Dashboards roll it up per change, repository, team and
   (where allowed) developer.

Developers change two things in their tool: the endpoint and the key. No plug-in, no hook, no agent on the laptop.

## What a PR looks like afterwards

The **AI code attribution** check on the demo PR, from the recorded clean-machine run
([docs/validation/quickstart-run.md](docs/validation/quickstart-run.md)):

| AI, unmodified | AI, modified (anchored) | AI, modified (broad) | Human | Indeterminate |
|:-:|:-:|:-:|:-:|:-:|
| 47 | 1 | 2 | 8 | 35 |

Every line gets exactly one of these, and the stack never guesses:

| Outcome | Meaning |
|---|---|
| **AI, unmodified** | Exactly what the author's AI tool produced through the gateway. |
| **AI, modified (anchored)** | Similar to a line from an AI response that produced an exact match *in the same file*. Typically an AI line someone edited. High confidence. |
| **AI, modified (broad)** | Similar to a line from *any* of the author's AI responses. Typically AI code moved and adapted. Lower confidence, always shown separately. |
| **Human** | No match to observed AI output. Not proof a person typed it: tools the gateway can't see land here too. |
| **Indeterminate** | Too short or too common to attribute honestly (`}`, `return`, `import os`). Left out of percentages. |
| **Not observed** *(state)* | The commit's author isn't linked to a gateway credential, so nothing is guessed. |

Full definitions, coverage states and the percentage rules: [docs/outcomes.md](docs/outcomes.md).

## Why at the gateway?

- **Tool-neutral by construction.** Anything that speaks the Anthropic, OpenAI or Gemini APIs can be routed
  through it. New tool, same capture.
- **Nothing on developer machines.** No hooks to install, keep updated, or quietly disable.
- **A server-side witness.** The fingerprint is taken from the model's response *before* anything touches a file,
  so a mismatch at PR time really means the line changed after generation.
- **Private by design.** Only keyed fingerprints and metadata are stored. Without the key they can't be computed,
  compared or reversed; with it, an operator can only confirm guesses about short lines. The
  [privacy assessment](docs/privacy.md) spells out exactly what is kept and who can read it.
- **Honest about blind spots.** Copilot inline completions, Cursor, pasted chat output: the gateway can't see them,
  and the docs say so ([docs/tools/not-observed.md](docs/tools/not-observed.md)). Capture outages are reported as
  *incomplete coverage* on the PRs they affect, never silently counted as human.

## Quick start

### Two minutes, no cluster: fingerprint a recorded response

The matching library, `gcattr`, is plain Python 3.12 with no dependencies. This fingerprints a recorded Claude
Code response from the test corpus, one JSON line per code line, with nothing but hashes in the output:

```bash
git clone https://github.com/nathan-james-s/gateway-code-attribution && cd gateway-code-attribution
uv sync --all-packages -p 3.12
uv run gca version
head -c 32 /dev/urandom | base64 > key.b64
uv run gca fingerprint --key-file key.b64 --format anthropic_messages < lib/tests/golden/alg-1/inputs/anthropic.sse
```

Then run the library's tests (unit, property-based and a frozen golden corpus checked byte for byte on Linux and
macOS):

```bash
make test-lib
```

[docs/library.md](docs/library.md) shows `gca attribute`, which attributes a local branch the way the PR check does,
and how to call the library from your own code.

### Thirty minutes: the whole stack, on your laptop

You need Docker (or OrbStack), `kind`, `helm`, `kubectl`, `uv` and a signed-in `gh`. The demo needs **no model
and no provider key**: a built-in mock model answers scripted agent sessions through the real capture path.

```bash
uv run gca setup github-app --org <ORG> --namespace gca     # 1. creates the GitHub App from a manifest (browser)
uv run gca demo init-repo --repo <ORG>/gca-sample           # 2. pushes the sample project; install the App on it
make demo GATEWAY=agentgateway                               # 3. kind cluster + the chart, demo mode (or GATEWAY=litellm)
```

Then open http://localhost:8080, sign in with GitHub and choose **Get gateway credential**, and:

```bash
GCA_CREDENTIAL=<key> uv run gca demo run --repo <ORG>/gca-sample   # 4. traffic through the gateway, then a PR
```

Within about two minutes the PR shows the check, http://localhost:3000 shows the Grafana dashboards, and
`make demo-down` deletes the cluster. The step-by-step version, with what each GitHub App permission is for and
how to bring your own provider keys, is in [docs/install.md](docs/install.md).

### Point a real coding tool at it

With the stack up, Claude Code needs exactly this and nothing else:

```bash
export ANTHROPIC_BASE_URL=http://localhost:4000   # the gateway
export ANTHROPIC_AUTH_TOKEN=sk-gca-...            # your personal gateway key from the portal
export ANTHROPIC_MODEL=demo-anthropic             # a model route on the gateway
claude
```

Codex CLI, Gemini CLI and OpenCode: [docs/tools/](docs/tools/README.md).

## Does it actually work?

A release gate runs a published, labelled scenario set through **both** gateways and fails below the bar
([quality-report.schema.json](specs/001-gateway-code-attribution/contracts/quality-report.schema.json)). The
latest run, 375 labelled lines including recorded real Claude Code traffic:

| Measure | agentgateway | LiteLLM | Bar |
|---|:-:|:-:|:-:|
| Accuracy | 98.7% | 98.7% | ≥ 95% |
| Human lines wrongly called AI modified (anchored / broad) | 0% / 0% | 0% / 0% | ≤ 2% / ≤ 5% |
| AI lines a formatter changed, called human | 0% | 0% | ≤ 10% |
| AI lines surviving rebase and squash | 100% | 100% | |
| Responses lost without being reported | 0 | 0 | 0 |
| Same outcome on both gateways | 100% | | 100% |

The scenario set is synthetic apart from one recorded tool session, so read these as a floor on correctness, not
as a measurement of your codebase. What the scenarios cover, and how to add one:
[eval/scenarios/README.md](eval/scenarios/README.md). The measured sizing for 500 developers (storage per line,
ingest rate, PR-check latency, gateway overhead under load) is in [docs/sizing.md](docs/sizing.md).

**Supported tools.** A tool is listed as supported only once real traffic from it has been recorded, with its
owner's consent, and passes conformance on both gateways:

- **Claude Code** (recorded with 2.1.292)

Codex CLI, Gemini CLI and OpenCode route through the gateway and are covered by scripted sessions, but their
recordings were deferred ([docs/tools/supported.md](docs/tools/supported.md)).

## What's in the box

One Helm chart brings up everything:

| Piece | Where | What it does |
|---|---|---|
| **`gcattr`** | [`lib/`](lib/) | The one versioned matching library: normalization, keyed fingerprints, MinHash similarity, stream reassembly for four API formats, tiered matching. Standard library only. |
| **Gateway** | [`charts/`](charts/gateway-code-attribution/) | Your choice of [agentgateway](https://agentgateway.dev) or [LiteLLM](https://docs.litellm.ai), with capture attached: an `ext_proc` processor for agentgateway, a callback for LiteLLM. Identical results either way. |
| **capture-extproc**, **capture-litellm** | [`services/`](services/) | Reassemble streamed tool calls, fingerprint in a worker process, publish to NATS. The gateway fails open; capture never slows a response. |
| **ingest** | `services/ingest` | JetStream consumer into PostgreSQL. Detects loss from sequence gaps and missed heartbeats and keeps the watermark the PR check waits on. |
| **prcheck** | `services/prcheck` | The GitHub App: webhooks or polling, attribution per head, the check run, team sync. |
| **portal** | `services/portal` | GitHub sign-in, personal gateway credentials, per-line views, coverage, admin (roles, key rotation). |
| **Grafana** | `charts/…/dashboards` | Change, repository, team and coverage dashboards over aggregate-only SQL views. |
| **demo** | `services/demo` | A mock model, scripted agent sessions, a sample repository and ten edge-case scenarios (rebase, squash, cherry-pick, paused ingest, unmapped authors, …). |
| **eval** | [`eval/`](eval/) | The scenario set, the recorded corpus, and the harness that produces the quality report. |

Cross-cutting tests live in [`tests/`](tests/): cross-gateway conformance, the privacy audit, end-to-end on kind,
and a Locust performance suite.

## Documentation

| | |
|---|---|
| [Install](docs/install.md) · [Configuration reference](docs/configuration.md) · [Upgrading](docs/upgrade.md) · [Sizing](docs/sizing.md) | Running it |
| [The GitHub App](docs/github-app.md) | Every permission and why |
| [Outcomes](docs/outcomes.md) · [What the gateway can't observe](docs/tools/not-observed.md) | Reading the results |
| [Privacy assessment](docs/privacy.md) | What the fingerprints reveal, and to whom |
| [The `gcattr` library](docs/library.md) | Using the matching on its own |
| [Specification, plan, research, contracts](specs/001-gateway-code-attribution/) | How and why it was built this way |
| [Validation records](docs/validation/) | What was measured on real gateways, and what broke |

## License

None. This is a demo and reference implementation, published to be read and tried, and it carries no license
file. GitHub's terms let you view and fork it here; beyond that, copyright law's defaults apply. Third-party
components keep their own licenses ([NOTICE](NOTICE)). The repository doesn't take contributions
([CONTRIBUTING.md](CONTRIBUTING.md)).

This is a US-based project and isn't designed around GDPR or works-council requirements; adopters elsewhere are
responsible for their own compliance.
