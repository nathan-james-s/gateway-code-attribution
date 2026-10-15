"""`gca demo scenarios` (T080; quickstart.md section 2; spec User Story 2 scenarios 1-9).

Opens one PR per edge case in the sample repository. Each PR carries an answer file, `.gca-expected.json`, with
the intended result for every line it adds:

- lines the AI wrote and nobody changed: `ai_unmodified`;
- lines declared in the scenario's `expect` (a renamed variable): `ai_modified` or `human`;
- lines too short or too common to attribute: `indeterminate` (the library's fixed rule; no key involved);
- lines committed by an account with no gateway credential: `not_observed`;
- everything else: `human`.

Scripted edits are chosen so their similarity sits far from any threshold, so the answers hold on any install.
A run report (``--report``) lists each PR, its heads and anything observed while it ran.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gcattr import CapturedToolOutput, CaptureFailure, parse_stream
from gcattr.algorithm import ALG
from gcattr.lexer import tokenize
from gcattr.normalize import normalize_line
from gcattr.trivial import is_trivial

from .agent import DemoError, Sender, _gh_identity, _run, apply_human_edit, apply_output, gateway_sender
from .sessions import Session, marker, sessions

__all__ = ["expected_labels", "register"]

UNMAPPED = ("Legacy Importer", "legacy-importer@example.invalid")  # an email linked to no GitHub account
WAITING_TITLE = "Waiting for capture to catch up"


def _trivial(line: str) -> bool:
    return is_trivial(tokenize(normalize_line(line, ALG)), ALG)


def expected_labels(
    files: dict[str, str], ai_lines: dict[str, set[str]], file_author: dict[str, str], expect: dict[str, Any]
) -> dict[str, dict[str, str]]:
    """Intended result for every added line, by path and line number."""
    modified = {s.strip() for s in expect.get("ai_modified", [])}
    human = {s.strip() for s in expect.get("human", [])}
    out: dict[str, dict[str, str]] = {}
    for path, content in files.items():
        labels: dict[str, str] = {}
        for no, line in enumerate(content.splitlines(), start=1):
            text = line.strip()
            if file_author.get(path) == "unmapped":
                label = "not_observed"
            elif _trivial(line):
                label = "indeterminate"
            elif text in modified:
                label = "ai_modified"
            elif text in human:
                label = "human"
            elif text in ai_lines.get(path, set()):
                label = "ai_unmodified"
            else:
                label = "human"
            labels[str(no)] = label
        out[path] = labels
    return out


class Runner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.repo_name = args.repo
        self.run_id = time.strftime("%Y%m%d-%H%M%S")
        self.first = _gh_identity()  # (login, noreply email)
        self.first_id = int(json.loads(_run(["gh", "api", "user"]))["id"])
        self.second: tuple[str, str] | None = None
        self.second_id: int | None = None
        if args.second_login:
            user = json.loads(_run(["gh", "api", f"users/{args.second_login}"]))
            self.second = (user["login"], f"{user['id']}+{user['login']}@users.noreply.github.com")
            self.second_id = int(user["id"])
        cred = args.credential or os.environ.get("GCA_CREDENTIAL")
        if not cred:
            raise DemoError("set GCA_CREDENTIAL or pass --credential")
        self.senders: dict[str, Sender] = {"first": gateway_sender(args.gateway_url, cred, args.gateway)}
        cred2 = args.credential_2 or os.environ.get("GCA_CREDENTIAL_2")
        if cred2:
            self.senders["second"] = gateway_sender(args.gateway_url, cred2, args.gateway)
        self.tmp = Path(tempfile.mkdtemp(prefix="gca-scenarios-"))
        self.repo = self.tmp / "repo"
        _run(["gh", "repo", "clone", self.repo_name, str(self.repo), "--", "-q"])
        self.report: list[dict[str, Any]] = []

    # ------------------------------------------------------------------------------------------ helpers
    def git(self, *args: str) -> str:
        return _run(["git", *args], self.repo)

    def commit(self, message: str, who: str, paths: list[str]) -> str:
        name, email = {"first": self.first, "second": self.second or self.first, "unmapped": UNMAPPED}[who]
        self.git("add", *paths)
        self.git("-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD").strip()

    def branch(self, name: str, start: str = "origin/main") -> None:
        self.git("checkout", "-q", "-B", name, start)
        self.git("clean", "-q", "-fdx")

    def ai(self, session: Session, i: int) -> tuple[str, set[str]]:
        """Send step i through the gateway with its author's credential; apply it. Returns (path, AI lines)."""
        step = session.steps[i]
        if step.author not in self.senders:
            raise DemoError(f"{session.name} needs a credential for its {step.author} author")
        data = self.senders[step.author](step.format, marker(session.name, i))
        results = list(parse_stream(step.format, [data]))  # type: ignore[arg-type]
        if any(isinstance(r, CaptureFailure) for r in results):
            raise DemoError(f"{session.name} step {i}: the response could not be read")
        for out in results:
            assert isinstance(out, CapturedToolOutput)
            apply_output(self.repo, out)
        text = step.write or step.edit_new or ""
        return step.file, {ln.strip() for ln in text.splitlines()}

    def write_expected(
        self,
        session: Session,
        ai_lines: dict[str, set[str]],
        file_author: dict[str, str],
        coverage: str,
        **extra: Any,
    ) -> str:
        files = {p: (self.repo / p).read_text() for p in file_author}
        expected = {
            "scenario": session.name,
            "description": session.description,
            "coverage": coverage,
            "files": expected_labels(files, ai_lines, file_author, session.expect),
            "credited": {
                p: {"first": self.first_id, "second": self.second_id, "unmapped": None}[a]
                for p, a in file_author.items()
            },
            **extra,
        }
        (self.repo / ".gca-expected.json").write_text(json.dumps(expected, indent=2) + "\n")
        return ".gca-expected.json"

    def open_pr(self, session: Session, branch: str, base: str = "main") -> dict[str, Any]:
        self.git("push", "-q", "-u", "origin", branch, "--force-with-lease")
        url = _run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                self.repo_name,
                "--base",
                base,
                "--head",
                branch,
                "--title",
                f"Scenario: {session.name}",
                "--body",
                f"{session.description}\n\nOpened by `gca demo scenarios`; the answer key is `.gca-expected.json`.",
            ],
            self.repo,
        ).strip()
        entry = {
            "scenario": session.name,
            "url": url,
            "pr": int(url.rsplit("/", 1)[1]),
            "branch": branch,
            "base": base,
            "heads": [self.git("rev-parse", "HEAD").strip()],
        }
        self.report.append(entry)
        print(f"  {session.name}: {url}")
        return entry

    def check_title(self, sha: str) -> tuple[str, str] | None:
        runs = json.loads(_run(["gh", "api", f"repos/{self.repo_name}/commits/{sha}/check-runs"]))[
            "check_runs"
        ]
        for cr in runs:
            if cr["name"] == "AI code attribution":
                return cr["status"], (cr.get("output") or {}).get("title") or ""
        return None

    def wait_check(
        self, sha: str, done: Callable[[str, str], bool], timeout: float
    ) -> tuple[str, str] | None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            state = self.check_title(sha)
            if state and done(*state):
                return state
            time.sleep(10)
        return None

    def kubectl_scale(self, replicas: int) -> None:
        _run(
            [
                "kubectl",
                "--context",
                self.args.kube_context,
                "-n",
                self.args.namespace,
                "scale",
                f"deployment/{self.args.release}-gca-ingest",
                f"--replicas={replicas}",
            ]
        )

    # ------------------------------------------------------------------------------------------ scenarios
    def simple(self, s: Session, coverage: str = "complete") -> dict[str, Any]:
        """AI steps then human edits, one commit per author; unmapped edits in their own commit."""
        b = f"gca-scn-{self.run_id}-{s.name.removeprefix('scn-')}"
        self.branch(b)
        ai_lines: dict[str, set[str]] = {}
        author: dict[str, str] = {}
        for i, step in enumerate(s.steps):
            path, lines = self.ai(s, i)
            ai_lines.setdefault(path, set()).update(lines)
            author[path] = step.author
        for edit in s.human_edits:
            apply_human_edit(self.repo, edit)
            author.setdefault(edit["file"], edit.get("author", "first"))
        expected = self.write_expected(s, ai_lines, author, coverage)
        for who in ("first", "second", "unmapped"):
            paths = [p for p, a in author.items() if a == who] + ([expected] if who == "first" else [])
            if paths:
                self.commit(f"{s.name}: {who} author", who, paths)
        return self.open_pr(s, b)

    def rewrite(self, s: Session) -> dict[str, Any]:
        base = f"gca-scn-{self.run_id}-rewrite-base"
        self.branch(base)
        self.git("push", "-q", "-u", "origin", base)
        b = f"gca-scn-{self.run_id}-rewrite"
        self.branch(b, base)
        ai_lines: dict[str, set[str]] = {}
        author: dict[str, str] = {}
        for i in range(len(s.steps)):  # one commit per AI step
            path, lines = self.ai(s, i)
            ai_lines[path], author[path] = lines, "first"
            self.commit(f"{s.name}: step {i}", "first", [path])
        expected = self.write_expected(s, ai_lines, author, "complete")
        self.commit(f"{s.name}: answer key", "first", [expected])
        entry = self.open_pr(s, b, base)
        # Move the base, then rebase onto it and squash everything into one new commit (FR-019).
        self.branch(base, base)
        (self.repo / "docs").mkdir(exist_ok=True)
        (self.repo / "docs/scenario-base-moved.md").write_text("The base branch moved after the PR opened.\n")
        self.commit("move the base branch", "first", ["docs/scenario-base-moved.md"])
        self.git("push", "-q", "origin", base)
        self.git("checkout", "-q", b)
        self.git("rebase", "-q", base)
        self.git("reset", "--soft", base)
        self.commit(f"{s.name}: squashed", "first", ["."])
        self.git("push", "-q", "--force-with-lease", "origin", b)
        entry["heads"].append(self.git("rev-parse", "HEAD").strip())
        return entry

    def cherry_pick(self, s: Session) -> dict[str, Any]:
        scratch = f"gca-scn-{self.run_id}-scratch"
        self.branch(scratch)
        path, lines = self.ai(s, 0)
        sha = self.commit(f"{s.name}: written on another branch", "first", [path])
        b = f"gca-scn-{self.run_id}-cherry-pick"
        self.branch(b)
        self.git("-c", f"user.name={self.first[0]}", "-c", f"user.email={self.first[1]}", "cherry-pick", sha)
        expected = self.write_expected(s, {path: lines}, {path: "first"}, "complete")
        self.commit(f"{s.name}: answer key", "first", [expected])
        return self.open_pr(s, b)

    def pending(self, s: Session) -> dict[str, Any]:
        self.kubectl_scale(0)  # ingest paused: captures queue up and the watermark stops moving
        try:
            entry = self.simple(s)
            seen = self.wait_check(entry["heads"][0], lambda st, title: title.startswith(WAITING_TITLE), 180)
            entry["waiting_seen"] = seen is not None
        finally:
            self.kubectl_scale(1)
        return entry

    def new_push(self, s: Session) -> dict[str, Any]:
        b = f"gca-scn-{self.run_id}-new-push"
        self.branch(b)
        first = [i for i, st in enumerate(s.steps) if st.push == "first"]
        second = [i for i, st in enumerate(s.steps) if st.push == "second"]
        ai_lines: dict[str, set[str]] = {}
        author: dict[str, str] = {}
        for i in first:
            path, lines = self.ai(s, i)
            ai_lines[path], author[path] = lines, "first"
        expected = self.write_expected(s, ai_lines, author, "complete", push=1)
        self.commit(f"{s.name}: first push", "first", [*author, expected])
        entry = self.open_pr(s, b)
        done = self.wait_check(entry["heads"][0], lambda st, title: st == "completed", 600)
        entry["first_head_completed"] = done is not None
        for i in second:
            path, lines = self.ai(s, i)
            ai_lines[path], author[path] = lines, "first"
        expected = self.write_expected(s, ai_lines, author, "complete", push=2)
        self.commit(f"{s.name}: second push", "first", [*author, expected])
        self.git("push", "-q", "origin", b)
        entry["heads"].append(self.git("rev-parse", "HEAD").strip())
        return entry


