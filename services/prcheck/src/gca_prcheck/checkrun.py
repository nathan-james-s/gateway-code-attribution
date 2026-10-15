"""The `AI code attribution` check run (T054; contracts/github-app.md "Check run contract").

Conclusion is always neutral. Messages carry outcomes, tiers and confidence only, never code.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from gca_core.github import AppClient

__all__ = ["CHECK_NAME", "annotations", "complete", "start", "summary_markdown", "title"]

CHECK_NAME = "AI code attribution"
WAITING_TITLE = "Waiting for capture to catch up"
MAX_ANNOTATIONS = 50  # GitHub's limit per update

# Display labels (T067), used everywhere.
LABELS = {
    "ai_unmodified": "AI, unmodified",
    "ai_modified_anchored": "AI, modified (anchored)",
    "ai_modified_broad": "AI, modified (broad)",
    "human": "Human",
    "indeterminate": "Indeterminate",
    "not_observed": "Not observed",
}


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}%"


def title(summary: dict[str, Any], coverage_status: str, include_broad: bool) -> str:
    pct = summary["percentages_with_broad" if include_broad else "percentages_without_broad"]
    ind = summary["counts"]["indeterminate"]
    return f"AI {_pct(pct['ai'])} · human {_pct(pct['human'])} · indeterminate {ind} lines · coverage: {coverage_status}"


def summary_markdown(
    summary: dict[str, Any],
    *,
    coverage_status: str,
    coverage_reasons: Sequence[str],
    excluded: Sequence[dict[str, str]],
    alg: int,
    library_version: str,
    key_gens: Sequence[int],
    portal_link: str,
    include_broad: bool,
) -> str:
    c = summary["counts"]
    denom = summary["attributable"]

    def share(n: int) -> str:
        return "" if not denom else f"{100.0 * n / denom:.0f}%"

    rows = [
        "| Outcome | Lines | Share |",
        "|---|---:|---:|",
        *(
            f"| {LABELS[k]} | {c[k]} | {share(c[k])} |"
            for k in ("ai_unmodified", "ai_modified_anchored", "ai_modified_broad", "human")
        ),
        f"| {LABELS['indeterminate']} | {c['indeterminate']} | |",
        "",
        f"{LABELS['not_observed']}: {c['not_observed']} lines · Excluded: {len(excluded)} files",
    ]
    with_b, without_b = summary["percentages_with_broad"], summary["percentages_without_broad"]
    headline = "includes" if include_broad else "excludes"
    lines = [
        *rows,
        "",
        f"AI share without broad matches: **{_pct(without_b['ai'])}** · with broad matches: **{_pct(with_b['ai'])}** "
        f"(the title {headline} broad matches).",
        "",
        f"**Coverage:** {coverage_status}"
        + (f" ({', '.join(coverage_reasons)})" if coverage_reasons else ""),
        "",
        f"Algorithm version {alg} · gcattr {library_version} · key generations {', '.join(map(str, key_gens)) or 'none'}",
    ]
    if excluded:
        lines += ["", "**Excluded paths**", "", *(f"- `{e['path']}` ({e['reason']})" for e in excluded)]
    lines += [
        "",
        f"[Per-line results]({portal_link})",
        "",
        '"Human" means no match to observed AI output.',
    ]
    return "\n".join(lines)


def _ai_kind(outcome: str, tier: str) -> str | None:
    if outcome == "ai_unmodified":
        return "ai_unmodified"
    if outcome == "ai_modified":
        return f"ai_modified_{tier}"
    return None


_MESSAGES = {
    "ai_unmodified": "AI, unmodified",
    "ai_modified_anchored": "AI, modified (anchored) · high confidence",
    "ai_modified_broad": "AI, modified (broad) · lower confidence",
}


def annotations(rows: Sequence[tuple[str, int, str, str]]) -> list[dict[str, Any]]:
    """Group runs of consecutive lines with the same AI outcome. rows: (path, line_no, outcome, tier)."""
    out: list[dict[str, Any]] = []
    run: tuple[str, int, int, str] | None = None
    for path, line_no, outcome, tier in sorted(rows):
        kind = _ai_kind(outcome, tier)
        if run and kind == run[3] and path == run[0] and line_no == run[2] + 1:
            run = (run[0], run[1], line_no, kind)
            continue
        if run:
            out.append(_annotation(*run))
        run = (path, line_no, line_no, kind) if kind else None
    if run:
        out.append(_annotation(*run))
    return out


def _annotation(path: str, start: int, end: int, kind: str) -> dict[str, Any]:
    return {
        "path": path,
        "start_line": start,
        "end_line": end,
        "annotation_level": "notice",
        "title": CHECK_NAME,
        "message": _MESSAGES[kind],
    }


async def start(gh: AppClient, installation_id: int, owner: str, repo: str, head_sha: str) -> int:
    return await gh.create_check_run(
        installation_id,
        owner,
        repo,
        name=CHECK_NAME,
        head_sha=head_sha,
        status="in_progress",
        output={
            "title": WAITING_TITLE,
            "summary": "Attribution starts once capture has caught up with this push.",
        },
    )


async def complete(
    gh: AppClient,
    installation_id: int,
    owner: str,
    repo: str,
    check_run_id: int,
    *,
    title_text: str,
    summary: str,
    notes: Sequence[dict[str, Any]],
) -> None:
    batches = [list(notes[i : i + MAX_ANNOTATIONS]) for i in range(0, len(notes), MAX_ANNOTATIONS)] or [[]]
    await gh.update_check_run(
        installation_id,
        owner,
        repo,
        check_run_id,
        status="completed",
        conclusion="neutral",
        output={"title": title_text, "summary": summary, "annotations": batches[0]},
    )
    for batch in batches[1:]:  # GitHub appends annotations across updates
        await gh.update_check_run(
            installation_id,
            owner,
            repo,
            check_run_id,
            output={"title": title_text, "summary": summary, "annotations": batch},
        )
