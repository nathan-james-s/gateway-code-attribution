"""T015: keyed exact and path-suffix fingerprints."""

from __future__ import annotations

import pytest

from gcattr import FingerprintKey
from gcattr.fingerprint import exact_fp, path_suffix_fps
from gcattr.lexer import tokenize

from .conftest import TEST_KEY, TEST_KEY_2


def test_exact_fp_is_16_bytes_keyed_and_formatting_insensitive() -> None:
    a = exact_fp(tokenize("x = compute(a, b)"), TEST_KEY, 1)
    assert len(a) == 16
    assert a == exact_fp(tokenize("x=compute( a,b )"), TEST_KEY, 1)
    assert a != exact_fp(tokenize("x = compute(a, b)"), TEST_KEY_2, 1)
    assert a != exact_fp(tokenize("x = compute(a, c)"), TEST_KEY, 1)


def test_key_validation_and_redacted_repr() -> None:
    with pytest.raises(ValueError):
        FingerprintKey(1, b"short").check()
    assert "redacted" in repr(TEST_KEY)
    assert "\\x42" not in repr(TEST_KEY)


def test_path_suffix_fps() -> None:
    capture = path_suffix_fps("/repo/src/app.py", TEST_KEY, 1)
    pr = path_suffix_fps("src/app.py", TEST_KEY, 1)
    assert len(capture) == 3 and len(pr) == 2
    assert set(pr) <= set(capture)  # "app.py" and "src/app.py" match
    assert path_suffix_fps("C:\\repo\\src\\app.py", TEST_KEY, 1)[:2] == capture[:2]
    assert path_suffix_fps(None, TEST_KEY, 1) == ()
    assert not set(path_suffix_fps("lib/other.py", TEST_KEY, 1)) & set(capture)
