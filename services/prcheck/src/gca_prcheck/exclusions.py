"""Exclusion rules (T072; FR-021): glob rules from PortalSettings.exclusion_rules, matched against changed paths.

Excluded files are never read or attributed; they're listed in `ChangeHead.excluded_paths` with reason `rule`.
Glob syntax: `*` and `?` stay within one path segment, `**/` matches any number of leading directories, and a
trailing `/**` matches everything under a directory.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Engine

__all__ = ["DEFAULT_RULES", "Rules", "glob_to_regex", "load_rules"]

# contracts/helm-values.md `attribution.exclusions`; also the portal_settings column default (migration 0001).
DEFAULT_RULES = (
    "**/*.lock",
    "**/package-lock.json",
    "**/vendor/**",
    "**/node_modules/**",
    "**/*.min.*",
    "**/dist/**",
)


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


class Rules:
    def __init__(self, patterns: Iterable[str]) -> None:
        self.patterns = tuple(patterns)
        self._regexes = [glob_to_regex(p) for p in self.patterns]

    def match(self, path: str) -> bool:
        return any(r.match(path) for r in self._regexes)


def load_rules(engine: Engine) -> Rules:
    with engine.connect() as conn:
        rules = conn.execute(text("SELECT exclusion_rules FROM portal_settings WHERE id = 1")).scalar()
    return Rules(DEFAULT_RULES if rules is None else rules)
