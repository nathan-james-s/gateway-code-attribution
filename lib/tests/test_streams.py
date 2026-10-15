"""T023: stream reassembly across chunk sizes, truncation, schema-deviant input and JSON bodies."""

from __future__ import annotations

import json

import pytest

from gcattr import CapturedToolOutput, CaptureFailure, parse_stream

from .fixtures.streams import FIXTURES

FORMAT = {
    "openai_chat": "openai_chat",
    "openai_responses": "openai_responses",
    "anthropic": "anthropic_messages",
    "anthropic_truncated": "anthropic_messages",
    "gemini": "gemini_native",
}


def _chunks(data: bytes, size: int) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


def _tool_payloads(results: list[CapturedToolOutput | CaptureFailure]) -> list[object]:
    out: list[object] = []
    for r in results:
        if isinstance(r, CapturedToolOutput) and r.kind != "text_block" and r.complete:
            out.append(r.payload if r.kind == "json_args" else {"__freeform__": r.payload})
    return out


@pytest.mark.parametrize("name", ["openai_chat", "openai_responses", "anthropic", "gemini"])
@pytest.mark.parametrize("size", range(1, 14))
def test_complete_streams_reassemble_exactly(name: str, size: int) -> None:
    stream, truth = FIXTURES[name]()
    results = list(parse_stream(FORMAT[name], _chunks(stream.encode("utf-8"), size)))  # type: ignore[arg-type]
    assert not [r for r in results if isinstance(r, CaptureFailure)]
    assert _tool_payloads(results) == list(truth.values())


@pytest.mark.parametrize("size", [1, 7, 13])
def test_truncated_anthropic_reports_truncation_and_keeps_raw(size: int) -> None:
    stream, truth = FIXTURES["anthropic_truncated"]()
    results = list(parse_stream("anthropic_messages", _chunks(stream.encode("utf-8"), size)))
    failures = [r for r in results if isinstance(r, CaptureFailure)]
    assert [f.cause for f in failures] == ["truncated"]
    incomplete = [r for r in results if isinstance(r, CapturedToolOutput) and not r.complete]
    assert len(incomplete) == 1 and isinstance(incomplete[0].payload, str)
    assert _tool_payloads(results) == [v for v in truth.values() if v is not None]


def test_text_blocks_are_reported() -> None:
    stream, _ = FIXTURES["anthropic"]()
    texts = [
        r
        for r in parse_stream("anthropic_messages", [stream.encode()])
        if getattr(r, "kind", "") == "text_block"
    ]
    assert texts and texts[0].payload == "Writing the file."


@pytest.mark.parametrize(
    ("fmt", "data"),
    [
        ("openai_responses", b'data: {"no_type": true}\n\n'),
        ("openai_chat", b"data: not-json\n\n"),
        ("anthropic_messages", b'data: {"type":"content_block_delta","index":5,"delta":{}}\n\n'),
        ("gemini_native", b'data: {"weird": 1}\n\n'),
        ("openai_chat", b"[1, 2, 3]"),
        ("openai_chat", b'{"choices": "nope"}'),
    ],
)
def test_schema_deviant_input_yields_unexpected_format_and_never_raises(fmt: str, data: bytes) -> None:
    results = list(parse_stream(fmt, [data]))  # type: ignore[arg-type]
    assert any(isinstance(r, CaptureFailure) and r.cause == "unexpected_format" for r in results)


def test_unknown_format() -> None:
    assert next(iter(parse_stream("nope", [b""]))) == CaptureFailure(
        "unexpected_format", "unknown api format 'nope'"
    )  # type: ignore[arg-type]


def test_non_streamed_bodies() -> None:
    chat = {
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [
                        {
                            "id": "c1",
                            "function": {
                                "name": "write_file",
                                "arguments": json.dumps({"path": "a.py", "content": "x = 1\n"}),
                            },
                        }
                    ]
                },
            }
        ]
    }
    res = list(parse_stream("openai_chat", [json.dumps(chat).encode()]))
    assert _tool_payloads(res) == [{"path": "a.py", "content": "x = 1\n"}]
    msg = {
        "content": [
            {"type": "tool_use", "id": "t", "name": "Write", "input": {"file_path": "a", "content": "y"}}
        ],
        "stop_reason": "tool_use",
    }
    assert _tool_payloads(list(parse_stream("anthropic_messages", [json.dumps(msg).encode()]))) == [
        {"file_path": "a", "content": "y"}
    ]
    gem = [
        {"candidates": [{"content": {"parts": [{"functionCall": {"name": "w", "args": {"content": "z"}}}]}}]}
    ]
    assert _tool_payloads(list(parse_stream("gemini_native", [json.dumps(gem).encode()]))) == [
        {"content": "z"}
    ]


def test_chat_length_finish_marks_invalid_json_as_truncated() -> None:
    chunk = {
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {"index": 0, "id": "c", "function": {"name": "w", "arguments": '{"content": "abc'}}
                    ]
                },
                "finish_reason": "length",
            }
        ]
    }
    res = list(parse_stream("openai_chat", [f"data: {json.dumps(chunk)}\n\n".encode()]))
    assert [r.cause for r in res if isinstance(r, CaptureFailure)] == ["truncated"]
