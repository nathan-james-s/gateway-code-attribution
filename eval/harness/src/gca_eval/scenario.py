"""The scenario format (T100; eval/scenarios/README.md). A scenario is a directory:

- `repo.yaml`: the authors (aliases), the model output streams to send, the git operations that build the
  repository, and the pull request range to attribute;
- `streams/*.sse`: recorded model output, one response per file, in its API format's wire form;
- `edits.yaml`: how the committed code came from the model output (human edits, formatter passes). Provenance
  for readers; the committed files in `repo.yaml` already include them;
- `expected.json`: the expected outcome of every added line in the pull request (and the tier for AI modified
  lines), plus the capture loss the streams should cause.

Aliases stand for test developers. The runner gives each (scenario, alias) its own GitHub account id and gateway
credential, so one scenario's captures can never match another scenario's lines.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "OPERATIONS",
    "ExpectedLine",
    "Scenario",
    "ScenarioError",
    "StreamSpec",
    "build_repo",
    "load",
    "load_all",
]

OPERATIONS = ("commit", "branch", "rebase", "squash", "cherry_pick")
OUTCOMES = ("ai_unmodified", "ai_modified", "human", "indeterminate", "not_observed")
FAULTS = ("truncated", "unexpected_format", "dropped")


class ScenarioError(ValueError):
    pass


@dataclass(frozen=True)
class StreamSpec:
    file: str
    author: str  # alias
    api_format: str
    key_gen: int = 1  # the fingerprint key generation active when it's sent (key rotation scenarios)
    fault: str | None = (
        None  # truncated | unexpected_format | dropped (its capture message never reaches ingest)
    )


@dataclass(frozen=True)
class ExpectedLine:
    outcome: str
    tier: str | None = None  # for ai_modified: anchored | broad | any
    tags: tuple[str, ...] = ()  # formatter | rewrite | lookalike | unapplied | path_only ...


@dataclass
class Scenario:
    name: str
    path: Path
    category: str
    authors: dict[str, str]  # alias -> commit email ("base" is the repository's owner, never captured)
    streams: list[StreamSpec]
    operations: list[dict[str, Any]]
    pr: dict[str, str]  # {"base": ref, "head": ref}
    expected: dict[tuple[str, int], ExpectedLine]
    expected_loss: dict[str, int] = field(default_factory=dict)
    attributable: bool = True  # False for PRs that must report nothing attributable (not 0%)
    unmapped: tuple[str, ...] = ()  # aliases GitHub links to no account: their lines are not observed

    def stream_bytes(self, spec: StreamSpec) -> bytes:
        return (self.path / "streams" / spec.file).read_bytes()


def _require(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise ScenarioError(f"{where}: missing {key!r}")
    return d[key]


def load(path: Path) -> Scenario:
    where = path.name
    repo = yaml.safe_load((path / "repo.yaml").read_text())
    exp = json.loads((path / "expected.json").read_text())
    authors = {str(k): str(v) for k, v in _require(repo, "authors", where).items()}
    streams = [StreamSpec(**s) for s in repo.get("streams", [])]
    for s in streams:
        if s.author not in authors:
            raise ScenarioError(f"{where}: stream {s.file} names unknown author {s.author!r}")
        if s.fault is not None and s.fault not in FAULTS:
            raise ScenarioError(f"{where}: stream {s.file}: unknown fault {s.fault!r}")
        if not (path / "streams" / s.file).is_file():
            raise ScenarioError(f"{where}: missing streams/{s.file}")
    ops = _require(repo, "operations", where)
    for op in ops:
        if op.get("op") not in OPERATIONS:
            raise ScenarioError(f"{where}: unknown operation {op.get('op')!r}")
    expected: dict[tuple[str, int], ExpectedLine] = {}
    for key, v in exp.get("lines", {}).items():
        file_path, _, line_no = key.rpartition(":")
        if v["outcome"] not in OUTCOMES:
            raise ScenarioError(f"{where}: {key}: unknown outcome {v['outcome']!r}")
        expected[(file_path, int(line_no))] = ExpectedLine(
            v["outcome"], v.get("tier"), tuple(v.get("tags", []))
        )
    return Scenario(
        name=path.name,
        path=path,
        category=str(repo.get("category", path.name.split("-")[0])),
        authors=authors,
        streams=streams,
        operations=ops,
        pr=_require(repo, "pr", where),
        expected=expected,
        expected_loss={str(k): int(v) for k, v in exp.get("loss", {}).items()},
        attributable=bool(exp.get("attributable", True)),
        unmapped=tuple(repo.get("unmapped", [])),
    )


def load_all(root: Path, only: list[str] | None = None) -> list[Scenario]:
    dirs = sorted(p for p in root.iterdir() if (p / "repo.yaml").is_file())
    if only:
        dirs = [p for p in dirs if any(p.name.startswith(o) for o in only)]
    return [load(p) for p in dirs]


# ---------------------------------------------------------------------------------------------- building
def _git(repo: Path, *args: str, email: str | None = None) -> str:
    who = email or "owner@example.test"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": who.split("@")[0],
        "GIT_AUTHOR_EMAIL": who,
        "GIT_COMMITTER_NAME": who.split("@")[0],
        "GIT_COMMITTER_EMAIL": who,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    res = subprocess.run(["git", "-C", str(repo), *args], env=env, capture_output=True, text=True)  # noqa: S603, S607
    if res.returncode != 0:
        raise ScenarioError(f"git {' '.join(args[:2])}: {res.stderr.strip()[:300]}")
    return res.stdout


def _write(repo: Path, files: dict[str, str | None]) -> None:
    for rel, content in files.items():
        target = (repo / rel).resolve()
        if repo.resolve() not in target.parents:
            raise ScenarioError(f"path outside the repository: {rel}")
        if content is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)


def build_repo(sc: Scenario, workdir: Path) -> Path:
    """Replay the scenario's git operations into ``workdir/repo``. Returns the repository path."""
    repo = workdir / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "root")  # so `main` exists before the first operation
    emails = sc.authors
    for op in sc.operations:
        kind = op["op"]
        if kind == "commit":
            _git(repo, "checkout", "-q", op.get("branch", "main"))
            _write(repo, op["files"])
            _git(repo, "add", "-A")
            _git(
                repo,
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                op.get("message", "change"),
                email=emails[op["author"]],
            )
        elif kind == "branch":
            _git(repo, "checkout", "-q", "-b", op["name"], op.get("from", "main"))
        elif kind == "rebase":
            _git(repo, "checkout", "-q", op["branch"])
            # The rebase is the author's own: their commits keep their authorship (git keeps the author field).
            _git(repo, "rebase", "-q", op["onto"], email=emails[op.get("author", "base")])
        elif kind == "squash":
            _git(repo, "checkout", "-q", "-b", op["into"], op.get("base", "main"))
            _git(repo, "merge", "--squash", "-q", op["from"])
            _git(repo, "commit", "-q", "-m", op.get("message", "squashed"), email=emails[op["author"]])
        elif kind == "cherry_pick":
            _git(repo, "checkout", "-q", op["branch"])
            commits = _git(repo, "rev-list", "--reverse", f"{op['since']}..{op['from']}").split()
            _git(repo, "cherry-pick", *commits, email=emails[op.get("author", "base")])
    return repo
