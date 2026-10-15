"""User Story 6 without the gateways: the scenario set is consistent, the report measures what the schema says,
calibration splits reproducibly, and the corpus recorder refuses to record without consent."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gca_eval import report
from gca_eval.calibrate import split
from gca_eval.runner import Case, GatewayRun, github_id
from gca_eval.scenario import build_repo, load, load_all
from gcattr import LineOutcome
from gcattr.diff import DEFAULT_EXCLUSIONS, ExclusionRules
from gcattr.gitlocal import read_change

ROOT = Path(__file__).resolve().parents[3]
SCENARIOS = ROOT / "eval" / "scenarios"
ALL = load_all(SCENARIOS)


def _module(name: str, path: Path):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_the_set_covers_every_category() -> None:
    cats = {s.name.split("-")[0] for s in ALL}
    assert {"seed", "human", "formatters", "lookalike", "refactor", "multi", "faults", "key", "empty"} <= cats
    seed = next(s for s in ALL if s.name == "seed-line-accuracy")
    assert len(seed.expected) == 59  # spec 002's line-accuracy set
    assert sum(len(s.expected) for s in ALL if "rewrite" in s.name) >= 30  # and its 30 rewrite lines


def test_committed_scenarios_match_the_generator(tmp_path: Path) -> None:
    gen = _module("gca_scenarios_generate", SCENARIOS / "generate.py")
    for fn in gen.SCENARIOS:
        b = fn()
        written = b.write(tmp_path)
        for f in sorted(p for p in written.rglob("*") if p.is_file()):
            committed = SCENARIOS / b.name / f.relative_to(written)
            assert committed.read_bytes() == f.read_bytes(), f"{committed} differs from generate.py's output"


@pytest.mark.parametrize("sc", ALL, ids=[s.name for s in ALL])
def test_every_added_line_is_labelled(sc, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    repo = build_repo(sc, tmp_path)
    authors = {
        e: github_id(sc.name, a) for a, e in sc.authors.items() if a != "base" and a not in sc.unmapped
    }
    change = read_change(
        str(repo), sc.pr["base"], sc.pr["head"], rules=ExclusionRules(DEFAULT_EXCLUSIONS), authors=authors
    )
    keys = {(ln.file_path, ln.line_no) for ln in change.lines}
    if not sc.attributable:
        assert keys == set() and not sc.expected
        return
    assert keys == set(sc.expected), (
        sorted(keys - set(sc.expected))[:3],
        sorted(set(sc.expected) - keys)[:3],
    )
    for ln in change.lines:  # crediting: unmapped authors' lines carry no account
        exp = sc.expected[(ln.file_path, ln.line_no)]
        assert (ln.credited_github_id is None) == (exp.outcome == "not_observed"), (ln.file_path, ln.line_no)


def test_rewrites_keep_authorship(tmp_path: Path) -> None:
    sc = load(SCENARIOS / "seed-rewrite-rebase")
    repo = build_repo(sc, tmp_path)
    change = read_change(str(repo), "main", "feature", authors={sc.authors["ada"]: 1})
    assert {ln.credited_github_id for ln in change.lines} == {1}


def test_release_bar_comes_from_the_schema() -> None:
    schema = json.loads(report.SCHEMA.read_text())["properties"]["release_bar"]["properties"]
    assert report.release_bar() == {k: v["const"] for k, v in schema.items()}


def _run(outcomes: dict[str, list[LineOutcome]]) -> GatewayRun:
    cases = {}
    for sc in ALL:
        o = outcomes.get(sc.name)
        if o is None:  # predict exactly the labels
            o = [
                LineOutcome(e.outcome, "anchored" if e.outcome == "ai_modified" else "none", None, None, None)
                for e in sc.expected.values()
            ]
        from gcattr import AddedLine

        lines = [AddedLine(p, n, "", 1) for (p, n) in sc.expected]
        cases[sc.name] = Case(
            sc.name, lines, o, {}, [], len(sc.streams), len(sc.streams), dict(sc.expected_loss), 0
        )
    return GatewayRun("agentgateway", "1.6.0", cases)


def test_perfect_predictions_meet_the_bar() -> None:
    g = report.gateway_report(_run({}), ALL, report.release_bar())
    assert g["accuracy"] == 1.0 and g["passed"] and g["failures"] == []
    assert g["history_rewrite_survival"] == 1.0 and g["capture"]["silent_loss"] == 0


def test_wrong_predictions_fail_the_named_measures() -> None:
    lookalike = next(s for s in ALL if s.name.startswith("lookalike"))
    fmt = next(s for s in ALL if s.name.startswith("formatters"))
    bad = {
        lookalike.name: [LineOutcome("ai_modified", "anchored", "high", 0.9, "e")] * len(lookalike.expected),
        fmt.name: [LineOutcome("human", "none", None, None, None)] * len(fmt.expected),
    }
    g = report.gateway_report(_run(bad), ALL, report.release_bar())
    assert not g["passed"]
    assert {"accuracy", "false_ai_modified_anchored", "formatter_false_human"} <= set(g["failures"])
    assert g["per_outcome"]["human"]["recall"] < 1.0


def test_calibration_split_is_fixed_and_stratified() -> None:
    cal, held = split(ALL)
    assert (cal, held) == split(ALL) and not cal & held
    total = sum(len(s.expected) for s in ALL)
    assert len(cal) + len(held) == total and 0.6 < len(cal) / total < 0.8
    broad = {(s.name, *k) for s in ALL for k, e in s.expected.items() if e.tier == "broad"}
    assert broad & cal and broad & held  # both halves see broad examples


# ----------------------------------------------------------------------------------------------- recorder (T111)
def test_recorder_needs_consent_then_records_responses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _module("gca_corpus_record", ROOT / "eval" / "corpus" / "record.py")
    monkeypatch.setattr(record, "HERE", tmp_path)
    assert record.main(["--tool", "claude-code"]) == 2  # no consent yet
    assert record.main(["--tool", "claude-code", "--owner", "Test Owner", "--i-consent"]) == 0
    assert "consent: true" in (tmp_path / "claude-code" / "consent.yaml").read_text()

    from gca_demo.model import Handler

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    rec = record.Recorder("claude-code", f"http://127.0.0.1:{upstream.server_address[1]}")
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), record.handler_for(rec))
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        body = json.dumps({"model": "demo", "stream": True, "messages": [{"role": "user", "content": "hi"}]})
        req = urllib.request.Request(
            f"http://127.0.0.1:{proxy.server_address[1]}/v1/messages",
            data=body.encode(),
            headers={"content-type": "application/json", "x-api-key": "sk-gca-secret"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            got = r.read()
        recorded = tmp_path / "claude-code" / "anthropic_messages" / "001.sse"
        assert recorded.read_bytes() == got and b"message_stop" in got  # exactly what the tool received
        assert b"sk-gca-secret" not in recorded.read_bytes() and b'"hi"' not in recorded.read_bytes()
    finally:
        proxy.shutdown()
        upstream.shutdown()
