"""Shared helpers for stream parsers."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from ..types import ApiFormat, CapturedToolOutput, CaptureFailure, FailureCause

Result = CapturedToolOutput | CaptureFailure


def decode_args(raw: str, *, truncated_hint: bool) -> tuple[dict[str, object] | None, FailureCause | None]:
    """Parse tool-call JSON arguments. Returns (args, None) on success, else (None, cause)."""
    if not raw.strip():
        return {}, None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        at_end = exc.pos >= len(raw.rstrip()) - 1 or exc.msg.startswith("Unterminated")
        return None, ("truncated" if (truncated_hint or at_end) else "unparsable")
    if not isinstance(value, dict):
        return None, "unexpected_format"
    return value, None


def emit_json_call(
    api_format: ApiFormat,
    name: str | None,
    raw: str,
    call_id: str | None,
    *,
    truncated_hint: bool,
) -> Iterator[Result]:
    args, cause = decode_args(raw, truncated_hint=truncated_hint)
    if cause is None and args is not None:
        yield CapturedToolOutput(api_format, name, "json_args", args, True, call_id)
        return
    yield CaptureFailure(cause or "unparsable", f"tool call {name!r}")
    # Hand the raw text on so extract() can keep complete lines before the cut-off (T019).
    yield CapturedToolOutput(api_format, name, "json_args", raw, False, call_id)


def emit_text(api_format: ApiFormat, text: str) -> Iterator[Result]:
    if text.strip():
        yield CapturedToolOutput(api_format, None, "text_block", text, True, None)


def load_json(data: str) -> dict[str, Any] | None:
    try:
        value = json.loads(data)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
