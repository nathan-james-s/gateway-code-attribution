"""Added lines of a change, in memory only (T053; research R11). Line text is never logged or stored."""

from __future__ import annotations

import difflib
import re

__all__ = ["MAX_ADDED_LINES", "MAX_BLOB_BYTES", "added_from_blobs", "added_from_patch"]

MAX_ADDED_LINES = 5_000  # per file; above this the file is excluded as too_large
MAX_BLOB_BYTES = 2 * 1024 * 1024

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def added_from_patch(patch: str) -> list[tuple[int, str]]:
    """(new line number, text) for every '+' line of a unified diff patch."""
    out: list[tuple[int, str]] = []
    new_no = 0
    for raw in patch.split("\n"):
        m = _HUNK.match(raw)
        if m:
            new_no = int(m.group(1))
        elif raw.startswith("+"):
            out.append((new_no, raw[1:]))
            new_no += 1
        elif raw.startswith(("-", "\\")):  # removed line, or "\ No newline at end of file"
            continue
        elif new_no:
            new_no += 1  # context line
    return out


def added_from_blobs(old: str | None, new: str) -> list[tuple[int, str]]:
    """Diff two file versions when the compare API omits the patch. ``old`` is None for added files."""
    b = new.splitlines()
    if old is None:
        return [(i + 1, t) for i, t in enumerate(b)]
    a = old.splitlines()
    out: list[tuple[int, str]] = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "insert"):
            out.extend((j + 1, b[j]) for j in range(j1, j2))
    return out
