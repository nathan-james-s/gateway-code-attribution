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
L_ANCH_PR = (  # ~0.66 similar to L_ANCH_SRC: above the anchored threshold, below the broad one
    "result = compute_total(order.items, discount=customer.discount, "
    "tax=region.tax_rate, currency=default_currency)"
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
    assert res[0].outcome == "human"  # ~0.66 is below the broad threshold, and a path alone does not anchor
    assert res[0].tier != "anchored"


def test_no_cross_file_anchoring_when_capture_names_another_file() -> None:
    other = _captured([L_ANCH_SRC], path="/repo/lib/other.py", event="ev1")
    same = _captured([L_EXACT], path="/repo/src/app.py", event="ev1")
    res = attribute([_line(L_EXACT, 1), _line(L_ANCH_PR, 2)], {ALICE: same + other}, {1: TEST_KEY}, 1)
    assert res[1].outcome == "human" and res[1].tier != "anchored"


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


# ------------------------------------------------------------------------------------- formatter splits (T109)
L_RAISE_SRC = "if missing: raise KeyError('missing config keys: ' + ', '.join(missing))"
L_CHAIN_SRC = "return plugins.filter(p => p.enabled).sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0))"


def test_wrapped_one_ai_line_over_several_is_ai_modified() -> None:
    cands = _captured([L_ANCH_SRC], path=None)
    wrapped = [
        "result = compute_total(",
        "    order.items,",
        "    discount=customer.discount,",
        "    tax_rate=region.tax_rate,",
        "    currency=order.currency,",
        ")",
    ]
    res = attribute([_line(t, n) for n, t in enumerate(wrapped, 1)], {ALICE: cands}, {1: TEST_KEY}, 1)
    assert [r.outcome for r in res] == ["ai_modified"] * 5 + ["indeterminate"]
    assert {r.matched_capture_event_id for r in res[:5]} == {"ev1"}


def test_split_fragment_joins_the_part_that_matched() -> None:
    cands = _captured([L_EXACT, L_RAISE_SRC])
    lines = [
        _line(L_EXACT, 1),
        _line("if missing:", 2),
        _line('    raise KeyError("missing config keys: " + ", ".join(missing))', 3),
    ]
    res = attribute(lines, {ALICE: cands}, {1: TEST_KEY}, 1)
    assert [r.outcome for r in res] == ["ai_unmodified", "ai_modified", "ai_modified"]
    assert res[1].tier == res[2].tier == "anchored"


def test_split_fragment_of_a_method_chain() -> None:
    cands = _captured([L_EXACT, L_CHAIN_SRC], path="/repo/src/plugins.ts")
    chain = [
        L_EXACT,
        "return plugins",
        "    .filter((p) => p.enabled)",
        "    .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0));",
    ]
    lines = [_line(t, n, "src/plugins.ts") for n, t in enumerate(chain, 1)]
    res = attribute(lines, {ALICE: cands}, {1: TEST_KEY}, 1)
    assert res[3].outcome == "ai_modified"  # the main part matches on its own
    assert res[2].outcome == "ai_modified" and res[2].matched_capture_event_id == "ev1"


def test_an_unrelated_line_next_to_a_match_stays_human() -> None:
    cands = _captured([L_EXACT, L_RAISE_SRC])
    lines = [
        _line(L_EXACT, 1),
        _line('log.warning("config incomplete for %s", path)', 2),
        _line('    raise KeyError("missing config keys: " + ", ".join(missing))', 3),
        _line("notify_admins(settings.ADMIN_EMAILS)", 4),
    ]
    res = attribute(lines, {ALICE: cands}, {1: TEST_KEY}, 1)
    assert [r.outcome for r in res] == ["ai_unmodified", "human", "ai_modified", "human"]


# ------------------------------------------------------------------------------------- candidate lookup
POOL = [
    "subtotal = sum(i.price * i.qty for i in items)",
    "tax = round(subtotal * region.tax_rate, 2)",
    "result = compute_total(order.items, discount=customer.discount, tax_rate=region.tax_rate)",
    "if missing: raise KeyError('missing config keys: ' + ', '.join(missing))",
    "return plugins.filter(p => p.enabled).sort((a, b) => b.priority - a.priority)",
    "logger.info('processed %d orders for %s', len(orders), customer.name)",
    "response = client.post(url, json=payload, headers=headers, timeout=30)",
    "for index, item in enumerate(items): totals[item.category] += item.price",
    "user = session.query(User).filter(User.email == email).one_or_none()",
    "cache.set(key, value, ttl=settings.CACHE_TTL_SECONDS)",
    "names = [p.name for p in plugins if p.enabled]",
    "with open(path, encoding='utf-8') as fh: data = json.load(fh)",
]
UNRELATED = [  # other work in the matching window that the PR doesn't touch
    "schedule.every(10).minutes.do(refresh_exchange_rates)",
    "parser.add_argument('--dry-run', action='store_true', help='print the plan only')",
    "df = pd.read_csv(source, parse_dates=['created_at'], dtype={'sku': str})",
    "router.get('/healthz', (req, res) => res.json({ status: 'ok' }))",
]
HUMAN_POOL = [
    "metrics.increment('checkout.completed', tags=[f'region:{region.code}'])",
    "assert invoice.total_cents >= 0, invoice.id",
    "notify_admins(settings.ADMIN_EMAILS, subject='nightly import failed')",
]


def _scenario(seed: int):  # type: ignore[no-untyped-def]
    import random

    rng = random.Random(seed)
    cands = []
    written: list[str] = []
    for ev in range(4):
        texts = rng.sample(POOL, 5)
        written += texts
        cands += _captured(
            texts, path=rng.choice(["/repo/src/app.py", "/repo/src/b.py", None]), event=f"ev{ev}"
        )
    for ev in range(3):
        cands += _captured(rng.sample(UNRELATED, 3), path="/repo/src/other.py", event=f"other{ev}")
    lines, n = [], 0
    for _ in range(14):
        kind = rng.choice(["exact", "edit", "wrap", "human", "trivial"])
        src = rng.choice(written)
        if kind == "exact":
            parts = [src]
        elif kind == "edit":
            parts = [src.replace("items", "entries").replace("customer", "client")]
        elif kind == "wrap":
            parts = [p.strip() + ("," if k < src.count(",") else "") for k, p in enumerate(src.split(","))]
        elif kind == "human":
            parts = [rng.choice(HUMAN_POOL)]
        else:
            parts = ["}", "return"]
        for text in parts:
            n += 1
            lines.append(_line(text, n, rng.choice(["src/app.py", "src/app.py", "src/b.py"])))
    return lines, cands


def test_lookup_keys_select_exactly_what_attribute_needs() -> None:
    from gcattr.match import lookup_keys, select_candidates

    matched = 0
    for seed in range(60):
        lines, cands = _scenario(seed)
        everything = attribute(lines, {ALICE: cands}, {1: TEST_KEY}, 1)
        lk = lookup_keys(lines, {1: TEST_KEY}, 1)[ALICE]
        subset = select_candidates(cands, lk)
        assert attribute(lines, {ALICE: subset}, {1: TEST_KEY}, 1) == everything, seed
        assert not any(c.capture_event_id.startswith("other") for c in subset)  # untouched work isn't loaded
        matched += sum(o.outcome in ("ai_unmodified", "ai_modified") for o in everything)
    assert matched > 200  # the scenarios exercise the AI tiers


# ------------------------------------------------------------------------------------- key independence
def test_a_one_token_rename_is_ai_modified_under_almost_any_key() -> None:
    """An outcome is a property of the code, not of the fingerprint key: renaming one identifier in a short AI line
    (true similarity 0.50, 4 of 8 token pairs kept) must come out AI modified under at least 99% of keys, or the
    same edit would score differently per installation and across a key rotation."""
    import hashlib

    from gcattr import FingerprintKey

    written = ["subtotal = sum(i.price for i in items)", "    return min(discount, subtotal_cents)"]
    committed = [_line(written[0], 1), _line("    return min(amount, subtotal_cents)", 2)]
    keys = [FingerprintKey(1, hashlib.sha256(f"key {n}".encode()).digest()) for n in range(300)]
    hits = 0
    for key in keys:
        res = attribute(committed, {ALICE: _captured(written, key=key)}, {1: key}, 1)
        assert res[0].outcome == "ai_unmodified"
        hits += res[1].outcome == "ai_modified" and res[1].tier == "anchored"
    assert hits / len(keys) >= 0.99, f"AI modified under {hits / len(keys):.1%} of keys"
