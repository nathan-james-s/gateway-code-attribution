# Claude Code

Claude Code speaks the Anthropic Messages API. Point it at the gateway with two environment variables:

```bash
export ANTHROPIC_BASE_URL=http://localhost:4000       # the gateway; Claude Code appends /v1/messages
export ANTHROPIC_AUTH_TOKEN=sk-gca-...                # your personal gateway key
export ANTHROPIC_MODEL=demo-anthropic                 # a model route on the gateway
claude
```

- `ANTHROPIC_AUTH_TOKEN` is sent as `Authorization: Bearer`, which both gateways accept. Don't also set
  `ANTHROPIC_API_KEY`: Claude Code would prefer it and send your provider key instead.
- `ANTHROPIC_MODEL` (and `ANTHROPIC_SMALL_FAST_MODEL`, if you use it) must name a gateway route. With your own
  provider keys, either name the route after the model Claude Code requests, for example
  `{name: claude-sonnet-4-5, provider: anthropic, model: claude-sonnet-4-5}`, or set `ANTHROPIC_MODEL` to the route
  name.
- Claude Code's file edits (`Write`, `Edit`, `MultiEdit`) are captured as tool calls. Its session header
  (`x-claude-code-session-id`) is recorded when present; matching never depends on it.
