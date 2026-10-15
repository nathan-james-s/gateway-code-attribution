# R3 validation: LiteLLM 1.105.1 capture, including Gemini's native API

**Date**: 2026-10-14 · **Setup**: kind, chart in LiteLLM mode, `gca-litellm` image (Python 3.12), demo-model,
`gca demo run --gateway litellm` (PR #4 on the test repository), compared with the agentgateway run (PR #2).

## Result: validated

| API format | Route through LiteLLM | Call type seen by the callback | Lines captured | Fingerprints vs agentgateway |
|---|---|---|---|---|
| OpenAI Responses (Codex `apply_patch`) | `/v1/responses` | `aresponses` | 7 | identical |
| OpenAI Chat (OpenCode-style write) | `/v1/chat/completions` | `acompletion` | 15 | identical |
| Anthropic Messages (Write, Edit) | `/v1/messages` | `anthropic_messages` | 12, 6 | identical |
| Gemini native (`write_file`) | `/v1beta/models/{m}:streamGenerateContent` | `agenerate_content_stream` | 12 | identical |

"Identical" compares every captured line's tool and line ordinals, exact fingerprint, MinHash signature, LSH
bands and path fingerprints, event by event. The two PRs' per-line outcomes also agree on all 93 lines.

## Findings that changed the build

1. **Gemini goes through LiteLLM's native route, not the `/gemini` pass-through.** LiteLLM 1.105 serves
   `/v1beta/models/{m}:streamGenerateContent` through its router (so `model_list` applies) and hands callbacks a
   response already converted to its chat shape. The adapter maps the `*generate_content*` call types.
2. **`litellm_settings.turn_off_message_logging` can't be used.** It redacts the response given to *every*
   callback, capture included (content becomes `redacted-by-litellm`). Code is kept out of LiteLLM's storage by
   `store_prompts_in_spend_logs: false` and no other logging callbacks; the privacy audit (T064) checks both. If a
   response is ever redacted (the setting re-enabled, or a client sending LiteLLM's redaction header), capture
   reports it as loss rather than fingerprinting the placeholder.
3. **Virtual keys must start with `sk-`.** Portal keys are `sk-gca-…` for both gateways. Issuing a key with our
   own value and `key_alias`, using it, and deleting it by alias all work.
4. **Prisma's engine path is fixed at build time.** The image builds and runs with
   `PRISMA_BINARY_CACHE_DIR=/opt/prisma`, and the pod mounts writable `/tmp` and home directories under a
   read-only root filesystem.
5. **Unknown generative call types are counted** as `unsupported_combination` loss, never skipped silently.

Fixtures: `lib/tests/fixtures/litellm_1_105/` holds the objects LiteLLM handed the callback; the parity test is
`services/capture-litellm/tests/test_parity_objects.py`.