def _cmd_scenarios(args: argparse.Namespace) -> int:
    r = Runner(args)
    chosen = [
        n
        for n in sorted(s for s, v in sessions().items() if v.kind == "scenario")
        if not args.only or n.removeprefix("scn-") in args.only or n in args.only
    ]
    flows: dict[str, Callable[[Session], dict[str, Any]]] = {
        "scn-rewrite": r.rewrite,
        "scn-cherry-pick": r.cherry_pick,
        "scn-pending": r.pending,
        "scn-new-push": r.new_push,
        "scn-unmapped": lambda s: r.simple(s, "complete"),
    }
    print(f"Opening scenario PRs in {args.repo} (run {r.run_id}) ...")
    for name in chosen:
        s = sessions()[name]
        if name == "scn-two-authors" and not (r.second and "second" in r.senders):
            print(f"  {name}: skipped (needs --second-login and GCA_CREDENTIAL_2)")
            r.report.append({"scenario": name, "skipped": "needs a second mapped developer"})
            continue
        flows.get(name, r.simple)(s)
    out = {"repo": args.repo, "run": r.run_id, "gateway": args.gateway, "scenarios": r.report}
    Path(args.report).write_text(json.dumps(out, indent=2) + "\n")
    print(f"Wrote {args.report}. Check each PR's AI code attribution check against its .gca-expected.json.")
    return 0


