# Claude Code: corpus setup

- **Tool**: Claude Code 2.1.292
- **Recorded**: 2026-10-15, by the owner (consent.yaml), doing the five tasks in [../tasks.md](../tasks.md) in one
  empty folder and accepting every edit
- **Gateway**: agentgateway, local demo install, route `claude-haiku-5-5` → `anthropic/claude-haiku-5.5` through
  OpenRouter (bring-your-own provider key)
- **Responses**: 18, all Anthropic Messages streams

## Routing (SC-011)

Environment variables only; nothing installed, no plug-in or hook:

```bash
export ANTHROPIC_BASE_URL=http://localhost:4000   # 4100 while recording, the recorder in front of the gateway
export ANTHROPIC_AUTH_TOKEN=sk-gca-...            # the personal gateway key
export ANTHROPIC_MODEL=claude-haiku-5-5 ANTHROPIC_DEFAULT_HAIKU_MODEL=claude-haiku-5-5 ANTHROPIC_SMALL_FAST_MODEL=claude-haiku-5-5
unset ANTHROPIC_API_KEY
CLAUDE_CONFIG_DIR=~/gca-tryout/.claude-profile claude   # optional: a separate profile keeps the usual setup untouched
```

## What the recording showed

- Code is written with `Write` and `Edit` (once with `replace_all`); `Read` and `Bash` are also used. No
  `MultiEdit`: a rename across a file was done by rewriting it with `Write`.
- Thinking blocks arrive with an empty `thinking` and only a `signature_delta`; `message_delta` carries fields the
  scripted fixtures didn't (`container`, `stop_details`, `output_tokens_details`).
- OpenRouter appends `event: data` / `data: [DONE]` after `message_stop`, which isn't part of the Anthropic format.
- Both gateways capture every line the library reads from each recording, with no loss
  (tests/conformance/test_parity.py). Replaying the Write and Edit calls reproduces the task folder byte for byte,
  so the eval scenario `corpus-claude-code` labels the committed files as the model's.
