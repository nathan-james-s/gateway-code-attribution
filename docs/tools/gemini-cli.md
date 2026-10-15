# Gemini CLI

Gemini CLI speaks the native Gemini API (`streamGenerateContent`). Both gateways serve it at the same path.

```bash
export GOOGLE_GEMINI_BASE_URL=http://localhost:4000
export GEMINI_API_KEY=sk-gca-...                      # your personal gateway key
gemini --model demo-gemini                            # a model route on the gateway
```

- By default the key is sent as `x-goog-api-key`, which both gateways accept. To send it as
  `Authorization: Bearer` instead, set `GEMINI_API_KEY_AUTH_MECHANISM=bearer`.
- Use API-key authentication. Signing in with a Google account sends traffic to Google directly, which the
  gateway can't see.
- Through LiteLLM, Gemini's native route was validated on 2026-10-14
  ([R3](../validation/R3-litellm-gemini.md)).
