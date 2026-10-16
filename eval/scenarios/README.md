# The scenario set

The published scenario set that `gca eval` measures attribution quality on (User Story 6; FR-044). Every
release must meet the release bar on it, with each gateway (SC-002, SC-003; `release-gate.yml`).

## A scenario

A directory with:

| File | What it holds |
|---|---|
| `repo.yaml` | the authors (aliases), the model output streams to send (`streams:`), the git operations that build the repository (`operations:`), and the pull request range to attribute (`pr:`) |
| `streams/*.sse` | one recorded model response each, in its API format's wire form |
| `edits.yaml` | how the committed code came from the model output: human edits, formatter passes. For readers; the committed files in `repo.yaml` already include them |
| `expected.json` | the expected outcome of every added line in the PR (`"path:line"`), the tier for AI modified lines, tags (`formatter`, `rewrite`, `lookalike`, `path_only`, `retyped`), the capture loss the streams should cause, and whether the PR has anything attributable |

`streams` entries: `file`, `author` (an alias), `api_format`, and optionally `key_gen` (the fingerprint key
generation active when it's sent, for key rotation) and `fault`: `truncated` and `unexpected_format` streams are
broken on purpose; `dropped` means its capture message is removed before ingest, as a lost message would be.

`operations`: `commit` (`branch`, `author`, `message`, `files`: path to content, or null to delete), `branch`
(`name`, `from`), `rebase` (`branch`, `onto`), `squash` (`from`, `into`, `base`, `author`) and `cherry_pick`
(`branch`, `from`, `since`). Authors listed under `unmapped` are commit authors GitHub links to no account.

Aliases stand for test developers. The runner gives each (scenario, alias) its own GitHub account id and gateway
credential, so one scenario's captures can never match another scenario's lines.

## The set

| Scenarios | What they measure |
|---|---|
| `seed-line-accuracy` (59 lines), `seed-rewrite-rebase`, `seed-rewrite-squash` | spec 002's measured categories (docs/handoffs/gateway-fingerprint-attribution.md section 6): unmodified, edited, typed and trivial lines; agent lines through a rebase onto a moved base and `merge --squash`. Recreated here: the original spec 002 files weren't available |
| `seed-codex-apply-patch` | Codex's freeform `apply_patch` through the Responses API |
| `human-edits-*` | single-token edits, renamed identifiers, added arguments, edited strings, a deleted-then-retyped line, edits moved to other files (broad), a path-only case (broad or human, never anchored), and model output that was never committed |
| `formatters-*` | Black (Python), Prettier (TypeScript) and gofmt (Go) over AI output, at the versions in `eval/harness/formatters.lock` |
| `lookalike-*` | human code that looks like typical AI output but has no matching capture (false AI modified rate) |
| `refactor-*` | extraction into a new file with renames |
| `multi-author-*` | two developers with credentials, one without captures, one GitHub can't link (not observed) |
| `faults-*` | truncated and schema-deviant streams and a lost capture message, with the loss each must cause |
| `key-rotation-*` | output captured before and after a fingerprint key rotation, matched by one PR |
| `empty-*` | deletion-only and excluded-only PRs: nothing attributable, not 0% |

## Writing scenarios

Scenarios are generated from `generate.py`, which writes each file as labelled lines (what the model wrote, what a
person typed or changed). The labels come from how the scenario is written, never from the algorithm:

```bash
uv run python eval/scenarios/generate.py                 # everything except formatters-*
uv run python eval/scenarios/generate.py --formatters    # also formatters-* (needs uv and Docker)
```

Then `uv run gca eval --gateway both --out report.json`. A trivial line (too short, no identifier or literal, or
common boilerplate; research R10) is expected to be indeterminate whoever wrote it.
