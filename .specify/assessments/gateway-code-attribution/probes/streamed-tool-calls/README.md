# Probe: can a gateway reassemble streamed tool-call arguments?

- **Run**: 2026-10-14, macOS arm64, Python 3.9 (stdlib) for the probe and Python 3.12 venv for LiteLLM
- **Gateways tested**: LiteLLM proxy 1.105.1 (PyPI), agentgateway 1.6.0 (`agentgateway-darwin-arm64` from the
  GitHub release; sha256 `6cebe8bd…e9c685` matched the published `.sha256`)
- **Question** (research gap): when model output streams through a gateway, can the gateway (or a plug-in to it)
  recover each tool call's complete arguments, byte-exact, so that the code inside can be fingerprinted?

## Method

No provider API keys were available, so a **mock provider** (`mock_upstream.py`) replays synthetic streams
(`fixtures.py`) built to each provider's documented SSE format. The fixtures cover:

| Format | What the fixture contains |
|---|---|
| OpenAI Chat Completions | text, then **two parallel tool calls with interleaved argument fragments** (`write_file`, `edit_file`) |
| OpenAI Responses | a `function_call` (`response.function_call_arguments.delta/.done`) and a **freeform `custom_tool_call` `apply_patch`** (`response.custom_tool_call_input.delta/.done`), with Codex-style patch text |
| Anthropic Messages | a text block, then Claude Code-shaped `Write` and `Edit` `tool_use` blocks via `input_json_delta`, with a `ping` mid-stream |
| Anthropic, truncated | the same, with the stream cut mid-value and `stop_reason: max_tokens` |
| Gemini `streamGenerateContent?alt=sse` | text, then one whole `functionCall` part |

The code in the arguments includes tabs, `\r\n`, an escaped `\n` inside a string literal, quotes, `é` and a 4-byte
emoji. Arguments are split into 5–7-character fragments, so boundaries land inside JSON escapes. The mock then
writes the byte stream in **7-byte HTTP chunks**, which splits SSE lines and, in four of the five fixtures,
multi-byte UTF-8 characters.

Three ways of capturing were checked against ground truth (exact argument equality, plus equal per-line
HMAC fingerprints after NFC + trim):

1. **Reference reassembler** (`reassemble.py`, about 150 lines, stdlib only): raw bytes in, tool calls out.
2. **LiteLLM**: a `CustomLogger` callback (`litellm_cb.py`) records what `async_log_success_event` receives.
3. **agentgateway**: JSON access-log fields from CEL `llm.toolCalls` and `llm.completion` (`ag_config.yaml`).

The client side (raw stream through each gateway, reassembled by `reassemble.py`) was checked as well, to make
sure the gateway didn't change the stream.

## Results

| Path | Chat (parallel) | Responses fn + `apply_patch` | Anthropic `Write`/`Edit` | Anthropic truncated | Gemini |
|---|---|---|---|---|---|
| Reference reassembler, direct | ✅ 2/2 | ✅ 2/2 (deltas = `.done`) | ✅ 2/2 | ✅ `Write`; `Edit` flagged invalid JSON | ✅ 1/1 |
| LiteLLM callback | ✅ 2/2 | ✅ 2/2 | ✅ 2/2 (translated to OpenAI shape) | ✅ `Write`; `Edit` passed as raw invalid JSON, `finish_reason: length` | ✅ 1/1 via OpenAI-format route (LiteLLM-made call id) |
| agentgateway `llm.toolCalls`, streamed | ✅ 2/2 (args as objects) | ✅ 2/2 (`apply_patch` as string)* | ✅ 2/2 | ✅ `Write`; `Edit` logged as raw string | ❌ **native path: none logged**; ✅ via OpenAI-format route |
| agentgateway `llm.toolCalls`, non-streamed | ✅ | ✅ | ✅ | n/a | not tested |
| Client stream through either gateway | ✅ unchanged | ✅ (LiteLLM appends a non-standard `data: [DONE]`) | ✅ | ✅ | ✅ |

\* **Silent capture loss when events don't match the expected schema.** The first Responses fixture left out
`created_at` and the usage `*_details` fields, which real OpenAI responses include. agentgateway still streamed it
to the client, but logged `llm.toolCalls = null` and raised no error. Its typed parser treats non-matching events
as raw and records only usage from them (`crates/llm/src/conversion/responses.rs`, `passthrough_stream`). With the
fields added (matching agentgateway's own test fixture `stream-custom-tool.json`), capture worked.

**Native Gemini gap (source-confirmed).** In agentgateway 1.6.0, `vertex_gemini::passthrough_stream` collects
usage and completion text only. It has no tool-call accumulator, so a native-Gemini client such as Gemini CLI
won't show up in `llm.toolCalls`.

## What this shows, and what it doesn't

- **Shows:** reassembling streamed arguments is a solved, small problem. That holds even with split UTF-8, split
  escapes, interleaved parallel calls and freeform patch tools. Both gateways already do it internally for the main
  formats, and hand a plug-in complete, byte-exact arguments. Fingerprints computed from gateway-side captures
  matched ground truth in every complete case.
- **Shows:** truncated (`max_tokens`) tool calls reach the plug-in as invalid JSON. Capture must detect them and
  either drop them or salvage them line by line, never crash.
- **Doesn't show:**
  - Behaviour against **real provider streams.** The fixtures are synthetic, built from docs.
  - Real **Claude Code, Codex, Gemini CLI or OpenCode** traffic: actual tool names and schemas, whether Codex really
    uses freeform `apply_patch`, and Claude Code's `MultiEdit` and other tools.
  - Performance or buffer limits for large file writes. agentgateway warns `llm.toolCalls` has "performance
    impacts for large responses", and `maxBufferSize` applies.
  - LiteLLM's native `/gemini` pass-through route.
  - Envoy AI Gateway, Portkey and Kong.

## Reproduce

```bash
python3 mock_upstream.py 18080 &                         # mock provider
python3 client_check.py http://127.0.0.1:18080           # reference reassembler, direct
# LiteLLM (needs `pip install 'litellm[proxy]'`):
LITELLM_MASTER_KEY=sk-probe litellm --config litellm_config.yaml --port 14000 &
python3 client_check.py http://127.0.0.1:14000 openai_chat openai_responses anthropic anthropic_truncated
python3 litellm_verify.py
# agentgateway 1.6.0:
agentgateway -f ag_config.yaml > ag.log 2>&1 &
python3 ag_verify.py
```

All keys in these files (`sk-mock`, `sk-probe`, `probe-key`) are placeholders for the local mock.
