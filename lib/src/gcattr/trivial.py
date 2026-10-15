"""Trivial and common lines are ``indeterminate`` (research R10, FR-011, FR-014)."""

from __future__ import annotations

from functools import cache
from importlib import resources

from .algorithm import params_for
from .lexer import Token, tokenize

__all__ = ["common_lines", "is_trivial", "token_key"]

_MIN_TOKENS = 3
_CONTENT_KINDS = frozenset({"ident", "number", "string"})


def token_key(tokens: list[Token]) -> str:
    """Canonical whitespace-free form of a token list: token texts joined by a single space."""
    return " ".join(t.text for t in tokens)


@cache
def common_lines(version: str) -> frozenset[str]:
    raw = resources.files("gcattr").joinpath(f"data/common_lines_v{version}.txt").read_text("utf-8")
    keys = set()
    for line in raw.splitlines():
        if not line.strip() or (line.startswith("# ") or line == "#"):
            continue
        keys.add(token_key(tokenize(line)))
    return frozenset(keys)


def is_trivial(tokens: list[Token], alg: int) -> bool:
    if len(tokens) < _MIN_TOKENS:
        return True
    if not any(t.kind in _CONTENT_KINDS for t in tokens):
        return True
    return token_key(tokens) in common_lines(params_for(alg).common_lines_version)
