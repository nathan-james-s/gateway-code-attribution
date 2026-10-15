# Codex CLI

Codex CLI speaks the OpenAI Responses API and edits files with a freeform `apply_patch` tool. Add a provider for
the gateway to `~/.codex/config.toml`:

```toml
model_provider = "gca"
model = "demo-openai"                 # a model route on the gateway

[model_providers.gca]
name = "Gateway Code Attribution"
base_url = "http://localhost:4000/v1"
env_key = "GCA_CREDENTIAL"            # the variable holding your gateway key
wire_api = "responses"
```

```bash
export GCA_CREDENTIAL=sk-gca-...
codex logout                          # important: see below
codex
```

**Run `codex logout` first.** A logged-in ChatGPT session takes precedence over `env_key`, so Codex would talk to
OpenAI directly and the gateway would see nothing. After `codex logout`, Codex sends `GCA_CREDENTIAL` as
`Authorization: Bearer` to the gateway.
