"""The quality report (T107; contracts/quality-report.schema.json; FR-044, SC-002, SC-003, SC-004, SC-007).

The release bar is read from the schema file, its single source; the numbers are never repeated in code. The
report is validated against the schema before it's written.

Measures, per gateway, over every labelled line of every scenario's pull request:

- accuracy: lines whose outcome matches the label / labelled lines;
- per outcome: expected, predicted and correct counts, precision and recall;
- false_ai_modified_anchored / _broad: lines labelled human that came out AI modified through that tier / lines
  that came out AI modified through that tier;
- formatter_false_human: AI lines changed only by a formatter that came out human / such lines;
- history_rewrite_survival: AI lines in rewrite scenarios that kept an AI outcome / such lines;
- capture: responses sent, faults injected, faults reported, and silent loss (responses neither captured nor
  reported as loss), which must be 0.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema

import gcattr

from .runner import GatewayRun, Run
from .scenario import OUTCOMES, Scenario

__all__ = ["SCHEMA", "build", "release_bar", "scenario_set_version", "validate"]

SCHEMA = (
    Path(__file__).resolve().parents[4]
    / "specs/001-gateway-code-attribution/contracts/quality-report.schema.json"
)
AI = ("ai_unmodified", "ai_modified")


def release_bar(schema_path: Path = SCHEMA) -> dict[str, float]:
    props = json.loads(schema_path.read_text())["properties"]["release_bar"]["properties"]
    return {k: v["const"] for k, v in props.items()}


def scenario_set_version(scenarios: list[Scenario]) -> str:
    h = hashlib.sha256()
    for sc in sorted(scenarios, key=lambda s: s.name):
        for p in sorted(sc.path.rglob("*")):
            if p.is_file():
                h.update(str(p.relative_to(sc.path.parent)).encode() + b"\0" + p.read_bytes())
    return f"{len(scenarios)}-scenarios-{h.hexdigest()[:12]}"


def _ratio(n: int, d: int, empty: float = 0.0) -> float:
    return round(n / d, 4) if d else empty


def _rows(run: GatewayRun, scenarios: list[Scenario]) -> tuple[list[dict[str, Any]], list[str]]:
    """(one row per labelled line: scenario, path, line, expected and predicted outcome and tier, tags), problems."""
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    for sc in scenarios:
        case = run.cases[sc.name]
        got = {(ln.file_path, ln.line_no): o for ln, o in zip(case.lines, case.outcomes, strict=True)}
        if not sc.attributable and got:
            problems.append(f"{sc.name}: expected nothing attributable, got {len(got)} lines")
        for key in sorted(got.keys() - sc.expected.keys()):
            problems.append(f"{sc.name}: {key[0]}:{key[1]} has no label")
        for key, exp in sorted(sc.expected.items()):
            o = got.get(key)
            rows.append(
                {
                    "scenario": sc.name,
                    "path": key[0],
                    "line": key[1],
                    "expected": exp.outcome,
                    "expected_tier": exp.tier,
                    "tags": list(exp.tags),
                    "predicted": o.outcome if o else "missing",
                    "tier": o.tier if o else "none",
                }
            )
            if o is None:
                problems.append(f"{sc.name}: {key[0]}:{key[1]} is labelled but wasn't attributed")
    return rows, problems


def gateway_report(run: GatewayRun, scenarios: list[Scenario], bar: dict[str, float]) -> dict[str, Any]:
    rows, problems = _rows(run, scenarios)
    correct = sum(r["predicted"] == r["expected"] for r in rows)
    per_outcome = {}
    for outcome in OUTCOMES:
        exp = sum(r["expected"] == outcome for r in rows)
        pred = sum(r["predicted"] == outcome for r in rows)
        ok = sum(r["expected"] == outcome and r["predicted"] == outcome for r in rows)
        per_outcome[outcome] = {
            "expected": exp,
            "predicted": pred,
            "correct": ok,
            "precision": _ratio(ok, pred, 1.0 if exp == 0 else 0.0),
            "recall": _ratio(ok, exp, 1.0),
        }

    def false_ai_modified(tier: str) -> float:
        tiered = [r for r in rows if r["predicted"] == "ai_modified" and r["tier"] == tier]
        return _ratio(sum(r["expected"] == "human" for r in tiered), len(tiered))

    formatter = [r for r in rows if "formatter" in r["tags"]]
    rewrite = [r for r in rows if "rewrite" in r["tags"] and r["expected"] in AI]
    responses = sum(c.responses for c in run.cases.values())
    injected = sum(1 for sc in scenarios for s in sc.streams if s.fault)
    reported = sum(sum(c.reported.values()) for c in run.cases.values())
    silent = sum(c.silent for c in run.cases.values())
    capture = {
        "responses": responses,
        "injected_faults": injected,
        "reported_faults": reported,
        "silent_loss": silent,
    }
    out = {
        "gateway": run.gateway,
        "gateway_version": run.version,
        "lines_total": len(rows),
        "accuracy": _ratio(correct, len(rows), 1.0),
        "per_outcome": per_outcome,
        "false_ai_modified_anchored": false_ai_modified("anchored"),
        "false_ai_modified_broad": false_ai_modified("broad"),
        "formatter_false_human": _ratio(sum(r["predicted"] == "human" for r in formatter), len(formatter)),
        "history_rewrite_survival": _ratio(sum(r["predicted"] in AI for r in rewrite), len(rewrite), 1.0),
        "capture": capture,
    }
    failures = []
    if out["accuracy"] < bar["min_accuracy"]:
        failures.append("accuracy")
    if out["false_ai_modified_anchored"] > bar["max_false_ai_modified_anchored"]:
        failures.append("false_ai_modified_anchored")
    if out["false_ai_modified_broad"] > bar["max_false_ai_modified_broad"]:
        failures.append("false_ai_modified_broad")
    if out["formatter_false_human"] > bar["max_formatter_false_human"]:
        failures.append("formatter_false_human")
    if silent > bar["max_silent_loss"]:
        failures.append("silent_loss")
    if problems:
        failures.append("scenario_problems")
    out["passed"] = not failures
    out["failures"] = failures
    out["problems"] = problems
    out["wrong_lines"] = [
        {k: r[k] for k in ("scenario", "path", "line", "expected", "expected_tier", "predicted", "tier")}
        for r in rows
        if r["predicted"] != r["expected"]
    ]
    out["by_scenario"] = {
        sc.name: {
            "lines": sum(r["scenario"] == sc.name for r in rows),
            "correct": sum(r["scenario"] == sc.name and r["predicted"] == r["expected"] for r in rows),
            "loss": run.cases[sc.name].reported,
            "expected_loss": sc.expected_loss,
            "client_errors": run.cases[sc.name].client_errors,
        }
        for sc in scenarios
    }
    return out


def build(run: Run) -> dict[str, Any]:
    bar = release_bar()
    gateways = [gateway_report(g, run.scenarios, bar) for g in run.gateways.values()]
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "library_version": gcattr.__version__,
        "alg": gcattr.ALG,
        "scenario_set_version": scenario_set_version(run.scenarios),
        "release_bar": bar,
        "gateways": gateways,
    }
    if len(run.gateways) > 1:
        a, b = list(run.gateways.values())[:2]
        same = total = 0
        for name, ca in a.cases.items():
            cb = b.cases[name]
            ob = {(ln.file_path, ln.line_no): o.outcome for ln, o in zip(cb.lines, cb.outcomes, strict=True)}
            for ln, o in zip(ca.lines, ca.outcomes, strict=True):
                total += 1
                same += ob.get((ln.file_path, ln.line_no)) == o.outcome
        report["cross_gateway_agreement"] = _ratio(same, total, 1.0)
    agreement_ok = report.get("cross_gateway_agreement", 1.0) == 1.0
    report["passed"] = all(g["passed"] for g in gateways) and agreement_ok and len(gateways) >= 2
    return report


def validate(report: dict[str, Any], schema_path: Path = SCHEMA) -> None:
    schema = json.loads(schema_path.read_text())
    jsonschema.validate(report, schema, format_checker=jsonschema.FormatChecker())
