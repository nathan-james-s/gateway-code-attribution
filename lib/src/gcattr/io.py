"""Fingerprinting a whole response, and the JSON forms the CLI reads and writes (contracts/library-api.md).

JSON never carries content: fingerprints, ordinals and ids only. Bytes are base64 (standard alphabet).
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any, NamedTuple

from .algorithm import ALG
from .extract import extract
from .fingerprint import FingerprintKey
from .types import Candidate, CapturedToolOutput, CaptureFailure, LineFingerprint

__all__ = [
    "FingerprintResult",
    "KeyFileError",
    "candidate_from_json",
    "candidate_to_json",
    "fingerprint_outputs",
    "fingerprint_to_json",
    "load_keys",
    "read_candidates",
]


class FingerprintResult(NamedTuple):
    lines: list[LineFingerprint]
    failures: list[str]  # causes, one per CaptureFailure
    tool_call_count: int


def fingerprint_outputs(
    results: Iterable[CapturedToolOutput | CaptureFailure], key: FingerprintKey, alg: int = ALG
) -> FingerprintResult:
    """Fingerprint everything a parser or adapter yielded for one response. Tool calls are numbered from 1 in
    order; code in assistant text shares the ordinal of the tool call before it (0 before any)."""
    lines: list[LineFingerprint] = []
    failures: list[str] = []
    tool_calls = 0
    for result in results:
        if isinstance(result, CaptureFailure):
            failures.append(result.cause)
            continue
        if result.kind != "text_block":
            tool_calls += 1
        lines.extend(extract(result, key, alg, tool_call_ordinal=tool_calls))
    return FingerprintResult(lines, failures, tool_calls)


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s, validate=True)


def fingerprint_to_json(fp: LineFingerprint) -> dict[str, Any]:
    return {
        "alg": fp.alg,
        "key_gen": fp.key_gen,
        "tool_call_ordinal": fp.tool_call_ordinal,
        "line_ordinal": fp.line_ordinal,
        "exact_fp": _b64(fp.exact_fp),
        "minhash": list(fp.minhash),
        "lsh_bands": [_b64(b) for b in fp.lsh_bands],
        "path_suffix_fps": [_b64(p) for p in fp.path_suffix_fps],
    }


def candidate_to_json(c: Candidate, github_id: int) -> dict[str, Any]:
    """One line of a captures file: a captured line credited to ``github_id``'s gateway credential."""
    return {
        "github_id": github_id,
        "capture_event_id": c.capture_event_id,
        "alg": c.alg,
        "key_gen": c.key_gen,
        "tool_call_ordinal": c.tool_call_ordinal,
        "line_ordinal": c.line_ordinal,
        "exact_fp": _b64(c.exact_fp),
        "minhash": list(c.minhash),
        "lsh_bands": [_b64(b) for b in c.lsh_bands],
        "path_suffix_fps": [_b64(p) for p in c.path_suffix_fps],
    }


def candidate_from_json(d: Mapping[str, Any]) -> tuple[int, Candidate]:
    return int(d["github_id"]), Candidate(
        str(d["capture_event_id"]),
        _unb64(d["exact_fp"]),
        tuple(int(x) for x in d["minhash"]),
        tuple(_unb64(p) for p in d.get("path_suffix_fps", [])),
        int(d["tool_call_ordinal"]),
        int(d["line_ordinal"]),
        int(d["alg"]),
        int(d["key_gen"]),
        tuple(_unb64(b) for b in d.get("lsh_bands", [])),
    )


def read_candidates(lines: Iterable[str]) -> dict[int, list[Candidate]]:
    """A captures file (JSON lines) -> candidates per GitHub account id."""
    out: dict[int, list[Candidate]] = {}
    for n, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            gid, cand = candidate_from_json(json.loads(raw))
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise ValueError(f"captures line {n}: {exc}") from None
        out.setdefault(gid, []).append(cand)
    return out


class KeyFileError(ValueError):
    pass


def _read_key(path: Path, key_gen: int) -> FingerprintKey:
    try:
        secret = base64.b64decode(path.read_text().strip(), validate=True)
    except (binascii.Error, ValueError, OSError) as exc:
        raise KeyFileError(f"{path}: not a base64 key ({type(exc).__name__})") from None
    try:
        return FingerprintKey(key_gen, secret).check()
    except ValueError as exc:
        raise KeyFileError(f"{path}: {exc}") from None


def load_keys(path: str | Path, key_gen: int = 1) -> tuple[dict[int, FingerprintKey], int]:
    """``(keys by generation, active generation)`` from a key file (base64, generation ``key_gen``) or from a
    directory in the stack's Secret layout (files named by generation, plus ``active``)."""
    p = Path(path)
    if not p.is_dir():
        key = _read_key(p, key_gen)
        return {key_gen: key}, key_gen
    keys = {int(e.name): _read_key(e, int(e.name)) for e in p.iterdir() if e.name.isdigit() and e.is_file()}
    active_file = p / "active"
    active = int(active_file.read_text().strip()) if active_file.is_file() else max(keys, default=key_gen)
    if active not in keys:
        raise KeyFileError(f"{p}: no key for active generation {active}")
    return keys, active


def iter_jsonl(rows: Iterable[Mapping[str, Any]]) -> Iterator[str]:
    for r in rows:
        yield json.dumps(r, sort_keys=True, separators=(",", ":"))
