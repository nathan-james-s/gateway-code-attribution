"""T021: summaries (FR-014, FR-028)."""

from __future__ import annotations

from gcattr import LineOutcome, summarize

U = LineOutcome("ai_unmodified", "exact", None, None, "e")
A = LineOutcome("ai_modified", "anchored", "high", 0.6, "e")
B = LineOutcome("ai_modified", "broad", "lower", 0.8, "e")
H = LineOutcome("human", "none", None, None, None)
I = LineOutcome("indeterminate", "none", None, None, None)  # noqa: E741
N = LineOutcome("not_observed", "none", None, None, None)


def test_percentages_exclude_indeterminate_and_not_observed() -> None:
    s = summarize([U, A, B, H, I, N])
    assert s["attributable"] == 4
    assert s["counts"]["not_observed"] == 1 and s["counts"]["indeterminate"] == 1
    assert s["percentages_with_broad"]["ai"] == 75.0
    assert s["percentages_without_broad"]["ai"] == 50.0
    assert s["percentages_without_broad"]["human"] == 50.0  # broad lines count as human without broad


def test_nothing_attributable_gives_null_not_zero() -> None:
    s = summarize([I, N])
    assert s["attributable"] == 0
    assert s["percentages_with_broad"]["ai"] is None
