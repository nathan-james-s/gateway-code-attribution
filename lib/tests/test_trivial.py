"""T014: trivial and common lines."""

from __future__ import annotations

import pytest

from gcattr.lexer import tokenize
from gcattr.trivial import is_trivial, token_key


def test_whitespace_insensitive_token_key() -> None:
    assert token_key(tokenize("a=b+c")) == token_key(tokenize("  a  =  b + c "))


@pytest.mark.parametrize(
    "line",
    [
        "}",
        "",
        "   ",
        "return x",
        ") ;",
        "} else {",
        "else{",
        "import os",
        "pass",
        "return;",
        'if __name__=="__main__":',
    ],
)
def test_trivial_lines(line: str) -> None:
    assert is_trivial(tokenize(line), 1)


@pytest.mark.parametrize("line", ["x = compute(a, b)", "total = sum(items)", "import os.path as p"])
def test_non_trivial_lines(line: str) -> None:
    assert not is_trivial(tokenize(line), 1)
