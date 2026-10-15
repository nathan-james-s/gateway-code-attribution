"""T054: check run title, summary and annotations follow contracts/github-app.md."""

from __future__ import annotations

from gca_prcheck import checkrun
from gcattr import LineOutcome, summarize


def _summary() -> dict:
    outs = (
        [LineOutcome("ai_unmodified", "exact", None, None, "e")] * 5
        + [LineOutcome("ai_modified", "anchored", "high", 0.8, "e")]
        + [LineOutcome("ai_modified", "broad", "lower", 0.8, "e")]
        + [LineOutcome("human", "none", None, None, None)] * 3
        + [LineOutcome("indeterminate", "none", None, None, None)] * 2
        + [LineOutcome("not_observed", "none", None, None, None)]
    )
    return summarize(outs)


def test_title_excludes_broad_by_default() -> None:
    s = _summary()
    assert (
        checkrun.title(s, "complete", False)
        == "AI 60% · human 40% · indeterminate 2 lines · coverage: complete"
    )
    assert (
        checkrun.title(s, "complete", True)
        == "AI 70% · human 30% · indeterminate 2 lines · coverage: complete"
    )


def test_summary_has_labels_and_no_code() -> None:
    md = checkrun.summary_markdown(
        _summary(),
        coverage_status="complete",
        coverage_reasons=[],
        excluded=[{"path": "big.json", "reason": "too_large"}],
        alg=1,
        library_version="0.1.0",
        key_gens=[1],
        portal_link="http://p/changes/o/r/1",
        include_broad=False,
    )
    for label in (
        "AI, unmodified",
        "AI, modified (anchored)",
        "AI, modified (broad)",
        "Human",
        "Indeterminate",
    ):
        assert f"| {label} |" in md
    assert "Not observed: 1 lines" in md and "`big.json` (too_large)" in md
    assert "no match to observed AI output" in md and "http://p/changes/o/r/1" in md


def test_annotations_group_runs() -> None:
    rows = [
        ("a.py", 1, "ai_unmodified", "exact"),
        ("a.py", 2, "ai_unmodified", "exact"),
        ("a.py", 3, "ai_modified", "anchored"),
        ("a.py", 4, "human", "none"),
        ("a.py", 5, "ai_unmodified", "exact"),
        ("b.py", 6, "ai_unmodified", "exact"),
    ]
    notes = checkrun.annotations(rows)
    assert [(n["path"], n["start_line"], n["end_line"], n["message"]) for n in notes] == [
        ("a.py", 1, 2, "AI, unmodified"),
        ("a.py", 3, 3, "AI, modified (anchored) · high confidence"),
        ("a.py", 5, 5, "AI, unmodified"),
        ("b.py", 6, 6, "AI, unmodified"),
    ]
    assert all(n["annotation_level"] == "notice" for n in notes)


async def test_complete_batches_annotations() -> None:
    calls: list[dict] = []

    class GH:
        async def update_check_run(self, *args: object, **body: object) -> None:
            calls.append(body)

    notes = [{"path": "a", "start_line": i, "end_line": i} for i in range(120)]
    await checkrun.complete(GH(), 1, "o", "r", 9, title_text="t", summary="s", notes=notes)  # type: ignore[arg-type]
    assert [len(c["output"]["annotations"]) for c in calls] == [50, 50, 20]
    assert calls[0]["conclusion"] == "neutral" and calls[0]["status"] == "completed"
