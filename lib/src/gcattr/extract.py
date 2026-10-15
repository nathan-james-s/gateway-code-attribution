"""Turn captured model output into keyed line fingerprints (research R7-R10). Content stays in memory."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

from .fingerprint import FingerprintKey, exact_fp, path_suffix_fps
from .lexer import tokenize
from .normalize import normalize_line, split_lines
from .similarity import lsh_bands, minhash
from .tool_fields import (
    CODE_FIELDS,
    EDIT_ITEM_CODE_FIELDS,
    EDIT_LIST_FIELDS,
    EXCLUDED_FIELDS,
    PATCH_BEGIN,
    PATH_FIELDS,
)
from .trivial import is_trivial
from .types import CapturedToolOutput, LineFingerprint

__all__ = ["code_units", "extract", "partial_string_fields"]

# (path or None, text, text_is_complete)
CodeUnit = tuple[str | None, str, bool]

_FENCE = re.compile(r"```[^\n`]*\n(.*?)(?:```|\Z)", re.DOTALL)


def partial_string_fields(raw: str) -> tuple[dict[str, str], str | None]:
    """Read top-level string fields from possibly truncated JSON.

    Returns ``(fields, cut_key)``. ``cut_key`` names the field whose string value was cut off (its partial
    value is included), or is ``None`` if every returned value was complete.
    """
    fields: dict[str, str] = {}
    dec = json.JSONDecoder()
    i = raw.find("{")
    if i < 0:
        return fields, None
    i += 1
    n = len(raw)
    while i < n:
        while i < n and raw[i] in " \t\r\n,":
            i += 1
        if i >= n or raw[i] == "}":
            break
        try:
            key, i = dec.raw_decode(raw, i)
        except json.JSONDecodeError:
            break
        while i < n and raw[i] in " \t\r\n:":
            i += 1
        if i >= n:
            break
        if raw[i] == '"':
            try:
                value, i = dec.raw_decode(raw, i)
            except json.JSONDecodeError:
                fields[str(key)] = _decode_partial_string(raw[i + 1 :])
                return fields, str(key)
            if isinstance(value, str):
                fields[str(key)] = value
        else:
            try:
                _, i = dec.raw_decode(raw, i)
            except json.JSONDecodeError:
                break
    return fields, None


def _decode_partial_string(body: str) -> str:
    """Decode the body of an unterminated JSON string, dropping an incomplete trailing escape."""
    for trim in range(0, 7):
        candidate = body[: len(body) - trim] if trim else body
        try:
            value = json.loads('"' + candidate + '"')
        except json.JSONDecodeError:
            continue
        return str(value)
    return ""


def _patch_units(patch: str) -> Iterator[CodeUnit]:
    """Only ``+`` lines of a ``*** Begin Patch`` patch are model output; paths come from headers."""
    path: str | None = None
    for line in split_lines(patch):
        for prefix in ("*** Update File:", "*** Add File:"):
            if line.startswith(prefix):
                path = line[len(prefix) :].strip()
        if line.startswith("+++ "):
            target = line[4:].strip()
            path = target[2:] if target.startswith("b/") else target
            continue
        if line.startswith("+") and not line.startswith("+++"):
            yield (path, line[1:], True)


def _string_units(path: str | None, text: str, complete: bool) -> Iterator[CodeUnit]:
    if text.lstrip().startswith(PATCH_BEGIN):
        yield from _patch_units(text)
    else:
        yield (path, text, complete)


def code_units(output: CapturedToolOutput) -> list[CodeUnit]:
    """The code-bearing texts of one output, each with its file path (when known) and completeness."""
    units: list[CodeUnit] = []
    if output.kind == "text_block":
        text = output.payload if isinstance(output.payload, str) else ""
        for block in _FENCE.findall(text):
            units.append((None, block, True))
        return units
    if output.kind == "freeform":
        text = output.payload if isinstance(output.payload, str) else ""
        units.extend(_string_units(None, text, output.complete))
        return units
    # json_args
    if isinstance(output.payload, dict):
        args: dict[str, object] = output.payload
        cut_key: str | None = None
    else:
        fields, cut_key = partial_string_fields(output.payload)
        args = dict(fields)
    path = next((v for k in PATH_FIELDS if isinstance(v := args.get(k), str) and v), None)
    for key, value in args.items():
        if key in EDIT_LIST_FIELDS and isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    for f in EDIT_ITEM_CODE_FIELDS:
                        if isinstance(item.get(f), str):
                            units.extend(_string_units(path, item[f], True))
            continue
        if not isinstance(value, str) or key in EXCLUDED_FIELDS:
            continue
        complete = key != cut_key
        unit_path = path if key in CODE_FIELDS else None
        units.extend(_string_units(unit_path, value, complete))
    return units


def extract(
    output: CapturedToolOutput, key: FingerprintKey, alg: int, tool_call_ordinal: int = 0
) -> list[LineFingerprint]:
    """Normalize, tokenize, drop trivial lines, and fingerprint every code line of ``output``.

    For a cut-off value, complete lines before the cut are kept; the incomplete remainder is dropped.
    """
    out: list[LineFingerprint] = []
    ordinal = 0
    for path, text, complete in code_units(output):
        lines = split_lines(text)
        if not complete and lines and not text.endswith(("\n", "\r")):
            lines = lines[:-1]
        path_fps = path_suffix_fps(path, key, alg)
        for raw_line in lines:
            ordinal += 1
            tokens = tokenize(normalize_line(raw_line, alg))
            if is_trivial(tokens, alg):
                continue
            sig = minhash(tokens, key, alg)
            out.append(
                LineFingerprint(
                    exact_fp=exact_fp(tokens, key, alg),
                    minhash=sig,
                    lsh_bands=lsh_bands(sig, key, alg),
                    path_suffix_fps=path_fps,
                    tool_call_ordinal=tool_call_ordinal,
                    line_ordinal=ordinal,
                    alg=alg,
                    key_gen=key.key_gen,
                )
            )
    return out
