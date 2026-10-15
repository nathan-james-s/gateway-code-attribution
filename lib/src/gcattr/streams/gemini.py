"""Gemini ``streamGenerateContent``: ``functionCall`` parts arrive whole (no ``partial_args``)."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

from ..types import ApiFormat, CaptureFailure
from ._common import Result, emit_json_call, emit_text, load_json
from .sse import SSEEvent

FORMAT: ApiFormat = "gemini_native"


def _parse_chunk(
    obj: dict[str, Any], text: list[str], calls: list[tuple[str | None, str]]
) -> Iterator[Result]:
    candidates = obj.get("candidates")
    if not isinstance(candidates, list):
        if "usageMetadata" in obj:
            return
        yield CaptureFailure("unexpected_format", "gemini chunk")
        return
    for cand in candidates:
        for part in (cand.get("content") or {}).get("parts") or []:
            if isinstance(part.get("text"), str) and not part.get("thought"):
                text.append(part["text"])
            fc = part.get("functionCall")
            if isinstance(fc, dict):
                if "partialArgs" in fc or "partial_args" in fc:
                    yield CaptureFailure("unexpected_format", "gemini partial_args")
                    continue
                calls.append((fc.get("name"), json.dumps(fc.get("args") or {}, ensure_ascii=False)))


def _finish(text: list[str], calls: list[tuple[str | None, str]]) -> Iterator[Result]:
    yield from emit_text(FORMAT, "".join(text))
    for name, raw in calls:
        yield from emit_json_call(FORMAT, name, raw, name, truncated_hint=False)


def parse_events(events: Iterable[SSEEvent]) -> Iterator[Result]:
    text: list[str] = []
    calls: list[tuple[str | None, str]] = []
    for ev in events:
        obj = load_json(ev.data)
        if obj is None:
            yield CaptureFailure("unexpected_format", "gemini event")
            continue
        yield from _parse_chunk(obj, text, calls)
    yield from _finish(text, calls)


def parse_body(obj: dict[str, Any] | list[Any]) -> Iterator[Result]:
    text: list[str] = []
    calls: list[tuple[str | None, str]] = []
    for chunk in obj if isinstance(obj, list) else [obj]:
        if not isinstance(chunk, dict):
            yield CaptureFailure("unexpected_format", "gemini body")
            continue
        yield from _parse_chunk(chunk, text, calls)
    yield from _finish(text, calls)
