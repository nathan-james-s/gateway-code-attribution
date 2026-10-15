"""Threshold calibration (T109; research R9).

The scenario set runs once through agentgateway (both gateways capture identically; conformance and
cross_gateway_agreement check that). Then matching is re-run over the stored lines and candidates for every
`anchored_threshold` from 0.30 to 0.90 and `broad_threshold` from 0.50 to 0.95, in steps of 0.05, on a fixed
70% calibration split of the scenario set's labelled lines. The split is by line, stratified by expected outcome
and tier: with a dozen scenarios, a split by scenario put every broad example in the held-out part. Matching
always runs on whole scenarios (multiset matching depends on every line); only the scoring is split. The pair
chosen maximizes accuracy subject to
`false_ai_modified_anchored <= 0.02` and `false_ai_modified_broad <= 0.05` (the release bar); ties go to the
more conservative pair (the higher broad threshold first), and the anchored threshold never exceeds the broad one.
The held-out 30% reports how the choice generalizes.

`--write` puts the chosen pair into `gcattr.algorithm.PARAMS[ALG]`. That is only allowed before `alg` is first
released: afterwards a threshold change alters outcomes, so it needs a new `ALG` (Constitution III).
"""

from __future__ import annotations

import dataclasses
import random
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gcattr import ALG, attribute
from gcattr import algorithm as algo

from .report import gateway_report, release_bar
from .runner import GatewayRun, run
from .scenario import Scenario

__all__ = ["calibrate", "split"]

SEED = 20261015
ALGORITHM = Path(algo.__file__)


def _steps(lo: float, hi: float) -> list[float]:
    return [round(lo + 0.05 * i, 2) for i in range(round((hi - lo) / 0.05) + 1)]


def split(scenarios: list[Scenario]) -> tuple[set[tuple[str, str, int]], set[tuple[str, str, int]]]:
    """A fixed 70/30 split of the labelled lines, stratified by expected outcome and tier (seeded)."""
    strata: dict[tuple[str, str | None], list[tuple[str, str, int]]] = {}
    for sc in scenarios:
        for (path, line), e in sc.expected.items():
            strata.setdefault((e.outcome, e.tier), []).append((sc.name, path, line))
    rng = random.Random(SEED)  # noqa: S311 - a reproducible split, not security
    cal: set[tuple[str, str, int]] = set()
    held: set[tuple[str, str, int]] = set()
    for key in sorted(strata, key=str):
        items = sorted(strata[key])
        rng.shuffle(items)
        k = round(len(items) * 0.7)
        cal.update(items[:k])
        held.update(items[k:])
    return cal, held


def _subset(scenarios: list[Scenario], keep: set[tuple[str, str, int]]) -> list[Scenario]:
    """The scenarios with only the labelled lines in ``keep`` (unlabelled-line checks are left to the report)."""
    out = []
    for sc in scenarios:
        expected = {k: v for k, v in sc.expected.items() if (sc.name, *k) in keep}
        out.append(dataclasses.replace(sc, expected=expected, attributable=True))
    return out


def _rerun(base: GatewayRun, anchored: float, broad: float, keys: Any) -> GatewayRun:
    original = algo.PARAMS[ALG]
    algo.PARAMS[ALG] = dataclasses.replace(original, anchored_threshold=anchored, broad_threshold=broad)
    try:
        cases = {
            name: dataclasses.replace(c, outcomes=attribute(c.lines, c.candidates, keys, ALG))
            for name, c in base.cases.items()
        }
    finally:
        algo.PARAMS[ALG] = original
    return GatewayRun(base.gateway, base.version, cases)


def _measures(run: GatewayRun, scenarios: list[Scenario], bar: dict[str, float]) -> dict[str, Any]:
    r = gateway_report(run, scenarios, bar)
    return {
        k: r[k] for k in ("accuracy", "false_ai_modified_anchored", "false_ai_modified_broad", "lines_total")
    }


def _write(anchored: float, broad: float) -> None:
    src = ALGORITHM.read_text()
    src, n1 = re.subn(r"anchored_threshold=[0-9.]+", f"anchored_threshold={anchored:.2f}", src, count=1)
    src, n2 = re.subn(r"broad_threshold=[0-9.]+", f"broad_threshold={broad:.2f}", src, count=1)
    if n1 != 1 or n2 != 1:
        raise RuntimeError(f"couldn't find the thresholds in {ALGORITHM}")
    ALGORITHM.write_text(src)


def calibrate(
    scenarios: list[Scenario], *, write: bool = False, log: Callable[[str], None] = print
) -> dict[str, Any]:
    bar = release_bar()
    result = run(scenarios, ("agentgateway",), log)
    base = result.gateways["agentgateway"]
    cal_keys, held_keys = split(scenarios)
    cal, held = _subset(scenarios, cal_keys), _subset(scenarios, held_keys)
    current = algo.PARAMS[ALG]
    grid = []
    for a in _steps(0.30, 0.90):
        for b in _steps(0.50, 0.95):
            rerun = _rerun(base, a, b, result.keys)
            m = _measures(rerun, cal, bar)
            m.update(anchored_threshold=a, broad_threshold=b)
            m["eligible"] = (
                a <= b  # anchoring exists to allow a lower bar than broad, never a higher one
                and m["false_ai_modified_anchored"] <= bar["max_false_ai_modified_anchored"]
                and m["false_ai_modified_broad"] <= bar["max_false_ai_modified_broad"]
            )
            grid.append(m)
    eligible = [g for g in grid if g["eligible"]]
    if not eligible:
        raise RuntimeError("no threshold pair meets the false AI modified limits on the calibration split")
    # Ties go to the more conservative pair: the higher broad threshold first (unanchored matches carry the most
    # risk on real traffic), then the higher anchored one.
    best = max(eligible, key=lambda g: (g["accuracy"], g["broad_threshold"], g["anchored_threshold"]))
    a, b = best["anchored_threshold"], best["broad_threshold"]
    chosen = _rerun(base, a, b, result.keys)
    now = _rerun(base, current.anchored_threshold, current.broad_threshold, result.keys)
    out = {
        "alg": ALG,
        "seed": SEED,
        "calibration_lines": len(cal_keys),
        "held_out_lines": len(held_keys),
        "current": {
            "anchored_threshold": current.anchored_threshold,
            "broad_threshold": current.broad_threshold,
            "calibration": _measures(now, cal, bar),
            "held_out": _measures(now, held, bar),
        },
        "chosen": {
            "anchored_threshold": a,
            "broad_threshold": b,
            "calibration": _measures(chosen, cal, bar),
            "held_out": _measures(chosen, held, bar),
            "all": _measures(chosen, scenarios, bar),
        },
        "grid": grid,
        "written": False,
    }
    log(
        f"current {current.anchored_threshold:.2f}/{current.broad_threshold:.2f}: "
        f"calibration accuracy {out['current']['calibration']['accuracy']:.3f}, held out "
        f"{out['current']['held_out']['accuracy']:.3f}"
    )
    log(
        f"chosen  {a:.2f}/{b:.2f}: calibration accuracy {out['chosen']['calibration']['accuracy']:.3f}, held out "
        f"{out['chosen']['held_out']['accuracy']:.3f}, all {out['chosen']['all']['accuracy']:.3f}"
    )
    if write and (a, b) != (current.anchored_threshold, current.broad_threshold):
        _write(a, b)
        out["written"] = True
        log(f"wrote anchored_threshold={a:.2f}, broad_threshold={b:.2f} into {ALGORITHM}")
    return out
