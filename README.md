# Gateway Code Attribution

An open-source reference stack that tells you, line by line, how much of each GitHub pull request came from AI.
Developers' coding tools reach their models through an AI gateway (agentgateway or LiteLLM). The stack captures
**keyed fingerprints** of what the models write there, and when a PR is opened it posts a check that classifies
every added line. Nothing is installed on developers' machines or in their tools: they change an endpoint and a
key. No code, prompts or model output is ever stored.

## What each line is called

| Outcome | Meaning |
|---|---|
| **AI, unmodified** | Exactly what the author's AI tool produced through the gateway (within 14 days by default). |
| **AI, modified (anchored)** | Similar to output from an AI response that produced an exact match in the same file: typically an AI line someone edited. High confidence. |
| **AI, modified (broad)** | Similar to output from any of the author's AI responses: typically AI code moved and adapted. Lower confidence. |
| **Human** | No match to observed AI output. Not proof a person typed it: code from tools the gateway can't see lands here too. |
| **Indeterminate** | Too short or too common to attribute honestly (`}`, `return`, `import os`). |
| **Not observed** *(state)* | The commit's author isn't linked to a gateway credential, so nothing is guessed. |

More in [docs/outcomes.md](docs/outcomes.md).

## Quality

From the release gate, which runs the published scenario set through both gateways on every PR to `main` and
blocks releases below the bar ([contracts/quality-report.schema.json](specs/001-gateway-code-attribution/contracts/quality-report.schema.json)).
Latest green run (PR #9, 375 labelled lines, including recorded real Claude Code traffic):

| Measure | agentgateway | LiteLLM | Bar |
|---|---|---|---|
| Accuracy | 98.7% | 98.7% | ≥ 95% |
| Human lines wrongly called AI modified (anchored / broad) | 0% / 0% | 0% / 0% | ≤ 2% / ≤ 5% |
| AI lines a formatter changed, called human | 0% | 0% | ≤ 10% |
| AI lines surviving rebase and squash | 100% | 100% | |
| Responses lost without being reported | 0 | 0 | 0 |
| Same outcome on both gateways | 100% | | 100% |

The scenario set is synthetic apart from one recorded tool session, so treat these as a floor on correctness,
not a measurement of your codebase.

## Supported tools

Every tool that speaks the Anthropic, OpenAI or Gemini APIs can route through the gateway
([docs/tools/](docs/tools/README.md)). A tool is listed as **supported** once real traffic from it is recorded,
with its owner's consent, and passes conformance on both gateways ([docs/tools/supported.md](docs/tools/supported.md)):

- **Claude Code** (recorded with 2.1.292)

Codex CLI, Gemini CLI and OpenCode route through the gateway but aren't recorded yet.

## Documentation

- [Install](docs/install.md), [configuration reference](docs/configuration.md), [upgrading](docs/upgrade.md),
  [sizing](docs/sizing.md)
- [The GitHub App](docs/github-app.md): every permission and why
- [Routing coding tools](docs/tools/README.md)
- [Privacy assessment](docs/privacy.md): what the fingerprints reveal, and to whom
- [The matching library `gcattr`](docs/library.md), usable on its own
- [Specification, plan and research](specs/001-gateway-code-attribution/)

## Jurisdiction

This is a US-based project. It isn't designed around GDPR or works-council requirements; adopters elsewhere are
responsible for their own compliance.

Licensed under the [Apache License 2.0](LICENSE).
