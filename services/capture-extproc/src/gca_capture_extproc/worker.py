"""Parse and fingerprint one finished response in a worker *process* (docs/validation/R2-extproc.md).

Runs outside the echo loop's process, so CPU-heavy hashing never holds the GIL against echoing. Content stays in
this process's memory for the duration of the call only.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from gca_core.keys import KeyRing
from gcattr import ALG, CapturedToolOutput, CaptureFailure, extract, parse_stream

_ring: KeyRing | None = None
# Fault injection for the end-to-end test (T093d): a slow parser must never slow the developer's response.
PARSE_DELAY_SECONDS = float(os.environ.get("GCA_CAPTURE_TEST_PARSE_DELAY_SECONDS", "0"))
_MODEL = re.compile(rb'"(?:model|modelVersion)"\s*:\s*"([^"]{1,128})"')


def init(keys_dir: str) -> None:
    global _ring
    _ring = KeyRing(keys_dir)


def ping() -> bool:
    """Warm-up call: makes the pool start its processes before the gRPC server takes traffic."""
    return _ring is not None


def model_from_stream(data: bytes) -> str | None:
    """The first model name in the response (llm.requestModel is not available at the ext_proc stage)."""
    m = _MODEL.search(data[:65536])
    return m.group(1).decode("utf-8", "replace") if m else None


def fingerprint(api_format: str, data: bytes) -> dict[str, Any]:
    """Return fingerprints (no content) for one response: lines, failures, counts, model."""
    assert _ring is not None, "worker not initialised"
    if PARSE_DELAY_SECONDS:
        time.sleep(PARSE_DELAY_SECONDS)
    _ring.reload()
    key = _ring.active
    lines = []
    failures: list[str] = []
    tool_calls = 0
    for result in parse_stream(api_format, [data]):  # type: ignore[arg-type]
        if isinstance(result, CaptureFailure):
            failures.append(result.cause)
            continue
        assert isinstance(result, CapturedToolOutput)
        if result.kind != "text_block":
            tool_calls += 1
        lines.extend(extract(result, key, ALG, tool_call_ordinal=tool_calls))
    return {
        "lines": lines,
        "failures": failures,
        "tool_call_count": tool_calls,
        "model": model_from_stream(data) or "unknown",
        "alg": ALG,
        "key_gen": key.key_gen,
    }


def _debug_summary(result: dict[str, Any]) -> str:  # never includes content
    return json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in result.items()})
