"""T094: the golden corpus (FR-032, FR-033, SC-008; Constitution III). For every supported algorithm version, the
outputs recomputed from the corpus inputs are byte-identical to the stored ones, on every platform CI runs on."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gcattr import ALG, SUPPORTED_ALGS

from .golden.generate import HERE, outputs, read_inputs


def test_every_supported_alg_has_a_corpus() -> None:
    assert ALG in SUPPORTED_ALGS
    for alg in SUPPORTED_ALGS:
        assert (HERE / f"alg-{alg}" / "inputs").is_dir(), f"no golden corpus for alg {alg}"


@pytest.mark.parametrize("alg", SUPPORTED_ALGS)
def test_outputs_are_byte_identical(alg: int) -> None:
    corpus = HERE / f"alg-{alg}"
    expected = {
        str(p.relative_to(corpus)): p.read_bytes()
        for p in sorted(corpus.rglob("*"))
        if p.is_file() and p.relative_to(corpus).parts[0] != "inputs"
    }
    got = outputs(alg, read_inputs(corpus))
    assert sorted(got) == sorted(expected), "the corpus files differ from what the generator produces"
    changed = [name for name in got if got[name] != expected[name]]
    assert not changed, (
        f"alg {alg} outputs changed: {changed}. A change that alters fingerprints or outcomes needs a new ALG "
        "and a new corpus (Constitution III, FR-032), never a regenerated one."
    )


def test_attribution_case_covers_every_outcome_and_tier() -> None:
    rows = [
        json.loads(ln) for ln in (HERE / f"alg-{ALG}" / "attribute.expected.jsonl").read_text().splitlines()
    ]
    assert {r["outcome"] for r in rows} == {
        "ai_unmodified",
        "ai_modified",
        "human",
        "indeterminate",
        "not_observed",
    }
    assert {r["tier"] for r in rows} == {"exact", "anchored", "broad", "none"}


def test_corpus_has_failures_too() -> None:
    truncated = (Path(HERE) / f"alg-{ALG}" / "fingerprints" / "anthropic_truncated.sse.jsonl").read_text()
    assert '{"failure":"truncated"}' in truncated