def _scale(args: argparse.Namespace, replicas: int) -> int:
    _run(
        [
            "kubectl",
            "--context",
            args.kube_context,
            "-n",
            args.namespace,
            "scale",
            f"deployment/{args.release}-gca-ingest",
            f"--replicas={replicas}",
        ]
    )
    print("ingest paused" if replicas == 0 else "ingest resumed")
    return 0


def register(demo_sub: Any) -> None:
    from .agent import _guard

    def cluster_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--kube-context", default=os.environ.get("GCA_KUBE_CONTEXT", "kind-gca"))
        p.add_argument("--namespace", default="gca")
        p.add_argument("--release", default="gca")

    p = demo_sub.add_parser("scenarios", help="open one PR per edge case (quickstart section 2)")
    p.add_argument("--repo", required=True, help="OWNER/NAME of the sample repository")
    p.add_argument("--gateway-url", default="http://localhost:4000")
    p.add_argument("--gateway", choices=["agentgateway", "litellm"], default="agentgateway")
    p.add_argument("--credential", default=None, help="gateway key (default: $GCA_CREDENTIAL)")
    p.add_argument(
        "--second-login", default=None, help="a second developer's GitHub login (two-authors case)"
    )
    p.add_argument(
        "--credential-2", default=None, help="the second developer's key (default: $GCA_CREDENTIAL_2)"
    )
    p.add_argument("--only", nargs="*", help="scenario names, e.g. edited trivial")
    p.add_argument("--report", default="scenarios-report.json")
    cluster_args(p)
    p.set_defaults(func=lambda a: _guard(_cmd_scenarios, a))
    for name, replicas in (("pause-ingest", 0), ("resume-ingest", 1)):
        q = demo_sub.add_parser(name, help=f"scale ingest to {replicas} (the pending-capture case)")
        cluster_args(q)
        q.set_defaults(func=lambda a, n=replicas: _guard(lambda x: _scale(x, n), a))
