# OpenCode

OpenCode reaches the gateway as an OpenAI-compatible provider. Add it to `opencode.json` (project) or
`~/.config/opencode/opencode.json` (user):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "gca": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Gateway Code Attribution",
      "options": {
        "baseURL": "http://localhost:4000/v1",
        "apiKey": "{env:GCA_CREDENTIAL}"
      },
      "models": { "demo-openai": {} }
    }
  },
  "model": "gca/demo-openai"
}
```

```bash
export GCA_CREDENTIAL=sk-gca-...
opencode
```

The key is sent as `Authorization: Bearer`. List each gateway route you want to use under `models`. OpenCode's
session header (`x-opencode-session-id`) is recorded when present; matching never depends on it.
