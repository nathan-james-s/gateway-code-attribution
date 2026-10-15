"""Map LiteLLM's reassembled responses to ``CapturedToolOutput`` (research R3, R4).

LiteLLM translates Anthropic ``/v1/messages`` into the OpenAI chat shape before callbacks see it, so
``anthropic_messages`` uses the same path as ``acompletion``. Truncated arguments arrive as invalid JSON with
``finish_reason == "length"`` (probe finding).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from ..streams._common import Result, emit_json_call, emit_text
from ..types import ApiFormat, CapturedToolOutput, CaptureFailure

__all__ = ["from_litellm"]

_CHAT_CALL_TYPES = {"acompletion", "completion", "anthropic_messages"}
_RESPONSES_CALL_TYPES = {"aresponses", "responses"}
# LiteLLM substitutes this for content when message logging is turned off (litellm.constants.REDACTED_BY_LITELLM).
REDACTED = "redacted-by-litellm"
_GEMINI_CALL_TYPES = {
    "agenerate_content",
    "generate_content",
    "agenerate_content_stream",
    "generate_content_stream",
}


def _as_dict(obj: Any) -> dict[str, Any] | None:
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        value = dump()
        return value if isinstance(value, dict) else None
    return None


def from_litellm(response_obj: Any, call_type: str, api_format: ApiFormat | None = None) -> Iterator[Result]:
    if f'"{REDACTED}"' in json.dumps(_as_dict(response_obj) or {}, default=str):
        # Fingerprinting the placeholder would record wrong lines; report the response as lost instead.
        yield CaptureFailure("unexpected_format", "litellm redacted the response (message logging is off)")
        return
    if call_type in _GEMINI_CALL_TYPES and "choices" in (_as_dict(response_obj) or {}):
        # LiteLLM 1.105 hands callbacks Gemini responses already converted to its chat shape.
        yield from from_litellm(response_obj, "acompletion", api_format or "gemini_native")
        return
    if call_type in _GEMINI_CALL_TYPES:
        # Gemini's native generateContent shape: one response object, or the list of streamed chunks.
        from ..streams import parse_stream

        items = response_obj if isinstance(response_obj, list) else [response_obj]
        dicts = [_as_dict(i) for i in items]
        if any(d is None for d in dicts):
            yield CaptureFailure("unexpected_format", "litellm generate_content response is not JSON-like")
            return
        yield from parse_stream("gemini_native", [json.dumps(dicts if len(dicts) > 1 else dicts[0]).encode()])
        return
    obj = _as_dict(response_obj)
    if obj is None:
        yield CaptureFailure("unexpected_format", "litellm response is not a dict or pydantic model")
        return
    if call_type in _RESPONSES_CALL_TYPES or "output" in obj:
        fmt: ApiFormat = api_format or "openai_responses"
        incomplete = obj.get("status") == "incomplete"
        for item in obj.get("output") or []:
            item = _as_dict(item) or {}
            kind = item.get("type")
            if kind == "function_call":
                yield from emit_json_call(
                    fmt,
                    item.get("name"),
                    item.get("arguments") or "",
                    item.get("call_id"),
                    truncated_hint=incomplete,
                )
            elif kind == "custom_tool_call":
                yield CapturedToolOutput(
                    fmt,
                    item.get("name"),
                    "freeform",
                    item.get("input") or "",
                    not incomplete,
                    item.get("call_id"),
                )
            elif kind == "message":
                for part in item.get("content") or []:
                    part = _as_dict(part) or {}
                    if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                        yield from emit_text(fmt, part["text"])
        return
    if call_type in _CHAT_CALL_TYPES or "choices" in obj:
        fmt = api_format or ("anthropic_messages" if call_type == "anthropic_messages" else "openai_chat")
        choices = obj.get("choices")
        if not isinstance(choices, list):
            yield CaptureFailure("unexpected_format", "litellm chat response without choices")
            return
        for ch in choices:
            ch = _as_dict(ch) or {}
            msg = _as_dict(ch.get("message")) or {}
            if isinstance(msg.get("content"), str):
                yield from emit_text(fmt, msg["content"])
            for tc in msg.get("tool_calls") or []:
                tc = _as_dict(tc) or {}
                fn = _as_dict(tc.get("function")) or {}
                yield from emit_json_call(
                    fmt,
                    fn.get("name"),
                    fn.get("arguments") or "",
                    tc.get("id"),
                    truncated_hint=ch.get("finish_reason") == "length",
                )
        return
    yield CaptureFailure("unexpected_format", f"unsupported litellm call type {call_type!r}")
