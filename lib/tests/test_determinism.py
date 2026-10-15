"""T024: determinism properties (Constitution III, FR-033)."""

from __future__ import annotations

import random

from hypothesis import given, settings
from hypothesis import strategies as st

from gcattr import AddedLine, CapturedToolOutput, attribute, extract, parse_stream

from .conftest import TEST_KEY, to_candidates
from .fixtures.streams import FIXTURES

code_line = st.text(
    alphabet=st.characters(categories=("Ll", "Lu", "Nd"), include_characters=" _=+-*/()[]{}.,:'\"#"),
    min_size=0,
    max_size=60,
)


@settings(max_examples=150, deadline=None)
@given(st.lists(code_line, min_size=1, max_size=12))
def test_extract_is_pure(lines: list[str]) -> None:
    out = CapturedToolOutput(
        "openai_chat", "w", "json_args", {"path": "a/b.py", "content": "\n".join(lines)}, True
    )
    assert extract(out, TEST_KEY, 1) == extract(out, TEST_KEY, 1)


@settings(max_examples=100, deadline=None)
@given(st.lists(code_line, min_size=1, max_size=10), st.integers(min_value=0, max_value=2**31))
def test_attribute_is_pure_and_order_independent_for_candidates(lines: list[str], seed: int) -> None:
    out = CapturedToolOutput(
        "openai_chat", "w", "json_args", {"path": "a/b.py", "content": "\n".join(lines)}, True
    )
    cands = to_candidates(extract(out, TEST_KEY, 1))
    added = [AddedLine("a/b.py", i, t, 7) for i, t in enumerate(lines, 1)]
    first = attribute(added, {7: cands}, {1: TEST_KEY}, 1)
    shuffled = list(cands)
    random.Random(seed).shuffle(shuffled)
    assert attribute(added, {7: shuffled}, {1: TEST_KEY}, 1) == first


@settings(max_examples=60, deadline=None)
@given(st.sampled_from(["openai_chat", "openai_responses", "anthropic", "gemini"]), st.integers(1, 64))
def test_fingerprints_do_not_depend_on_chunk_boundaries(name: str, size: int) -> None:
    fmt = {"anthropic": "anthropic_messages", "gemini": "gemini_native"}.get(name, name)
    data = FIXTURES[name]()[0].encode("utf-8")

    def fps(chunks: list[bytes]) -> list[object]:
        res = []
        for i, o in enumerate(r for r in parse_stream(fmt, chunks) if isinstance(r, CapturedToolOutput)):  # type: ignore[arg-type]
            res.extend(extract(o, TEST_KEY, 1, tool_call_ordinal=i))
        return res

    assert fps([data[i : i + size] for i in range(0, len(data), size)]) == fps([data])
