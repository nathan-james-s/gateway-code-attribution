"""Anthropic Messages: ``tool_use`` blocks with ``input_json_delta.partial_json`` fragments."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

from ..types import ApiFormat, CaptureFailure
from ._common import Result, emit_json_call, emit_text, load_json
from .sse import SSEEvent

FORMAT: ApiFormat = "anthropic_messages"


class _Block:
    __slots__ = ("id", "initial", "kind", "name", "parts", "stopped")

    def __init__(self, kind: str) -> None:
        self.kind = kind  # "tool" | "text"
        self.id: str | None = None
        self.name: str | None = None
        self.parts: list[str] = []
        self.initial: dict[str, Any] = {}
        self.stopped = False


def parse_events(events: Iterable[SSEEvent]) -> Iterator[Result]:
    blocks: dict[int, _Block] = {}
    order: list[int] = []
    stop_reason: str | None = None
    for ev in events:
        obj = load_json(ev.data)
        etype = (obj or {}).get("type") or ev.event
        if obj is None or not isinstance(etype, str):
            yield CaptureFailure("unexpected_format", "messages event")
            continue
        if etype == "content_block_start":
            cb = obj.get("content_block") or {}
            idx = int(obj.get("index", 0) or 0)
            kind = "tool" if cb.get("type") in ("tool_use", "server_tool_use") else "text"
            new = _Block(kind)
            new.id, new.name = cb.get("id"), cb.get("name")
            if kind == "tool" and isinstance(cb.get("input"), dict):
                new.initial = cb["input"]
            if kind == "text" and isinstance(cb.get("text"), str):
                new.parts.append(cb["text"])
            blocks[idx] = new
            order.append(idx)
        elif etype == "content_block_delta":
            idx = int(obj.get("index", 0) or 0)
            delta = obj.get("delta") or {}
            target = blocks.get(idx)
            if target is None:
                yield CaptureFailure("unexpected_format", "delta for unknown block")
                continue
            if delta.get("type") == "input_json_delta" and isinstance(delta.get("partial_json"), str):
                target.parts.append(delta["partial_json"])
            elif delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                target.parts.append(delta["text"])
        elif etype == "content_block_stop":
            stopped = blocks.get(int(obj.get("index", 0) or 0))
            if stopped is not None:
                stopped.stopped = True
        elif etype == "message_delta":
            stop_reason = (obj.get("delta") or {}).get("stop_reason") or stop_reason
    text = "".join("".join(blocks[i].parts) for i in order if blocks[i].kind == "text")
    yield from emit_text(FORMAT, text)
    for i in order:
        b = blocks[i]
        if b.kind != "tool":
            continue
        raw = "".join(b.parts)
        if not raw and b.initial:
            raw = json.dumps(b.initial, ensure_ascii=False)
        yield from emit_json_call(
            FORMAT, b.name, raw, b.id, truncated_hint=stop_reason == "max_tokens" or not b.stopped
        )


def parse_body(obj: dict[str, Any]) -> Iterator[Result]:
    content = obj.get("content")
    if not isinstance(content, list):
        yield CaptureFailure("unexpected_format", "messages body")
        return
    truncated = obj.get("stop_reason") == "max_tokens"
    for block in content:
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            yield from emit_text(FORMAT, block["text"])
        elif block.get("type") in ("tool_use", "server_tool_use"):
            raw = json.dumps(block.get("input") or {}, ensure_ascii=False)
            yield from emit_json_call(
                FORMAT, block.get("name"), raw, block.get("id"), truncated_hint=truncated
            )
