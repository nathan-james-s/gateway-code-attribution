"""OpenAI Responses API: function calls and freeform custom tools (for example Codex ``apply_patch``)."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from ..types import ApiFormat, CapturedToolOutput, CaptureFailure
from ._common import Result, emit_json_call, emit_text, load_json
from .sse import SSEEvent

FORMAT: ApiFormat = "openai_responses"


class _Item:
    __slots__ = ("call_id", "deltas", "done", "kind", "name")

    def __init__(self, kind: str) -> None:
        self.kind = kind  # "function_call" | "custom_tool_call"
        self.call_id: str | None = None
        self.name: str | None = None
        self.deltas: list[str] = []
        self.done: str | None = None  # full value from a .done event, preferred over the deltas


def parse_events(events: Iterable[SSEEvent]) -> Iterator[Result]:
    items: dict[str, _Item] = {}
    order: list[str] = []
    text: list[str] = []
    incomplete = False

    def item_for(item_id: str, kind: str = "function_call") -> _Item:
        if item_id not in items:
            items[item_id] = _Item(kind)
            order.append(item_id)
        return items[item_id]

    for ev in events:
        obj = load_json(ev.data)
        etype = (obj or {}).get("type") or ev.event
        if obj is None or not isinstance(etype, str):
            yield CaptureFailure("unexpected_format", "responses event")
            continue
        if etype in ("response.output_item.added", "response.output_item.done"):
            item = obj.get("item") or {}
            kind = item.get("type")
            if kind in ("function_call", "custom_tool_call") and item.get("id"):
                it = item_for(item["id"], kind)
                it.call_id = item.get("call_id") or it.call_id
                it.name = item.get("name") or it.name
                full = item.get("arguments" if kind == "function_call" else "input")
                if etype.endswith(".done") and isinstance(full, str) and full:
                    it.done = full
        elif etype in ("response.function_call_arguments.delta", "response.custom_tool_call_input.delta"):
            kind = "function_call" if "function_call" in etype else "custom_tool_call"
            if isinstance(obj.get("delta"), str) and obj.get("item_id"):
                item_for(obj["item_id"], kind).deltas.append(obj["delta"])
        elif etype == "response.function_call_arguments.done" and obj.get("item_id"):
            if isinstance(obj.get("arguments"), str):
                item_for(obj["item_id"], "function_call").done = obj["arguments"]
        elif etype == "response.custom_tool_call_input.done" and obj.get("item_id"):
            if isinstance(obj.get("input"), str):
                item_for(obj["item_id"], "custom_tool_call").done = obj["input"]
        elif etype == "response.output_text.delta" and isinstance(obj.get("delta"), str):
            text.append(obj["delta"])
        elif etype == "response.incomplete":
            incomplete = True

    yield from emit_text(FORMAT, "".join(text))
    for item_id in order:
        it = items[item_id]
        value = it.done if it.done is not None else "".join(it.deltas)
        if it.kind == "custom_tool_call":
            complete = it.done is not None and not incomplete
            if not complete:
                yield CaptureFailure("truncated", f"custom tool {it.name!r}")
            yield CapturedToolOutput(FORMAT, it.name, "freeform", value, complete, it.call_id)
        else:
            yield from emit_json_call(
                FORMAT, it.name, value, it.call_id, truncated_hint=incomplete or it.done is None
            )


def parse_body(obj: dict[str, Any]) -> Iterator[Result]:
    output = obj.get("output")
    if not isinstance(output, list):
        yield CaptureFailure("unexpected_format", "responses body")
        return
    incomplete = obj.get("status") == "incomplete"
    for item in output:
        kind = item.get("type")
        if kind == "function_call":
            yield from emit_json_call(
                FORMAT,
                item.get("name"),
                item.get("arguments") or "",
                item.get("call_id"),
                truncated_hint=incomplete,
            )
        elif kind == "custom_tool_call":
            yield CapturedToolOutput(
                FORMAT,
                item.get("name"),
                "freeform",
                item.get("input") or "",
                not incomplete,
                item.get("call_id"),
            )
        elif kind == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    yield from emit_text(FORMAT, part["text"])
