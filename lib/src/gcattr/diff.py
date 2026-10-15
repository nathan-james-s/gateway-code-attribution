"""Added lines of a change, and exclusion globs (R11, FR-021). Shared by the PR check and `gca attribute`, so both
read a change the same way. Line text stays in memory; nothing here logs or stores it.

Exclusion glob syntax: `*` and `?` stay within one path segment, `**/` matches any number of leading directories,
and a trailing `/**` matches everything under a directory.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable

__all__ = ["DEFAULT_EXCLUSIONS", "ExclusionRules", "added_from_blobs", "added_from_patch", "glob_to_regex"]

# FR-021 defaults; also contracts/helm-values.md `attribution.exclusions` and the portal_settings column default.
DEFAULT_EXCLUSIONS = (
    "**/*.lock",
    "**/package-lock.json",
    "**/vendor/**",
    "**/node_modules/**",
    "**/*.min.*",
    "**/dist/**",
)

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


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("/**", i) and i + 3 == len(pattern):
            out.append("(?:/.*)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


class ExclusionRules:
    def __init__(self, patterns: Iterable[str]) -> None:
        self.patterns = tuple(patterns)
        self._regexes = [glob_to_regex(p) for p in self.patterns]

    def match(self, path: str) -> bool:
        return any(r.match(path) for r in self._regexes)
