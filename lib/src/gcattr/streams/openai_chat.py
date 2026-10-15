"""OpenAI Chat Completions: streamed ``delta.tool_calls[i].function.arguments`` fragments, keyed by index."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from ..types import ApiFormat, CaptureFailure
from ._common import Result, emit_json_call, emit_text, load_json
from .sse import SSEEvent

FORMAT: ApiFormat = "openai_chat"


class _Call:
    __slots__ = ("args", "id", "name")

    def __init__(self) -> None:
        self.id: str | None = None
        self.name: str | None = None
        self.args = ""


def parse_events(events: Iterable[SSEEvent]) -> Iterator[Result]:
    calls: dict[tuple[int, int], _Call] = {}
    order: list[tuple[int, int]] = []
    text: dict[int, list[str]] = {}
    finish: dict[int, str | None] = {}
    for ev in events:
        obj = load_json(ev.data)
        if obj is None or ("choices" not in obj and "usage" not in obj):
            yield CaptureFailure("unexpected_format", "chat chunk")
            continue
        choices: Any = obj.get("choices") or []
        for ch in choices:
            if not isinstance(ch, dict):
                yield CaptureFailure("unexpected_format", "chat choice")
                continue
            ci = int(ch.get("index", 0) or 0)
            delta = ch.get("delta") or {}
            if isinstance(delta.get("content"), str):
                text.setdefault(ci, []).append(delta["content"])
            for tc in delta.get("tool_calls") or []:
                key = (ci, int(tc.get("index", 0) or 0))
                if key not in calls:
                    calls[key] = _Call()
                    order.append(key)
                call = calls[key]
                call.id = tc.get("id") or call.id
                fn = tc.get("function") or {}
                call.name = fn.get("name") or call.name
                if isinstance(fn.get("arguments"), str):
                    call.args += fn["arguments"]
            if ch.get("finish_reason"):
                finish[ci] = ch["finish_reason"]
    for _ci, parts in sorted(text.items()):
        yield from emit_text(FORMAT, "".join(parts))
    for key in order:
        call = calls[key]
        yield from emit_json_call(
            FORMAT, call.name, call.args, call.id, truncated_hint=finish.get(key[0]) == "length"
        )


def parse_body(obj: dict[str, Any]) -> Iterator[Result]:
    choices = obj.get("choices")
    if not isinstance(choices, list):
        yield CaptureFailure("unexpected_format", "chat body")
        return
    for ch in choices:
        msg = ch.get("message") or {}
        if isinstance(msg.get("content"), str):
            yield from emit_text(FORMAT, msg["content"])
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            yield from emit_json_call(
                FORMAT,
                fn.get("name"),
                fn.get("arguments") or "",
                tc.get("id"),
                truncated_hint=ch.get("finish_reason") == "length",
            )
