# Validation R2: agentgateway 1.6.0 `extProc` for capture (task T038)

- **Date**: 2026-10-14
- **Gateway**: agentgateway 1.6.0 standalone (`agentgateway-darwin-arm64`, sha256 `6cebe8bd…e9c685`)
- **Setup**: `tests/spikes/run_r2.py` with `tests/spikes/r2_agentgateway.yaml`, a minimal pass-through processor
  (`tests/spikes/extproc_echo.py`, `grpcio` + `xds-protos` 1.84.0) and the assessment probe's mock provider, which
  writes 7-byte chunks.
- **Config under test**: `llm.policies.extProc` with `failureMode: failOpen`,
  `processingOptions.responseBodyMode: fullDuplexStreamed`, `requestHeaderMode: send`, and `metadataContext` from
  the `apiKey` policy.

## Results

| Check | Result | Detail |
|---|---|---|
| (a) Client stream byte-identical to the upstream stream | ✅ pass | Chat (16,520 B), Responses (12,729 B), Anthropic (10,245 B) identical, at 1.1–1.8 s each |
| (b) Processor receives every body chunk | ✅ pass | 2,361 / 1,820 / 1,465 chunks; SHA-256 of the bytes it saw equals the client's; `end_of_stream` seen |
| (d) CEL names for `metadataContext` | ✅ pass, with one change | `apiKey.<field>` (flattened key metadata, for example `apiKey.credential_id`, `apiKey.github_id`) and `request.path` work. **`llm.requestModel` is not available at the ext_proc stage** ("No such key: requestModel"): the model must be read from the response stream. There's no API-format CEL field; the format is derived from `request.path` (T042). |
| API-key policy, multi-header `location.expression` | ✅ pass | `Authorization: Bearer`, `x-api-key` and `x-goog-api-key` → 200; no key or a wrong key → 401 |
| (c) Processor killed: **new** requests | ✅ pass | Logged `failure_mode: FailOpen`; later requests return 200 with full bodies |
| (c) Processor killed: request **in flight** | ❌ **fail** | Status 200 but the body is **truncated**: it ended after 0.15 s versus about 1.1 s normally. Log: `ext_proc response stream failed … ConnectionReset`. `failOpen` does not keep proxying a stream whose processor dies mid-way. |
| (e) Slow processor (0.5 s delay per echoed chunk) | ❌ **fail** | The client received 140 bytes in 10 s. The stream stalls with the processor; no gateway timeout applies. |

### Why there's no gateway-side timeout for (e)

- `llm.policies.timeout.responseIdleTimeout` explicitly excludes "time spent processing the response".
- `requestTimeout` and `backendRequestTimeout` stop applying once response headers arrive.
- `llm.policies.extProc.policies.http.requestTimeout` bounds the whole processor call, so it would cut every long
  stream. It's unusable for this.

## Decision

**Keep `extProc` (research R2).** It's still the only option that keeps code out of gateway logs and traces
(Constitution II) and captures native Gemini. The two failures are about **processor liveness**, not correctness.
So the processor is designed so it can neither stall nor die mid-stream in normal operation, and the residual risk
is stated openly.

Mitigations (folded into T041, T043 and T093):

1. **The echo path never waits on capture work.** Parsing and fingerprinting run in a **separate worker process**
   (a `ProcessPoolExecutor`), not just a background coroutine. CPU-heavy hashing then can't hold the GIL against
   the echo loop. Chunks go to the worker through a bounded per-stream queue. When it's full, copying stops for
   that stream and the stream is counted as `buffer_overflow`; the echo is never delayed.
2. **Self-deadline.** If the echo loop itself sees a chunk waiting longer than 250 ms (for example CPU starvation),
   the processor stops copying for that stream and keeps echoing. If it can't echo at all, it aborts the gRPC
   stream for **new** requests only, which agentgateway then fails open on.
3. **Graceful termination.** On SIGTERM the processor stops accepting new streams and finishes in-flight ones.
   Settings: `terminationGracePeriodSeconds: 330`, a `preStop` hook, and the gRPC server's graceful stop with a
   300 s grace. Rolling updates and scale-downs therefore never truncate responses.
4. **No OOM kills mid-stream.** Per-stream buffers are capped (8 MiB), memory limits are generous, and there are
   at least 2 replicas.
5. **Upstream.** Report to agentgateway that `failOpen` should also cover a processor that fails mid-stream, by
   continuing to proxy the remaining body unprocessed.

**Residual risk, accepted by the owner on 2026-10-14.** If the processor process crashes (not a
graceful stop), responses in flight at that moment are truncated for the developer. Their coding tool sees an
interrupted reply and normally retries. This is narrower than FR-005a's "requests MUST succeed": it holds for every
request except those in flight during a processor crash. T093 (d) measures stall behaviour under load. The
LiteLLM path doesn't have this risk, because its callback runs after the response completes.
