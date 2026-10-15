"""Capture message contract: fingerprints only (Constitution II)."""

from __future__ import annotations

import pytest

from gca_core import messages
from gcattr import CapturedToolOutput, FingerprintKey, extract

KEY = FingerprintKey(1, b"\x42" * 32)
ENV = {
    "schema": "gca.capture.v1",
    "instance_id": "8f1c1b0e-6a4c-4b31-9d1f-3a0f8a2a1c11",
    "seq": 0,
    "gateway_type": "litellm",
    "sent_at": "2026-10-14T00:00:00+00:00",
}


def _lines():  # type: ignore[no-untyped-def]
    out = CapturedToolOutput(
        "openai_chat", "w", "json_args", {"path": "a/b.py", "content": "x = compute(a, b)\n"}, True
    )
    return extract(out, KEY, 1)


def test_event_roundtrip() -> None:
    body = messages.event_body(
        api_format="openai_chat",
        model="m",
        received_at=messages.now_iso(),
        status="captured",
        alg=1,
        key_gen=1,
        lines=_lines(),
        tool_call_count=1,
    )
    msg = messages.decode(messages.encode({**ENV, **body}))
    wire = messages.line_from_wire(msg["lines"][0])
    assert wire["exact_fp"] == _lines()[0].exact_fp and wire["minhash"] == _lines()[0].minhash


def test_rejects_extra_top_level_field() -> None:
    body = messages.heartbeat_body(responses_seen=1, buffer_depth=0)
    with pytest.raises(messages.MessageError, match="not allowed"):
        messages.encode({**ENV, **body, "content": "def secret(): pass"})


def test_rejects_content_inside_line_items() -> None:
    body = messages.event_body(
        api_format="openai_chat",
        model="m",
        received_at=messages.now_iso(),
        status="captured",
        alg=1,
        key_gen=1,
        lines=_lines(),
        tool_call_count=1,
    )
    body["lines"][0]["text"] = "x = compute(a, b)"
    with pytest.raises(messages.MessageError, match="fingerprints"):
        messages.encode({**ENV, **body})


def test_schema_types_enforced() -> None:
    body = messages.failure_body(
        cause="not_a_cause", count=1, period_start=messages.now_iso(), period_end=messages.now_iso()
    )
    with pytest.raises(messages.MessageError):
        messages.encode({**ENV, **body})
