# Contract: Gateway capture integrations

Both integrations must produce **identical fingerprint multisets per capture event** for the same traffic
(FR-006). `tests/conformance/` enforces this (R4). Both fail open (FR-005a) and keep content in memory only
(Constitution II).

## agentgateway 1.6.0: `capture-extproc` (R2)

**Gateway configuration** (rendered by the chart, standalone mode):

```yaml
llm:
  policies:
    apiKey:                                  # R5: personal credentials rendered by the portal
      mode: strict
      location:
        expression: >-                       # accept the tool's native header
          has(request.headers["x-api-key"]) ? request.headers["x-api-key"] :
          has(request.headers["x-goog-api-key"]) ? request.headers["x-goog-api-key"] :
          request.headers["authorization"].stripPrefix("Bearer ")
      keys: []                               # [{keyHash: "sha256:…", metadata: {github_id, credential_id}}]
    extProc:
      host: capture-extproc.<ns>.svc:9000
      failureMode: failOpen
      processingOptions:
        requestHeaderMode: send
        responseHeaderMode: send
        requestBodyMode: none
        responseBodyMode: fullDuplexStreamed
      metadataContext:                       # identity + tool hints; no content
        gca:
          credential_id: 'apiKey.metadata.credential_id'
          github_id: 'apiKey.metadata.github_id'
          api_format: 'llm.inputFormat'       # exact CEL name confirmed in the R2 validation task
          model: 'llm.requestModel'
  models: []                                 # demo: routes to demo-model; BYO: real providers with Secret keys
```

**Processor behaviour**:
- **Pass-through:** echo every response body chunk immediately and unchanged. Never alter or delay headers or
  bodies.
- **Reassembly:** feed the chunks to `gcattr.parse_stream(api_format, …)` in a background task with a bounded
  per-stream buffer (default 8 MiB; overflow → `CaptureFailure(unexpected_format)`). The buffer is released when
  the stream ends.
- **Publishing:** publish `event` and `failure` messages and 5-second `heartbeat`s
  ([capture-event.schema.json](./capture-event.schema.json)). An event larger than 900 KB of fingerprints is
  sent as parts of one event, under NATS's 1 MiB `max_payload`. A message the server refuses anyway is dropped
  at once and reported as `publish_failed`; it is never retried, since a retry would hold back every message
  behind it.
- **No identity:** if the processor gets no identity metadata, it publishes `failure(unknown_credential)` and
  never matches.

## LiteLLM 1.105.1: `capture-litellm` (R3)

**Proxy configuration** (rendered by the chart):

```yaml
litellm_settings:
  callbacks: ["gcattr_litellm.handler"]
  turn_off_message_logging: true              # Constitution II
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY   # generated at install; used only by the portal
  database_url: os.environ/DATABASE_URL       # the stack's Postgres (separate schema "litellm")
  disable_spend_logs: false                   # spend logs keep usage only
  store_prompts_in_spend_logs: false          # pinned explicitly (Constitution II); privacy audit asserts it
model_list: []                                # demo-model routes or BYO providers
```

**Handler behaviour**:
- **Success path:** `async_log_success_event` passes the response to `gcattr.from_litellm(response_obj,
  call_type)` and then `gcattr.extract(...)`. Identity comes from `user_api_key_user_id`, which is the GitHub ID
  set on the virtual key.
- **Failure path:** `async_log_failure_event`, and any response with an unparsable or truncated tool call,
  produce a `failure` message with a cause.
- **Fail open:** handler exceptions are caught and counted (`publish_failed` or `unparsable`), and never
  propagate into the proxy.
- **Publishing:** the same message contract, heartbeats and per-process `instance_id` as `capture-extproc`.

## Shared obligations

| Obligation | Check |
|---|---|
| Fingerprint-only messages | schema `additionalProperties: false` on line items; privacy audit (SC-006) |
| Fail open | e2e: stop capture or NATS mid-stream; requests still succeed; a loss is recorded (spec US4 scenario 4) |
| Parity | conformance suite: same recorded streams through both gateways → identical `(t, l, x, m, b, p)` multisets |
| Unsupported combinations | if an integration can't see a tool or API combination, it emits `failure(unsupported_combination)` with `tool_hint`; the coverage view shows "not observed" (FR-007) |
