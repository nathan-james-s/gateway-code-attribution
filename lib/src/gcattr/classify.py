"""Summaries of line outcomes (FR-009, FR-014, FR-028)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .types import LineOutcome

__all__ = ["summarize"]


def _pct(part: int, whole: int) -> float | None:
    return None if whole == 0 else round(100.0 * part / whole, 2)


def summarize(outcomes: Sequence[LineOutcome]) -> dict[str, Any]:
    counts = {
        "ai_unmodified": 0,
        "ai_modified_anchored": 0,
        "ai_modified_broad": 0,
        "human": 0,
        "indeterminate": 0,
        "not_observed": 0,
    }
    for o in outcomes:
        if o.outcome == "ai_modified":
            counts["ai_modified_anchored" if o.tier == "anchored" else "ai_modified_broad"] += 1
        else:
            counts[o.outcome] += 1
    ai_mod = counts["ai_modified_anchored"] + counts["ai_modified_broad"]
    denom = counts["ai_unmodified"] + ai_mod + counts["human"]  # indeterminate and not_observed excluded
    with_broad = {
        "ai": _pct(counts["ai_unmodified"] + ai_mod, denom),
        "ai_unmodified": _pct(counts["ai_unmodified"], denom),
        "ai_modified": _pct(ai_mod, denom),
        "human": _pct(counts["human"], denom),
    }
    # Without broad matches, broad lines count as human.
    without_broad = {
        "ai": _pct(counts["ai_unmodified"] + counts["ai_modified_anchored"], denom),
        "ai_unmodified": _pct(counts["ai_unmodified"], denom),
        "ai_modified": _pct(counts["ai_modified_anchored"], denom),
        "human": _pct(counts["human"] + counts["ai_modified_broad"], denom),
    }
    return {
        "counts": counts,
        "attributable": denom,
        "percentages_with_broad": with_broad,
        "percentages_without_broad": without_broad,
    }
