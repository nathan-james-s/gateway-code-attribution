"""`gca eval` and `gca calibrate` (T108, T109; contracts/library-api.md).

    gca eval --scenarios eval/scenarios --gateway both --out report.json

Exit codes: 0 the release bar is met; 10 the release bar is missed (the failing measures are listed); 11 silent
capture loss was detected; 2 input error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .gateways import GATEWAYS
from .scenario import ScenarioError, load_all

__all__ = ["EXIT_BAR", "EXIT_SILENT", "register"]

EXIT_BAR, EXIT_SILENT, EXIT_INPUT = 10, 11, 2


def _gateways(choice: str) -> tuple[str, ...]:
    return GATEWAYS if choice == "both" else (choice,)


def _cmd_eval(args: argparse.Namespace) -> int:
    from . import report as rep
    from .runner import run

    try:
        scenarios = load_all(Path(args.scenarios), args.only)
    except (OSError, ScenarioError) as exc:
        print(f"gca eval: {exc}", file=sys.stderr)
        return EXIT_INPUT
    if not scenarios:
        print("gca eval: no scenarios found", file=sys.stderr)
        return EXIT_INPUT
    result = run(scenarios, _gateways(args.gateway), log=lambda m: print(m, file=sys.stderr))
    report = rep.build(result)
    complete = len(result.gateways) == len(GATEWAYS) and not args.only
    if complete:
        rep.validate(report)  # the schema needs both gateways over the whole set
    Path(args.out).write_text(json.dumps(report, indent=1) + "\n")
    _summary(report, complete)
    if any(g["capture"]["silent_loss"] for g in report["gateways"]):
        return EXIT_SILENT
    return 0 if report["passed"] else EXIT_BAR


def _summary(report: dict[str, Any], complete: bool) -> None:
    out = sys.stderr
    for g in report["gateways"]:
        state = "met" if g["passed"] else "MISSED: " + ", ".join(g["failures"])
        print(
            f"{g['gateway']:12} accuracy {g['accuracy']:.3f} over {g['lines_total']} lines; false AI modified "
            f"anchored {g['false_ai_modified_anchored']:.3f}, broad {g['false_ai_modified_broad']:.3f}; formatter "
            f"false human {g['formatter_false_human']:.3f}; rewrite survival {g['history_rewrite_survival']:.3f}; "
            f"silent loss {g['capture']['silent_loss']}. Release bar {state}.",
            file=out,
        )
        for p in g["problems"]:
            print(f"  problem: {p}", file=out)
    if "cross_gateway_agreement" in report:
        print(f"cross-gateway agreement {report['cross_gateway_agreement']:.3f}", file=out)
    if not complete:
        print("partial run (one gateway or --only): the report isn't the release gate's", file=out)


def _cmd_calibrate(args: argparse.Namespace) -> int:
    from .calibrate import calibrate

    try:
        scenarios = load_all(Path(args.scenarios))
    except (OSError, ScenarioError) as exc:
        print(f"gca calibrate: {exc}", file=sys.stderr)
        return EXIT_INPUT
    result = calibrate(scenarios, write=args.write, log=lambda m: print(m, file=sys.stderr))
    Path(args.out).write_text(json.dumps(result, indent=1) + "\n")
    return 0


def register(sub: Any) -> None:
    e = sub.add_parser("eval", help="run the scenario set through the gateways and write a quality report")
    e.add_argument("--scenarios", default="eval/scenarios", help="the scenario set directory")
    e.add_argument("--gateway", choices=["agentgateway", "litellm", "both"], default="both")
    e.add_argument("--out", default="report.json", help="where to write the quality report")
    e.add_argument("--only", nargs="*", help="run only scenarios whose names start with these (debugging)")
    e.set_defaults(func=_cmd_eval)
    c = sub.add_parser("calibrate", help="sweep the similarity thresholds over the scenario set (T109)")
    c.add_argument("--scenarios", default="eval/scenarios")
    c.add_argument("--out", default="calibration.json")
    c.add_argument(
        "--write", action="store_true", help="write the chosen thresholds into gcattr's PARAMS[ALG]"
    )
    c.set_defaults(func=_cmd_calibrate)
