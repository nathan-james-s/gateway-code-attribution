# Gateway Code Attribution

Open-source reference stack that attributes the lines added in each GitHub pull request to AI model output,
using keyed fingerprints captured at an AI gateway (agentgateway or LiteLLM). No per-machine or per-tool
installs; no code or prompts are ever stored.

> Status: under construction. Quality figures are published only after the release gate passes
> (constitution Principle V).

- Install: [docs/install.md](docs/install.md)
- What the outcomes mean: [docs/outcomes.md](docs/outcomes.md)
- Privacy assessment: [docs/privacy.md](docs/privacy.md)
- Library (`gcattr`): [docs/library.md](docs/library.md)
- Specification and plan: [specs/001-gateway-code-attribution/](specs/001-gateway-code-attribution/)

This is a US-based project; it is not designed around GDPR or works-council requirements. Adopters elsewhere
are responsible for their own compliance.

Licensed under the [Apache License 2.0](LICENSE).
