# Routing coding tools through the gateway

Each in-scope tool reaches the gateway with **only an endpoint change and your personal gateway key**: no plug-in,
hook or per-machine install (FR-041). Get the key from the portal (**Get gateway credential**); it starts with
`sk-gca-`.

| Tool | Guide | API the gateway sees |
|---|---|---|
| Claude Code | [claude-code.md](claude-code.md) | Anthropic Messages |
| Codex CLI | [codex-cli.md](codex-cli.md) | OpenAI Responses (freeform `apply_patch`) |
| Gemini CLI | [gemini-cli.md](gemini-cli.md) | Gemini `streamGenerateContent` |
| OpenCode | [opencode.md](opencode.md) | OpenAI Chat Completions |

**Model names** must match a model route on the gateway: `demo-anthropic`, `demo-openai` and `demo-gemini` in demo
mode, or the `name` of each entry in `providers.models` when you bring your own provider keys
(see [install.md](../install.md#bring-your-own-provider-keys)).

The gateway URL is `http://localhost:4000` for the local demo, or `gateway.publicUrl` for a real install. Both
gateways (agentgateway and LiteLLM) serve the same paths, so these settings don't change with the gateway.

**Validation status**: routing works with the settings below. A tool is listed as *supported* only after real
traffic from it has been recorded into the evaluation corpus (constitution, "Real-traffic validation"; task
T112): see [supported.md](supported.md). So far that's Claude Code. For the others, attribution is covered by the
scripted demo sessions and fixtures.

Interactions the gateway can't see are listed in [not-observed.md](not-observed.md).
