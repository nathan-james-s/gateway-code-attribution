# Contributing

**This repository doesn't take contributions.** It's public so the design and the code can be read, tried and
cited. It isn't an open-source project: there is no roadmap, no release schedule and no maintainer commitment,
and pull requests from outside won't be merged. There is no license file: GitHub's terms let you view and fork
it here, and copyright law's defaults apply beyond that.

If you spot a security problem, follow [SECURITY.md](SECURITY.md).

## How the project was built (for readers)

Every feature followed the Spec Kit sequence: `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` →
`/speckit-tasks` → `/speckit-implement`, with each plan checked against
[`.specify/memory/constitution.md`](.specify/memory/constitution.md). The specification, research, data model,
contracts and task list are all in [`specs/001-gateway-code-attribution/`](specs/001-gateway-code-attribution/),
and the assessment that preceded them in
[`.specify/assessments/gateway-code-attribution/`](.specify/assessments/gateway-code-attribution/).

The CI gates that every change had to pass:

| Change touches | Gate |
|---|---|
| `lib/` | determinism and golden-corpus tests; the full scenario set; an outcome diff against the previous algorithm version |
| `services/capture-*`, `services/core/` | the cross-gateway conformance suite |
| any data path | the privacy audit (no code or prompt text in storage, logs or traces) |
| `charts/`, `services/` | a clean install from scratch that reaches a first result |
| a coding tool listed as supported | recorded real traffic in `eval/corpus/`, with its owner's consent |

Most of the code was written with AI assistance, under those gates.

## Running it yourself

```bash
uv sync --all-packages -p 3.12
make lint test-lib
```
