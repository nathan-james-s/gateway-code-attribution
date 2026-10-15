"""Language-agnostic tokenizer (research R8). Whitespace is dropped; everything else becomes a token."""

from __future__ import annotations

import re
from typing import Literal, NamedTuple

__all__ = ["Token", "tokenize"]

TokenKind = Literal["ident", "number", "string", "punct"]


class Token(NamedTuple):
    kind: TokenKind
    text: str


_NUMBER = re.compile(
    r"0[xX][0-9a-fA-F_]+"
    r"|0[oO][0-7_]+"
    r"|0[bB][01_]+"
    r"|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?"
    r"|\.\d[\d_]*(?:[eE][+-]?\d+)?"
)
# Identifier: a letter (any script) or underscore, then word characters.
_IDENT = re.compile(r"[^\W\d]\w*")
_QUOTES = "'\"`"


def _scan_string(line: str, start: int) -> int:
    """Return the index just past the string literal at ``start`` (end of line if unterminated)."""
    quote = line[start]
    i = start + 1
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\":
            i += 2
            continue
        if ch == quote:
            return i + 1
        i += 1
    return n


def tokenize(line: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch.isspace():
            i += 1
            continue
        if ch in _QUOTES:
            end = _scan_string(line, i)
            tokens.append(Token("string", line[i:end]))
            i = end
            continue
        m = _NUMBER.match(line, i)
        if m and m.end() > i:
            tokens.append(Token("number", m.group(0)))
            i = m.end()
            continue
        m = _IDENT.match(line, i)
        if m:
            tokens.append(Token("ident", m.group(0)))
            i = m.end()
            continue
        tokens.append(Token("punct", ch))
        i += 1
    return tokens
