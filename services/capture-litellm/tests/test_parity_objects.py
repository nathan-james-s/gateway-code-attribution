"""Fingerprint parity (FR-006, R4): what LiteLLM 1.105.1 hands the callback fingerprints identically to what
agentgateway's ext_proc computes from the raw demo-model stream for the same session step."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gca_capture_litellm.handler import _CALL_FORMATS
from gca_core.messages import line_to_wire
from gca_demo import model
from gca_demo.sessions import marker
from gcattr import ALG, CapturedToolOutput, FingerprintKey, extract, from_litellm, parse_stream

FIX = Path(__file__).resolve().parents[3] / "lib/tests/fixtures/litellm_1_105"
KEY = FingerprintKey(1, b"\x11" * 32)
STEP = {
    "acompletion": ("inventory", "/v1/chat/completions"),
    "aresponses": ("discount-ts", "/v1/responses"),
    "anthropic_messages": ("pricing", "/v1/messages"),
    "agenerate_content_stream": ("receipt", "/v1beta/models/demo-gemini:streamGenerateContent"),
}


def _fps(outs: object) -> list[str]:
    res: list[str] = []
    n = 0
    for o in outs:  # type: ignore[attr-defined]
        if isinstance(o, CapturedToolOutput) and o.kind != "text_block":
            n += 1
            res += [
                json.dumps(line_to_wire(fp), sort_keys=True)
                for fp in extract(o, KEY, ALG, tool_call_ordinal=n)
            ]
    return sorted(res)


@pytest.mark.parametrize("call_type", sorted(STEP))
def test_same_multiset_as_raw_stream(call_type: str) -> None:
    fmt = _CALL_FORMATS[call_type]
    session, path = STEP[call_type]
    body = json.dumps({"stream": True, "messages": [{"role": "user", "content": marker(session, 0)}]})
    raw = model.respond(fmt, path, body)[1]
    obj = json.loads((FIX / f"{call_type}.json").read_text())["response_obj"]
    via_agentgateway = _fps(parse_stream(fmt, [raw]))  # type: ignore[arg-type]
    via_litellm = _fps(from_litellm(obj, call_type, fmt))  # type: ignore[arg-type]
    assert via_agentgateway and via_agentgateway == via_litellm
