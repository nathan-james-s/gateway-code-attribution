"""Render tool calls as real provider responses, streamed (SSE) or whole (JSON). Ported from the probe."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from .sessions import ToolCall

__all__ = ["render"]

TEXT = "Working on it."


def _frags(s: str, n: int = 5) -> list[str]:
    return [s[i : i + n] for i in range(0, len(s), n)] or [""]


def _sse(data: Any, event: str | None = None) -> str:
    head = f"event: {event}\n" if event else ""
    return (
        head + "data: " + (data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)) + "\n\n"
    )


def _openai_chat(calls: Sequence[ToolCall], model: str, stream: bool) -> str:
    if not stream:
        msg = {
            "role": "assistant",
            "content": TEXT,
            "tool_calls": [
                {
                    "id": c.call_id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.args)},
                }
                for c in calls
            ]
            or None,
        }
        return json.dumps(
            {
                "id": "chatcmpl-demo",
                "object": "chat.completion",
                "created": 1,
                "model": model,
                "choices": [{"index": 0, "finish_reason": "tool_calls" if calls else "stop", "message": msg}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 50, "total_tokens": 60},
            }
        )
    base = {"id": "chatcmpl-demo", "object": "chat.completion.chunk", "created": 1, "model": model}

    def chunk(delta: dict[str, Any], finish: str | None = None) -> str:
        return _sse({**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]})

    out = [chunk({"role": "assistant", "content": TEXT})]
    for idx, c in enumerate(calls):
        fn = {"name": c.name, "arguments": ""}
        out.append(
            chunk({"tool_calls": [{"index": idx, "id": c.call_id, "type": "function", "function": fn}]})
        )
        for f in _frags(json.dumps(c.args)):
            out.append(chunk({"tool_calls": [{"index": idx, "function": {"arguments": f}}]}))
    out.append(chunk({}, "tool_calls" if calls else "stop"))
    out.append(_sse("[DONE]"))
    return "".join(out)


def _openai_responses(calls: Sequence[ToolCall], model: str, stream: bool) -> str:
    done_items: list[dict[str, Any]] = []
    for i, c in enumerate(calls):
        if c.freeform is not None:
            done_items.append(
                {
                    "type": "custom_tool_call",
                    "id": f"ctc_{i}",
                    "call_id": c.call_id,
                    "name": c.name,
                    "input": c.freeform,
                    "status": "completed",
                }
            )
        else:
            done_items.append(
                {
                    "type": "function_call",
                    "id": f"fc_{i}",
                    "call_id": c.call_id,
                    "name": c.name,
                    "arguments": json.dumps(c.args),
                    "status": "completed",
                }
            )
    resp = {
        "id": "resp_demo",
        "object": "response",
        "created_at": 1,
        "model": model,
        "status": "in_progress",
        "output": [],
    }
    usage = {
        "input_tokens": 10,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": 50,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 60,
    }
    final = {**resp, "status": "completed", "output": done_items, "usage": usage}
    if not stream:
        return json.dumps(final)
    seq = 0

    def ev(t: str, body: dict[str, Any]) -> str:
        nonlocal seq
        seq += 1
        return _sse({"type": t, "sequence_number": seq, **body}, t)

    out = [ev("response.created", {"response": resp})]
    for i, item in enumerate(done_items):
        if item["type"] == "custom_tool_call":
            out.append(
                ev(
                    "response.output_item.added",
                    {"output_index": i, "item": {**item, "input": "", "status": "in_progress"}},
                )
            )
            for f in _frags(item["input"], 7):
                out.append(
                    ev(
                        "response.custom_tool_call_input.delta",
                        {"item_id": item["id"], "output_index": i, "delta": f},
                    )
                )
            out.append(
                ev(
                    "response.custom_tool_call_input.done",
                    {"item_id": item["id"], "output_index": i, "input": item["input"]},
                )
            )
        else:
            out.append(
                ev(
                    "response.output_item.added",
                    {"output_index": i, "item": {**item, "arguments": "", "status": "in_progress"}},
                )
            )
            for f in _frags(item["arguments"]):
                out.append(
                    ev(
                        "response.function_call_arguments.delta",
                        {"item_id": item["id"], "output_index": i, "delta": f},
                    )
                )
            out.append(
                ev(
                    "response.function_call_arguments.done",
                    {"item_id": item["id"], "output_index": i, "arguments": item["arguments"]},
                )
            )
        out.append(ev("response.output_item.done", {"output_index": i, "item": item}))
    out.append(ev("response.completed", {"response": final}))
    return "".join(out)


def _anthropic(calls: Sequence[ToolCall], model: str, stream: bool) -> str:
    stop = "tool_use" if calls else "end_turn"
    if not stream:
        content: list[dict[str, Any]] = [{"type": "text", "text": TEXT}]
        content += [{"type": "tool_use", "id": c.call_id, "name": c.name, "input": c.args} for c in calls]
        return json.dumps(
            {
                "id": "msg_demo",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": content,
                "stop_reason": stop,
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 50},
            }
        )
    msg = {
        "id": "msg_demo",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 1},
    }
    out = [_sse({"type": "message_start", "message": msg}, "message_start")]
    out.append(
        _sse(
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            "content_block_start",
        )
    )
    out.append(
        _sse(
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": TEXT}},
            "content_block_delta",
        )
    )
    out.append(_sse({"type": "content_block_stop", "index": 0}, "content_block_stop"))
    for i, c in enumerate(calls, start=1):
        block = {"type": "tool_use", "id": c.call_id, "name": c.name, "input": {}}
        out.append(
            _sse({"type": "content_block_start", "index": i, "content_block": block}, "content_block_start")
        )
        for f in _frags(json.dumps(c.args, ensure_ascii=False), 6):
            delta = {"type": "input_json_delta", "partial_json": f}
            out.append(
                _sse({"type": "content_block_delta", "index": i, "delta": delta}, "content_block_delta")
            )
        out.append(_sse({"type": "content_block_stop", "index": i}, "content_block_stop"))
    out.append(
        _sse(
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop, "stop_sequence": None},
                "usage": {"output_tokens": 50},
            },
            "message_delta",
        )
    )
    out.append(_sse({"type": "message_stop"}, "message_stop"))
    return "".join(out)


def _gemini(calls: Sequence[ToolCall], model: str, stream: bool) -> str:
    parts = [{"functionCall": {"name": c.name, "args": c.args}} for c in calls]
    usage = {"promptTokenCount": 10, "candidatesTokenCount": 50, "totalTokenCount": 60}
    first = {
        "candidates": [{"content": {"role": "model", "parts": [{"text": TEXT}]}, "index": 0}],
        "modelVersion": model,
    }
    last = {
        "candidates": [
            {
                "content": {"role": "model", "parts": parts or [{"text": ""}]},
                "finishReason": "STOP",
                "index": 0,
            }
        ],
        "usageMetadata": usage,
        "modelVersion": model,
    }
    if not stream:
        whole = {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": TEXT}, *parts]},
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
            "usageMetadata": usage,
            "modelVersion": model,
        }
        return json.dumps(whole)
    return _sse(first) + _sse(last)


_RENDER = {
    "openai_chat": _openai_chat,
    "openai_responses": _openai_responses,
    "anthropic_messages": _anthropic,
    "gemini_native": _gemini,
}


def render(
    api_format: str, calls: Sequence[ToolCall], *, model: str = "demo", stream: bool = True
) -> tuple[str, bytes]:
    """(content type, body)."""
    body = _RENDER[api_format](calls, model, stream)
    return ("text/event-stream" if stream else "application/json"), body.encode("utf-8")
