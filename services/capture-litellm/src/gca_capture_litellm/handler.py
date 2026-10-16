"""LiteLLM capture callback (T044; research R3; contracts/gateway-capture.md).

Loaded by the proxy via ``litellm_settings.callbacks: ["gca_capture_litellm.handler.handler"]``. Runs after the
response has been returned to the client, so it can never delay a developer. Fingerprints only are published.
Every exception is caught and counted (FR-005a): nothing here may raise into the proxy.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from gca_core.capture_runtime import CaptureRuntime
from gca_core.keys import KeyRing
from gca_core.nats import connect_jetstream, ensure_stream
from gca_core.tools import session_id, tool_hint
from gcattr import ALG, from_litellm
from gcattr.io import fingerprint_outputs

try:  # LiteLLM is present in the gca-litellm image; tests can run without it.
    from litellm.integrations.custom_logger import CustomLogger
except ImportError:  # pragma: no cover
    CustomLogger = object  # type: ignore[misc,assignment]

log = logging.getLogger("gca.capture_litellm")

_CALL_FORMATS = {
    "acompletion": "openai_chat",
    "completion": "openai_chat",
    "aresponses": "openai_responses",
    "responses": "openai_responses",
    "anthropic_messages": "anthropic_messages",
    "aanthropic_messages": "anthropic_messages",
    "agenerate_content": "gemini_native",
    "generate_content": "gemini_native",
    "agenerate_content_stream": "gemini_native",
    "generate_content_stream": "gemini_native",
}
# Call types that never carry model-written code. Anything else unrecognised is counted as loss (FR-007).
_NO_CODE = {
    "embedding",
    "aembedding",
    "moderation",
    "amoderation",
    "image_generation",
    "aimage_generation",
    "transcription",
    "atranscription",
    "speech",
    "aspeech",
    "rerank",
    "arerank",
    "pass_through_endpoint",
}


def _request_headers(kwargs: dict[str, Any], md: dict[str, Any]) -> dict[str, str]:
    """The client's request headers, lower-cased, as the LiteLLM proxy passes them to callbacks."""
    lp = kwargs.get("litellm_params") or {}
    raw = md.get("headers") or (lp.get("proxy_server_request") or {}).get("headers") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k).lower(): str(v) for k, v in raw.items()}


def _metadata(kwargs: dict[str, Any]) -> dict[str, Any]:
    lp = kwargs.get("litellm_params") or {}
    for key in ("metadata", "litellm_metadata"):
        md = lp.get(key) or kwargs.get(key)
        if isinstance(md, dict) and md:
            return md
    return {}


def fingerprint_response(response_obj: Any, call_type: str, ring: KeyRing) -> dict[str, Any]:
    """Pure CPU work, run in a thread. Returns fingerprints only."""
    ring.reload()
    key = ring.active
    api_format = _CALL_FORMATS.get(call_type, "openai_chat")
    result = fingerprint_outputs(from_litellm(response_obj, call_type, api_format), key, ALG)  # type: ignore[arg-type]
    return {
        "api_format": api_format,
        "lines": result.lines,
        "failures": result.failures,
        "tool_call_count": result.tool_call_count,
        "key_gen": key.key_gen,
    }


class GcaHandler(CustomLogger):  # type: ignore[misc]
    def __init__(self) -> None:
        super().__init__()
        self._runtime: CaptureRuntime | None = None
        self._ring: KeyRing | None = None
        self._js: Any = None

    # ------------------------------------------------------------------ lazy setup inside the proxy's event loop
    async def _send(self, subject: str, payload: bytes) -> None:
        if self._js is None:
            _, self._js = await connect_jetstream(os.environ.get("GCA_NATS_URL", "nats://localhost:4222"))
            await ensure_stream(self._js)
        await self._js.publish(subject, payload)

    def runtime(self) -> CaptureRuntime:
        if self._runtime is None:
            self._runtime = CaptureRuntime("litellm", self._send)
            self._runtime.start()
        return self._runtime

    def ring(self) -> KeyRing:
        if self._ring is None:
            self._ring = KeyRing(os.environ.get("GCA_KEYS_DIR", "/var/run/gca/keys"))
        return self._ring

    # ------------------------------------------------------------------ LiteLLM hooks
    async def async_log_success_event(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: Any, end_time: Any
    ) -> None:
        try:
            await self.capture(kwargs, response_obj)
        except Exception:
            log.exception("capture failed")  # never logs content
            self.runtime().emit_failure("publish_failed")

    async def async_log_failure_event(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: Any, end_time: Any
    ) -> None:
        try:
            self.failed(kwargs)
        except Exception:  # never raise into LiteLLM
            log.exception("capture failure handling failed")

    def failed(self, kwargs: dict[str, Any]) -> None:
        """A generative call LiteLLM failed. If the provider refused it (a 4xx: rate limit, bad request, auth), no
        model output was produced and there's no loss. Otherwise (a 5xx, a dropped connection, or a stream LiteLLM
        couldn't read, which it ends mid-response) the developer may already have received output that capture
        never saw: that's counted as loss, never left silent (FR-005; found by the eval, T106)."""
        call_type = str(kwargs.get("call_type") or "")
        if call_type in _NO_CODE:
            return
        exc = kwargs.get("exception")
        status = getattr(exc, "status_code", None)
        if isinstance(status, int) and 400 <= status < 500:
            return
        md = _metadata(kwargs)
        credential = md.get("user_api_key_alias")
        hint = tool_hint(_request_headers(kwargs, md))
        cause = "unexpected_format" if credential else "unknown_credential"
        self.runtime().emit_failure(
            cause,
            credential_id=str(credential) if credential else None,
            api_format=_CALL_FORMATS.get(call_type),
            tool_hint=hint,
        )

    async def capture(self, kwargs: dict[str, Any], response_obj: Any) -> None:
        rt = self.runtime()
        call_type = str(kwargs.get("call_type") or "")
        md = _metadata(kwargs)
        credential = md.get("user_api_key_alias")
        api_format = _CALL_FORMATS.get(call_type)
        hint = tool_hint(_request_headers(kwargs, md))
        if api_format is None and call_type in _NO_CODE:
            return
        if not credential:
            rt.emit_failure("unknown_credential", api_format=api_format, tool_hint=hint)
            return
        if api_format is None:
            # A generative route we don't parse yet: report it rather than drop it silently (FR-007).
            rt.emit_failure("unsupported_combination", credential_id=str(credential), tool_hint=hint)
            return
        result = await asyncio.to_thread(fingerprint_response, response_obj, call_type, self.ring())
        failures: list[str] = result["failures"]
        lines = result["lines"]
        status = (
            "captured" if not failures else ("partial" if lines or result["tool_call_count"] else "failed")
        )
        model = str(md.get("model_group") or kwargs.get("model") or "unknown")
        if status != "failed":
            rt.emit_event(
                api_format=api_format,
                model=model,
                lines=lines,
                tool_call_count=result["tool_call_count"],
                alg=ALG,
                key_gen=result["key_gen"],
                status=status,
                failure_cause=failures[0] if failures else None,
                credential_id=str(credential),
                tool_hint=hint,
                session_id=session_id(_request_headers(kwargs, md)),
            )
        for i, cause in enumerate(failures):
            rt.emit_failure(
                cause,
                credential_id=str(credential),
                api_format=api_format,
                tool_hint=hint,
                count_as_response=status == "failed" and i == 0,
            )


handler = GcaHandler()
