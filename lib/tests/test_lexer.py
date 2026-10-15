"""T013: language-agnostic lexer."""

from __future__ import annotations

from gcattr.lexer import tokenize


def test_lexer_kinds_and_whitespace_dropped() -> None:
    toks = tokenize("  total = round(x * 1.5e3, 0x1F)  # 'note'")
    assert [t.kind for t in toks] == [
        "ident",
        "punct",
        "ident",
        "punct",
        "ident",
        "punct",
        "number",
        "punct",
        "number",
        "punct",
        "punct",
        "string",
    ]
    assert toks[-1].text == "'note'"


def test_lexer_strings_keep_quotes_and_escapes() -> None:
    toks = tokenize(r'print("a\"b", `t`)')
    assert [t.text for t in toks] == ["print", "(", r'"a\"b"', ",", "`t`", ")"]


def test_lexer_unterminated_string_runs_to_end() -> None:
    assert tokenize('x = "abc')[-1].text == '"abc'


def test_lexer_unicode_identifiers() -> None:
    assert tokenize("émoji = 1")[0].text == "émoji"
