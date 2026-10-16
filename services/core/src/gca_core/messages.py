"""Capture messages (contracts/capture-event.schema.json). Fingerprints and metadata only (Constitution II).

``validate`` rejects any field that is not in the schema for the message kind, at every level, so content can
never ride along in a capture message.

A response whose fingerprints don't fit in one message (NATS refuses payloads over its ``max_payload``, 1 MiB by
default) is sent as several ``part`` messages of one event, sharing its ``event_id``; ``event_parts`` splits it.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import UTC, datetime
from functools import cache
from importlib import resources
from typing import Any

import jsonschema

from gcattr import LineFingerprint

__all__ = [
    "MessageError",
    "decode",
    "encode",
    "event_body",
    "event_parts",
    "failure_body",
    "heartbeat_body",
    "line_from_wire",
    "now_iso",
    "validate",
]

SCHEMA_ID = "gca.capture.v2"  # v2: the signature is packed binary; events may be sent in parts
_ENVELOPE = {"schema", "kind", "instance_id", "seq", "gateway_type", "sent_at"}
_ALLOWED = {
    "event": _ENVELOPE
    | {
        "credential_id",
        "api_format",
        "tool_hint",
        "session_id",
        "model",
        "received_at",
        "status",
        "failure_cause",
        "alg",
        "key_gen",
        "tool_call_count",
        "event_id",
        "part",
        "lines",
    },
    "heartbeat": _ENVELOPE | {"responses_seen", "buffer_depth", "shutting_down"},
    "failure": _ENVELOPE
    | {"cause", "count", "credential_id", "api_format", "tool_hint", "period_start", "period_end"},
}
_LINE_KEYS = {"t", "l", "x", "m", "b", "p"}


class MessageError(ValueError):
    pass


@cache
def _schema() -> dict[str, Any]:
    raw = resources.files("gca_core").joinpath("schemas/capture-event.schema.json").read_text("utf-8")
    loaded: dict[str, Any] = json.loads(raw)
    return loaded


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def line_to_wire(fp: LineFingerprint) -> dict[str, Any]:
    out: dict[str, Any] = {
        "t": fp.tool_call_ordinal,
        "l": fp.line_ordinal,
        "x": _b64(fp.exact_fp),
        "m": _b64(b"".join(v.to_bytes(4, "big") for v in fp.minhash)),
        "b": [_b64(b) for b in fp.lsh_bands],
    }
    if fp.path_suffix_fps:
        out["p"] = [_b64(p) for p in fp.path_suffix_fps]
    return out


# Decoded sizes of a line's binary fields. JSON Schema can't check what a base64 string holds, and the default
# decoder skips characters outside the alphabet, so a malformed field would decode to the wrong length and fail
# the database's checks at insert: ingest would retry the message forever. Strict decoding here makes it a
# contract violation instead, rejected (and so counted as loss) like any other.
EXACT_FP_BYTES = 16
SIGNATURE_BYTES = 128 * 4  # MinHash signature: 128 big-endian uint32 values
BAND_BYTES = 8
PATH_FP_BYTES = 16


def _strict(value: Any, size: int, field: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, TypeError, ValueError) as exc:
        raise MessageError(f"line field {field!r} is not valid base64") from exc
    if len(raw) != size:
        raise MessageError(f"line field {field!r} must decode to {size} bytes, not {len(raw)}")
    return raw


def _unpack_u32(raw: bytes) -> tuple[int, ...]:
    return tuple(int.from_bytes(raw[i : i + 4], "big") for i in range(0, len(raw), 4))


def line_from_wire(d: dict[str, Any]) -> dict[str, Any]:
    """Decode one line's fingerprints, strictly: raises ``MessageError`` for anything but exact sizes."""
    return {
        "tool_call_ordinal": int(d["t"]),
        "line_ordinal": int(d["l"]),
        "exact_fp": _strict(d["x"], EXACT_FP_BYTES, "x"),
        "minhash": _unpack_u32(_strict(d["m"], SIGNATURE_BYTES, "m")),
        "lsh_bands": tuple(_strict(b, BAND_BYTES, "b") for b in d["b"]),
        "path_suffix_fps": tuple(_strict(p, PATH_FP_BYTES, "p") for p in d.get("p", [])),
    }


