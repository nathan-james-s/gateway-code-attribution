"""LiteLLM 1.105.1 callback objects (real shapes, synthetic content): every format yields its lines; redacted
responses are reported as loss, never fingerprinted."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from gcattr import ALG, CapturedToolOutput, CaptureFailure, FingerprintKey, extract, from_litellm

FIX = Path(__file__).parent / "fixtures" / "litellm_1_105"
KEY = FingerprintKey(1, b"\x11" * 32)
FORMATS = {
    "acompletion": ("openai_chat", 15),
    "aresponses": ("openai_responses", 7),
    "anthropic_messages": ("anthropic_messages", 12),
    "agenerate_content_stream": ("gemini_native", 12),
}


@pytest.mark.parametrize("call_type", sorted(FORMATS))
def test_lines_per_format(call_type: str) -> None:
    fmt, expected = FORMATS[call_type]
    obj = json.loads((FIX / f"{call_type}.json").read_text())["response_obj"]
    outs = list(from_litellm(obj, call_type, fmt))  # type: ignore[arg-type]
    assert not [o for o in outs if isinstance(o, CaptureFailure)]
    code = [o for o in outs if isinstance(o, CapturedToolOutput) and o.kind != "text_block"]
    assert all(o.api_format == fmt for o in code)
    assert sum(len(extract(o, KEY, ALG)) for o in code) == expected


def test_redacted_response_is_loss() -> None:
    obj = json.loads((FIX / "acompletion.json").read_text())["response_obj"]
    red = copy.deepcopy(obj)
    for ch in red["choices"]:
        for tc in ch["message"]["tool_calls"]:
            tc["function"]["arguments"] = "redacted-by-litellm"
    outs = list(from_litellm(red, "acompletion", "openai_chat"))
    assert [type(o).__name__ for o in outs] == ["CaptureFailure"]
