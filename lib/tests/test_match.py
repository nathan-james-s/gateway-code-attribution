"""T020: tiered, author-scoped, multiset matching (FR-009-FR-015, R11)."""

from __future__ import annotations

from gcattr import AddedLine, CapturedToolOutput, attribute, extract

from .conftest import TEST_KEY, TEST_KEY_2, to_candidates

ALICE, BOB = 101, 202
L_EXACT = "subtotal = sum(i.price for i in items)"
L_ANCH_SRC = (
    "result = compute_total(order.items, discount=customer.discount, "
    "tax_rate=region.tax_rate, currency=order.currency)"
)
L_ANCH_PR = (  # ~0.72 similar to L_ANCH_SRC
    "result = compute_total(order.items, discount=customer.discount, "
    "tax_rate=region.tax_rate, currency=default_currency)"
)
L_BROAD_SRC = "for index, item in enumerate(items): totals[item.category] += item.price * item.quantity"
L_BROAD_PR = "for idx, item in enumerate(items): totals[item.category] += item.price * item.quantity"  # ~0.94


def _captured(lines: list[str], path: str | None = "/repo/src/app.py", event: str = "ev1", key=TEST_KEY):  # type: ignore[no-untyped-def]
    payload = {"content": "\n".join(lines) + "\n"}
    if path:
        payload["file_path"] = path
    out = CapturedToolOutput("anthropic_messages", "Write", "json_args", payload, True)
    return to_candidates(extract(out, key, 1), event)


def _line(text: str, n: int = 1, path: str = "src/app.py", author: int | None = ALICE) -> AddedLine:
    return AddedLine(path, n, text, author)


def test_exact_tier_and_multiset() -> None:
    cands = _captured([L_EXACT])
    res = attribute([_line(L_EXACT, 1), _line(L_EXACT, 2)], {ALICE: cands}, {1: TEST_KEY}, 1)
    assert [r.outcome for r in res] == ["ai_unmodified", "human"]  # captured once -> matches once (FR-013)
    assert res[0].tier == "exact" and res[0].matched_capture_event_id == "ev1"


def test_formatting_only_change_is_exact() -> None:
    cands = _captured([L_EXACT])
    res = attribute([_line("subtotal=sum( i.price  for i in items )")], {ALICE: cands}, {1: TEST_KEY}, 1)
    assert res[0].outcome == "ai_unmodified"


def test_anchored_requires_an_exact_match_in_the_same_file() -> None:
    cands = _captured([L_EXACT, L_ANCH_SRC])
    lines = [_line(L_EXACT, 1), _line(L_ANCH_PR, 2)]
    res = attribute(lines, {ALICE: cands}, {1: TEST_KEY}, 1)
    assert (res[1].outcome, res[1].tier, res[1].confidence) == ("ai_modified", "anchored", "high")
    assert 0.5 <= (res[1].similarity or 0) < 0.75


def test_path_match_without_exact_match_is_not_an_anchor() -> None:
    cands = _captured([L_ANCH_SRC])
    res = attribute([_line(L_ANCH_PR)], {ALICE: cands}, {1: TEST_KEY}, 1)
    assert res[0].outcome == "human"  # ~0.72 is below the broad threshold, and a path alone does not anchor


def test_no_cross_file_anchoring_when_capture_names_another_file() -> None:
    other = _captured([L_ANCH_SRC], path="/repo/lib/other.py", event="ev1")
    same = _captured([L_EXACT], path="/repo/src/app.py", event="ev1")
    res = attribute([_line(L_EXACT, 1), _line(L_ANCH_PR, 2)], {ALICE: same + other}, {1: TEST_KEY}, 1)
    assert res[1].outcome == "human"


def test_broad_tier() -> None:
    cands = _captured([L_BROAD_SRC], path=None)
    res = attribute([_line(L_BROAD_PR)], {ALICE: cands}, {1: TEST_KEY}, 1)
    assert (res[0].outcome, res[0].tier, res[0].confidence) == ("ai_modified", "broad", "lower")


def test_never_uses_another_authors_output() -> None:
    cands = _captured([L_EXACT])
    res = attribute([_line(L_EXACT, author=BOB)], {ALICE: cands, BOB: []}, {1: TEST_KEY}, 1)
    assert res[0].outcome == "human"


def test_not_observed_for_unmapped_or_null_author() -> None:
    res = attribute([_line(L_EXACT, author=None), _line(L_EXACT, author=999)], {ALICE: []}, {1: TEST_KEY}, 1)
    assert [r.outcome for r in res] == ["not_observed", "not_observed"]


def test_indeterminate_for_trivial_lines() -> None:
    cands = _captured(["}"])
    assert attribute([_line("}")], {ALICE: cands}, {1: TEST_KEY}, 1)[0].outcome == "indeterminate"


def test_ai_outcome_requires_a_candidate() -> None:
    res = attribute([_line(L_EXACT)], {ALICE: []}, {1: TEST_KEY}, 1)
    assert res[0].outcome == "human" and res[0].matched_capture_event_id is None


def test_key_rotation_matches_captures_under_the_retired_key() -> None:
    old = _captured([L_EXACT], key=TEST_KEY)  # captured under key_gen 1, before rotation to key_gen 2
    res = attribute([_line(L_EXACT)], {ALICE: old}, {1: TEST_KEY, 2: TEST_KEY_2}, 1)
    assert res[0].outcome == "ai_unmodified"


def test_expired_key_cannot_match() -> None:
    old = _captured([L_EXACT], key=TEST_KEY)
    res = attribute([_line(L_EXACT)], {ALICE: old}, {2: TEST_KEY_2}, 1)
    assert res[0].outcome == "human"
