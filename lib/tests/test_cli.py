"""T096: the `gca` CLI. `fingerprint` reproduces the golden corpus; `attribute` reads a local branch the way the PR
check reads a pull request, credits lines by blame, and writes nothing to disk."""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gcattr import cli
from gcattr.io import candidate_to_json, fingerprint_outputs
from gcattr.streams import parse_stream
from gcattr.types import Candidate

from .golden.generate import HERE, KEY

CORPUS = HERE / "alg-1"
PY = (CORPUS / "inputs" / "anthropic.sse").read_bytes()


@pytest.fixture
def key_file(tmp_path: Path) -> Path:
    p = tmp_path / "key"
    p.write_text(base64.b64encode(KEY.secret).decode())
    return p


def _run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str], stdin: bytes = b""
):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin)))
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.mark.parametrize(
    ("name", "fmt"),
    [
        ("openai_chat.sse", "openai_chat"),
        ("openai_responses.sse", "openai_responses"),
        ("anthropic_truncated.sse", "anthropic_messages"),
        ("gemini.sse", "gemini_native"),
    ],
)
def test_fingerprint_matches_the_golden_corpus(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], key_file: Path, name: str, fmt: str
) -> None:
    data = (CORPUS / "inputs" / name).read_bytes()
    code, out, _ = _run(
        monkeypatch, capsys, ["fingerprint", "--key-file", str(key_file), "--format", fmt], data
    )
    assert code == 0
    assert out == (CORPUS / "fingerprints" / f"{name}.jsonl").read_text()


def test_fingerprint_prints_no_content(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], key_file: Path
) -> None:
    code, out, _ = _run(
        monkeypatch,
        capsys,
        ["--json", "fingerprint", "--key-file", str(key_file), "--format", "anthropic_messages"],
        PY,
    )
    assert code == 0 and json.loads(out)["tool_call_count"] >= 1
    for needle in ("subtotal", "def total", "café", "round("):
        assert needle not in out


def test_input_errors_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    bad = tmp_path / "bad"
    bad.write_text("not base64!")
    code, _, err = _run(
        monkeypatch, capsys, ["fingerprint", "--key-file", str(bad), "--format", "openai_chat"]
    )
    assert code == 2 and "not a base64 key" in err
    short = tmp_path / "short"
    short.write_text(base64.b64encode(b"x" * 8).decode())
    assert (
        _run(monkeypatch, capsys, ["fingerprint", "--key-file", str(short), "--format", "openai_chat"])[0]
        == 2
    )


def test_key_directory_in_the_secret_layout(tmp_path: Path) -> None:
    from gcattr.io import load_keys

    (tmp_path / "1").write_text(base64.b64encode(b"\x01" * 32).decode())
    (tmp_path / "2").write_text(base64.b64encode(b"\x02" * 32).decode())
    (tmp_path / "active").write_text("2")
    keys, active = load_keys(tmp_path)
    assert active == 2 and sorted(keys) == [1, 2] and keys[1].secret == b"\x01" * 32


# ----------------------------------------------------------------------------------------------- attribute
def _git(repo: Path, *args: str, email: str = "base@example.com") -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": "a",
           "GIT_COMMITTER_EMAIL": email, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}  # fmt: skip
    return subprocess.run(
        ["git", "-C", str(repo), *args], env=env, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """main: a stub app. feature: 4242 adds the AI-written code (lightly edited), a human line, a lock file and a
    renamed file; then an author GitHub can't link adds a line."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    (r / "src").mkdir()
    (r / "src" / "app.py").write_text("# app\n")
    (r / "old name.py").write_text("x = 1\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    _git(r, "checkout", "-qb", "feature")
    (r / "src" / "app.py").write_text(
        "# app\n"
        "def total(items):\n"
        "\tsubtotal = sum(i.price for i in items)  # cafe\n"
        "    print(\"a\\nb\", 'quote')\n"
        "    log_everything_to_a_remote_audit_service(items, verbose=True)\n"
    )
    (r / "package-lock.json").write_text('{"lockfileVersion": 3}\n')
    _git(r, "mv", "old name.py", "new name.py")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "ai", email="4242+ada@users.noreply.github.com")
    with (r / "src" / "app.py").open("a") as fh:
        fh.write("    return round(subtotal * 1.0825, 2)\n")
    _git(r, "commit", "-qam", "someone", email="someone@elsewhere.example")
    return r


def _captures(path: Path) -> Path:
    fps = fingerprint_outputs(parse_stream("anthropic_messages", [PY]), KEY).lines
    with path.open("w") as fh:
        for f in fps:
            c = Candidate("ev-1", f.exact_fp, f.minhash, f.path_suffix_fps, f.tool_call_ordinal, f.line_ordinal,
                          f.alg, f.key_gen, f.lsh_bands)  # fmt: skip
            fh.write(json.dumps(candidate_to_json(c, 4242)) + "\n")
    return path


def test_attribute_a_local_branch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    repo: Path,
    key_file: Path,
    tmp_path: Path,
) -> None:
    caps = _captures(tmp_path / "captures.jsonl")
    before = sorted(p.name for p in tmp_path.rglob("*") if ".git" not in p.parts)
    argv = ["--json", "attribute", "--repo", str(repo), "--base", "main", "--head", "feature",
            "--captures", str(caps), "--key-file", str(key_file)]  # fmt: skip
    code, out, err = _run(monkeypatch, capsys, argv)
    assert code == 0, err
    report = json.loads(out)
    got = {
        (r["file_path"], r["line_no"]): (r["outcome"], r["tier"], r["credited_github_id"])
        for r in report["lines"]
    }
    assert got == {
        ("src/app.py", 2): ("ai_unmodified", "exact", 4242),
        ("src/app.py", 3): ("ai_modified", "anchored", 4242),
        ("src/app.py", 4): ("ai_unmodified", "exact", 4242),
        ("src/app.py", 5): ("human", "none", 4242),
        ("src/app.py", 6): ("not_observed", "none", None),  # its author has no GitHub account link
    }
    assert {"path": "package-lock.json", "reason": "rule"} in report["excluded"]  # default rules apply
    assert report["summary"]["counts"]["not_observed"] == 1
    assert "text" not in report["lines"][0] and "subtotal" not in out  # no content without --explain
    after = sorted(p.name for p in tmp_path.rglob("*") if ".git" not in p.parts)
    assert after == before and _git(repo, "status", "--porcelain") == ""  # nothing written


def test_attribute_author_map_and_explain(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    repo: Path,
    key_file: Path,
    tmp_path: Path,
) -> None:
    caps = _captures(tmp_path / "captures.jsonl")
    argv = ["attribute", "--repo", str(repo), "--base", "main", "--head", "feature", "--captures", str(caps),
            "--key-file", str(key_file), "--author", "someone@elsewhere.example=4242", "--exclude", "**/*.py",
            "--explain"]  # fmt: skip
    code, out, _ = _run(monkeypatch, capsys, argv)
    assert code == 0
    assert "src/app.py\texcluded (rule)" in out  # --exclude replaces the default rules
    assert "package-lock.json:1" in out  # no longer excluded, and shown with --explain
    assert "lockfileVersion" in out


def test_attribute_bad_refs_exit_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    repo: Path,
    key_file: Path,
    tmp_path: Path,
) -> None:
    caps = _captures(tmp_path / "c.jsonl")
    argv = ["attribute", "--repo", str(repo), "--base", "main", "--head", "nope", "--captures", str(caps),
            "--key-file", str(key_file)]  # fmt: skip
    code, _, err = _run(monkeypatch, capsys, argv)
    assert code == 2 and "git rev-parse failed" in err
