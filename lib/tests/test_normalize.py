"""T012: normalization."""

from __future__ import annotations

import unicodedata
from unittest import mock

import pytest

from gcattr import UnicodeVersionMismatch, UnsupportedAlg
from gcattr.normalize import normalize_line, split_lines


def test_split_lines_handles_crlf_cr_and_trailing_newline() -> None:
    assert split_lines("a\r\nb\rc\n") == ["a", "b", "c"]
    assert split_lines("") == []
    assert split_lines("\n") == [""]


def test_normalize_nfc_and_bom() -> None:
    decomposed = "café"
    assert normalize_line("﻿" + decomposed + "\r\n", 1) == unicodedata.normalize("NFC", decomposed)


def test_unicode_version_mismatch_is_raised() -> None:
    with mock.patch("gcattr.algorithm.unicodedata") as ud:
        ud.unidata_version = "99.0.0"
        with pytest.raises(UnicodeVersionMismatch):
            normalize_line("x", 1)


def test_unsupported_alg() -> None:
    with pytest.raises(UnsupportedAlg):
        normalize_line("x", 999)
