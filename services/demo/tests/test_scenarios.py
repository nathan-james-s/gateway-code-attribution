"""T080: every scenario's answer key is what the matcher produces, under any fingerprint key.

The scripted edits must sit far from the similarity thresholds, because each install has its own random key.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from gca_demo import agent, model
from gca_demo.scenarios import expected_labels
from gca_demo.sessions import Session, sessions
from gcattr import (
    ALG,
    AddedLine,
    Candidate,
    CapturedToolOutput,
    FingerprintKey,
    attribute,
    extract,
    parse_stream,
)

SCENARIOS = sorted(k for k, v in sessions().items() if v.kind == "scenario")
IDS = {"first": 1, "second": 2, "unmapped": None}


def _send(api_format: str, text: str) -> bytes:
    path = {"gemini_native": "/v1beta/models/demo-gemini:streamGenerateContent"}.get(api_format, "/v1/x")
    body = json.dumps({"stream": True, "messages": [{"role": "user", "content": text}], "input": text})
    return model.respond(api_format, path, body)[1]


def _build(
    s: Session, repo: Path
) -> tuple[dict[str, str], dict[str, set[str]], dict[str, str], list[tuple[str, CapturedToolOutput]]]:
    ai_lines: dict[str, set[str]] = {}
    author: dict[str, str] = {}
    captured = []
    for i, step in enumerate(s.steps):
        for out in parse_stream(step.format, [_send(step.format, f"gca-demo session={s.name} step={i}")]):  # type: ignore[arg-type]
            assert isinstance(out, CapturedToolOutput)
            agent.apply_output(repo, out)
            captured.append((step.author, out))
        ai_lines.setdefault(step.file, set()).update(ln.strip() for ln in (step.write or "").splitlines())
        author[step.file] = step.author
    for edit in s.human_edits:
        agent.apply_human_edit(repo, edit)
        author.setdefault(edit["file"], edit.get("author", "first"))
    files = {p: (repo / p).read_text() for p in author}
    return files, ai_lines, author, captured


@pytest.mark.parametrize("name", SCENARIOS)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_answer_key_holds_under_any_key(name: str, seed: int, tmp_path: Path) -> None:
    s = sessions()[name]
    files, ai_lines, author, captured = _build(s, tmp_path)
    expected = expected_labels(files, ai_lines, author, s.expect)
    key = FingerprintKey(1, os.urandom(32) if seed else b"\x00" * 32)
    candidates: dict[int, list[Candidate]] = {1: [], 2: []}
    for n, (who, out) in enumerate(captured):
        for fp in extract(out, key, ALG, tool_call_ordinal=1):
            candidates[IDS[who] or 0].append(
                Candidate(
                    f"ev{n}",
                    fp.exact_fp,
                    fp.minhash,
                    fp.path_suffix_fps,
                    fp.tool_call_ordinal,
                    fp.line_ordinal,
                    fp.alg,
                    fp.key_gen,
                    fp.lsh_bands,
                )
            )
    lines = [
        AddedLine(p, no, t, IDS[author[p]])
        for p, c in files.items()
        for no, t in enumerate(c.splitlines(), start=1)
    ]
    got = attribute(lines, candidates, {1: key}, ALG)
    for ln, o in zip(lines, got, strict=True):
        assert o.outcome == expected[ln.file_path][str(ln.line_no)], (name, ln.file_path, ln.line_no, ln.text)


def test_scenarios_cover_quickstart_cases() -> None:
    assert len(SCENARIOS) == 10
    labels = set()
    for name in SCENARIOS:
        s = sessions()[name]
        labels |= {v for f in s.expect.values() for v in ([] if isinstance(f, list) else [f])}
    kinds = {sessions()[n].name for n in SCENARIOS}
    assert {
        "scn-unmodified",
        "scn-edited",
        "scn-typed",
        "scn-trivial",
        "scn-rewrite",
        "scn-cherry-pick",
        "scn-pending",
        "scn-unmapped",
        "scn-two-authors",
        "scn-new-push",
    } == kinds


def test_pausing_ingest_waits_for_its_pod_to_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """scn-pending opens its PR only once ingest has stopped; a terminating pod still stores captures."""
    import argparse

    from gca_demo import scenarios

    calls: list[list[str]] = []
    pods = ["pod/gca-gca-ingest-1", "pod/gca-gca-ingest-1", ""]  # terminating, terminating, gone

    def run(cmd: list[str], cwd: Path | None = None) -> str:
        calls.append(cmd)
        return pods.pop(0) if "get" in cmd else ""

    monkeypatch.setattr(scenarios, "_run", run)
    monkeypatch.setattr(scenarios.time, "sleep", lambda s: None)
    r = scenarios.Runner.__new__(scenarios.Runner)
    r.args = argparse.Namespace(kube_context="kind-gca", namespace="gca", release="gca")
    r.kubectl_scale(0)
    assert [c[5] for c in calls] == ["scale", "get", "get", "get"]
    assert "app.kubernetes.io/instance=gca,app.kubernetes.io/component=ingest" in calls[1]
    calls.clear()
    r.kubectl_scale(1)  # resuming doesn't wait
    assert [c[5] for c in calls] == ["scale"]
