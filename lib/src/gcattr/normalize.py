"""Text normalization (research R8)."""

from __future__ import annotations

import unicodedata

from .algorithm import params_for

__all__ = ["normalize_line", "split_lines"]

_BOM = "\ufeff"


def split_lines(text: str) -> list[str]:
    """Split into lines after mapping ``\\r\\n`` and ``\\r`` to ``\\n``; a trailing newline adds no line."""
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    if not unified:
        return []
    if unified.endswith("\n"):
        unified = unified[:-1]
    return unified.split("\n")


def normalize_line(text: str, alg: int) -> str:
    """Normalize a line for ``alg``: check the Unicode pin, drop a BOM, apply NFC, drop line ends."""
    params_for(alg)  # raises UnicodeVersionMismatch / UnsupportedAlg
    if text.startswith(_BOM):
        text = text[1:]
    text = text.replace("\r\n", "").replace("\r", "").replace("\n", "")
    return unicodedata.normalize("NFC", text)
