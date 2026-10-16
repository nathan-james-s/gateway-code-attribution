# Supported tools

A coding tool is listed here only once real traffic from it, recorded with its owner's consent, is in the corpus
and passes conformance on both gateways (FR-045; eval/corpus). `scripts/check-supported-tools.sh` enforces this in
CI. Other tools may still route through the gateway (see [README.md](README.md)), but their attribution rests on
scripted sessions only.

| Tool | Corpus | Recorded with | API |
|---|---|---|---|
| Claude Code | `claude-code` | 2.1.292 | Anthropic Messages |

Codex CLI, Gemini CLI and OpenCode are in scope (FR-041) and route through the gateway, but recording their
corpora is deferred past v1. To add one, record it as described in
[eval/corpus/README.md](../../eval/corpus/README.md) and list it here.
