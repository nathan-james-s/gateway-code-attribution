"""Reassemble model responses (streamed SSE or plain JSON) into code-bearing outputs (research R2, R7).

``parse_stream`` never raises on bad input: problems are yielded as ``CaptureFailure`` so callers count loss.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

from ..types import API_FORMATS, ApiFormat, CapturedToolOutput, CaptureFailure
from . import anthropic, gemini, openai_chat, openai_responses
from .sse import iter_events

__all__ = ["parse_stream"]

_MODULES: dict[str, Any] = {
    "openai_chat": openai_chat,
    "openai_responses": openai_responses,
    "anthropic_messages": anthropic,
    "gemini_native": gemini,
}


def parse_stream(
    api_format: ApiFormat, chunks: Iterable[bytes]
) -> Iterator[CapturedToolOutput | CaptureFailure]:
    if api_format not in API_FORMATS:
        yield CaptureFailure("unexpected_format", f"unknown api format {api_format!r}")
        return
    module = _MODULES[api_format]
    data = b"".join(chunks)
    head = data.lstrip()[:1]
    try:
        if head in (b"{", b"["):
            try:
                body = json.loads(data.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                yield CaptureFailure("unparsable", "response body is not JSON")
                return
            if not isinstance(body, dict | list) or (
                isinstance(body, list) and api_format != "gemini_native"
            ):
                yield CaptureFailure("unexpected_format", "response body shape")
                return
            yield from module.parse_body(body)
        else:
            yield from module.parse_events(iter_events([data]))
    except (AttributeError, TypeError, ValueError, KeyError) as exc:  # schema-deviant input must never raise
        yield CaptureFailure("unexpected_format", type(exc).__name__)
