# Contributing

## Workflow

Features follow the Spec Kit sequence: `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` →
`/speckit-tasks` → `/speckit-implement`. Every plan passes a Constitution Check against
`.specify/memory/constitution.md`.

## Merge gates (constitution: Development Workflow & Quality Gates)

| Change touches | Gate |
|---|---|
| `lib/` | determinism + golden tests; full scenario set; outcome diff vs previous algorithm version |
| `services/capture-*`, `services/core/` | cross-gateway conformance suite |
| any data path | privacy audit (no code or prompt text in storage, logs, traces) |
| `charts/`, `services/` | clean install from scratch reaches a first result |
| a coding tool listed as supported | recorded real traffic in `eval/corpus/` |

AI-assisted development is welcome; it does not relax any gate.

## Local setup

```bash
uv sync --all-packages -p 3.12
make lint test-lib
```