def event_body(
    *,
    api_format: str,
    model: str,
    received_at: str,
    status: str,
    alg: int,
    key_gen: int,
    lines: list[LineFingerprint],
    tool_call_count: int,
    credential_id: str | None = None,
    tool_hint: str | None = None,
    session_id: str | None = None,
    failure_cause: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": "event",
        "event_id": event_id or str(uuid.uuid4()),
        "credential_id": credential_id,
        "api_format": api_format,
        "tool_hint": tool_hint,
        "session_id": session_id,
        "model": model[:128],
        "received_at": received_at,
        "status": status,
        "failure_cause": failure_cause,
        "alg": alg,
        "key_gen": key_gen,
        "tool_call_count": tool_call_count,
        "lines": [line_to_wire(f) for f in lines],
    }


def event_parts(body: dict[str, Any], max_bytes: int, envelope_bytes: int = 512) -> list[dict[str, Any]]:
    """``body`` as one message, or as parts of one event when its encoding would exceed ``max_bytes``. Each part
    carries the event's metadata, its ``event_id`` and ``part: {index, count}``, and a run of its lines."""
    lines: list[dict[str, Any]] = body["lines"]
    head = {k: v for k, v in body.items() if k != "lines"}
    fixed = len(json.dumps({**head, "part": {"index": 999, "count": 999}, "lines": []})) + envelope_bytes
    if fixed + sum(len(json.dumps(ln, separators=(",", ":"))) + 1 for ln in lines) <= max_bytes:
        return [body]
    runs: list[list[dict[str, Any]]] = [[]]
    size = fixed
    for ln in lines:
        n = len(json.dumps(ln, separators=(",", ":"))) + 1
        if runs[-1] and size + n > max_bytes:
            runs.append([])
            size = fixed
        runs[-1].append(ln)
        size += n
    return [{**head, "part": {"index": i, "count": len(runs)}, "lines": run} for i, run in enumerate(runs, 1)]


def heartbeat_body(*, responses_seen: int, buffer_depth: int, shutting_down: bool = False) -> dict[str, Any]:
    return {
        "kind": "heartbeat",
        "responses_seen": responses_seen,
        "buffer_depth": buffer_depth,
        "shutting_down": shutting_down,
    }


def failure_body(
    *,
    cause: str,
    count: int,
    period_start: str,
    period_end: str,
    credential_id: str | None = None,
    api_format: str | None = None,
    tool_hint: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": "failure",
        "cause": cause,
        "count": count,
        "credential_id": credential_id,
        "api_format": api_format,
        "tool_hint": tool_hint,
        "period_start": period_start,
        "period_end": period_end,
    }


def validate(msg: dict[str, Any]) -> dict[str, Any]:
    kind = msg.get("kind")
    if kind not in _ALLOWED:
        raise MessageError(f"unknown message kind {kind!r}")
    extra = set(msg) - _ALLOWED[kind]
    if extra:
        raise MessageError(f"fields not allowed in a {kind} message: {sorted(extra)}")
    if kind == "event":
        for line in msg.get("lines", []):
            if not isinstance(line, dict) or set(line) - _LINE_KEYS:
                raise MessageError("line items may only hold fingerprints (t, l, x, m, b, p)")
    try:
        jsonschema.validate(msg, _schema())
    except jsonschema.ValidationError as exc:
        raise MessageError(exc.message) from exc
    if kind == "event":
        for line in msg["lines"]:
            line_from_wire(line)  # every binary field decodes, strictly, to its exact size
    return msg


def encode(msg: dict[str, Any]) -> bytes:
    return json.dumps(validate(msg), separators=(",", ":")).encode("utf-8")


def decode(data: bytes) -> dict[str, Any]:
    try:
        msg = json.loads(data)
    except json.JSONDecodeError as exc:
        raise MessageError("message is not JSON") from exc
    if not isinstance(msg, dict):
        raise MessageError("message is not an object")
    return validate(msg)
