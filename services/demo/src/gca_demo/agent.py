"""`gca demo run` and `gca demo init-repo` (T058; quickstart.md section 1).

`run` plays the scripted sessions through the gateway with your personal credential, applies the tool calls it
gets back, adds the scripted human edits, formats the Python files, then commits as your `gh` account and opens
a PR. All code involved is synthetic demo content.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable
from importlib import resources
from pathlib import Path
from typing import Any

import httpx

from gcattr import CapturedToolOutput, CaptureFailure, parse_stream

from .sessions import Session, marker, sessions

__all__ = ["apply_human_edit", "apply_output", "play", "register"]

Sender = Callable[[str, str], bytes]  # (api_format, marker text) -> response body

MODELS = {
    "anthropic_messages": "demo-anthropic",
    "openai_chat": "demo-openai",
    "openai_responses": "demo-openai",
    "gemini_native": "demo-gemini",
}
WORKSPACE = "/workspace/"


class DemoError(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------------- talking to the gateway
def gateway_sender(base_url: str, credential: str, gateway: str) -> Sender:
    base = base_url.rstrip("/")
    client = httpx.Client(timeout=120)

    def send(api_format: str, text: str) -> bytes:
        ua = {"User-Agent": f"gca-demo/0.1 ({api_format})"}
        if api_format == "anthropic_messages":
            url = f"{base}/v1/messages"
            headers = {**ua, "x-api-key": credential, "anthropic-version": "2023-06-01"}
            body: dict[str, Any] = {
                "model": MODELS[api_format],
                "max_tokens": 4096,
                "stream": True,
                "messages": [{"role": "user", "content": text}],
            }
        elif api_format == "openai_chat":
            url = f"{base}/v1/chat/completions"
            headers = {**ua, "Authorization": f"Bearer {credential}"}
            body = {
                "model": MODELS[api_format],
                "stream": True,
                "messages": [{"role": "user", "content": text}],
            }
        elif api_format == "openai_responses":
            url = f"{base}/v1/responses"
            headers = {**ua, "Authorization": f"Bearer {credential}"}
            body = {"model": MODELS[api_format], "stream": True, "input": text}
        else:
            # Both gateways serve Gemini's native route (LiteLLM through its router, research R3).
            url = f"{base}/v1beta/models/{MODELS[api_format]}:streamGenerateContent?alt=sse"
            headers = {**ua, "x-goog-api-key": credential}
            body = {"contents": [{"role": "user", "parts": [{"text": text}]}]}
        resp = client.post(url, json=body, headers=headers)
        if resp.status_code != 200:
            raise DemoError(f"{api_format}: the gateway answered HTTP {resp.status_code} for {url}")
        return resp.content

    return send


# ---------------------------------------------------------------------------------------------- applying edits
def _repo_path(repo: Path, path: str) -> Path:
    rel = path[len(WORKSPACE) :] if path.startswith(WORKSPACE) else path.lstrip("/")
    target = (repo / rel).resolve()
    if repo.resolve() not in target.parents:
        raise DemoError(f"refusing to write outside the repository: {path}")
    return target


def _replace(target: Path, old: str, new: str) -> None:
    text = target.read_text()
    if old not in text:
        raise DemoError(f"edit target not found in {target.name}")
    target.write_text(text.replace(old, new, 1))


def _apply_patch(repo: Path, patch: str) -> None:
    current: Path | None = None
    adding = False
    old: list[str] = []
    new: list[str] = []

    def flush() -> None:
        nonlocal old, new
        if current is not None and not adding and (old or new):
            _replace(current, "\n".join(old) + "\n", "\n".join(new) + "\n")
        old, new = [], []

    for line in patch.splitlines():
        if line.startswith(("*** Begin Patch", "*** End Patch")):
            flush()
        elif line.startswith("*** Add File: "):
            flush()
            current, adding = _repo_path(repo, line[len("*** Add File: ") :]), True
            current.parent.mkdir(parents=True, exist_ok=True)
            current.write_text("")
        elif line.startswith("*** Update File: "):
            flush()
            current, adding = _repo_path(repo, line[len("*** Update File: ") :]), False
        elif line.startswith("@@"):
            flush()
        elif current is not None and adding and line.startswith("+"):
            with current.open("a") as fh:
                fh.write(line[1:] + "\n")
        elif current is not None and not adding:
            if line.startswith("-"):
                old.append(line[1:])
            elif line.startswith("+"):
                new.append(line[1:])
            elif line.startswith(" "):
                old.append(line[1:])
                new.append(line[1:])


def apply_output(repo: Path, out: CapturedToolOutput) -> None:
    if out.kind == "text_block":
        return
    if out.kind == "freeform":
        _apply_patch(repo, str(out.payload))
        return
    args = out.payload if isinstance(out.payload, dict) else json.loads(out.payload)
    path = args.get("file_path") or args.get("path") or args.get("filename")
    if not isinstance(path, str):
        raise DemoError(f"tool call {out.tool_name} names no file")
    target = _repo_path(repo, path)
    if "content" in args:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(args["content"]))
    else:
        _replace(target, str(args["old_string"]), str(args["new_string"]))


def apply_human_edit(repo: Path, edit: dict[str, Any]) -> None:
    target = _repo_path(repo, edit["file"])
    if "write" in edit:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(edit["write"])
    elif "append" in edit:
        with target.open("a") as fh:
            fh.write(edit["append"])
    else:
        _replace(target, edit["replace"]["old"], edit["replace"]["new"])


def play(repo: Path, chosen: Iterable[Session], send: Sender) -> list[CapturedToolOutput]:
    """Run every step through ``send``, apply what comes back, then the human edits. Returns the AI outputs."""
    outputs: list[CapturedToolOutput] = []
    for session in chosen:
        for i, step in enumerate(session.steps):
            data = send(step.format, marker(session.name, i))
            results = list(parse_stream(step.format, [data]))  # type: ignore[arg-type]
            failures = [r for r in results if isinstance(r, CaptureFailure)]
            if failures:
                raise DemoError(f"{session.name} step {i}: response could not be read ({failures[0].cause})")
            for out in results:
                assert isinstance(out, CapturedToolOutput)
                apply_output(repo, out)
                outputs.append(out)
            print(f"  {session.name} step {i}: {step.format} -> {step.file}")
        for edit in session.human_edits:
            apply_human_edit(repo, edit)
    return outputs


def format_python(repo: Path) -> None:
    ruff = shutil.which("ruff")
    args = ["format", "--no-cache", "."]  # no cache dir, so nothing extra gets committed
    cmd = [ruff, *args] if ruff else [os.environ.get("PYTHON", "python3"), "-m", "ruff", *args]
    result = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)  # noqa: S603
    if result.returncode != 0:
        print("  warning: ruff is not available; skipping the formatter pass")


# ---------------------------------------------------------------------------------------------- git and gh
def _run(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)  # noqa: S603
    if result.returncode != 0:
        raise DemoError(f"{' '.join(cmd[:3])} failed: {result.stderr.strip()[:500]}")
    return result.stdout.strip()


def _gh_identity() -> tuple[str, str]:
    for tool in ("gh", "git"):
        if shutil.which(tool) is None:
            raise DemoError(f"`{tool}` is required")
    user = json.loads(_run(["gh", "api", "user"]))
    login, uid = user["login"], user["id"]
    # The noreply address links the commit to the account, which is how the PR check credits lines (FR-012).
    return login, f"{uid}+{login}@users.noreply.github.com"


def _commit(repo: Path, message: str, login: str, email: str) -> None:
    _run(["git", "add", "-A"], repo)
    _run(
        ["git", "-c", f"user.name={login}", "-c", f"user.email={email}", "commit", "-q", "-m", message], repo
    )


def _cmd_run(args: argparse.Namespace) -> int:
    credential = args.credential or os.environ.get("GCA_CREDENTIAL")
    if not credential:
        raise SystemExit("set GCA_CREDENTIAL (from the portal's Get gateway credential) or pass --credential")
    all_sessions = sessions()
    chosen = [all_sessions[n] for n in (args.sessions or sorted(all_sessions))]
    login, email = _gh_identity()
    with tempfile.TemporaryDirectory(prefix="gca-demo-") as tmp:
        repo = Path(tmp) / "repo"
        _run(["gh", "repo", "clone", args.repo, str(repo), "--", "-q"])
        branch = f"gca-demo-{time.strftime('%Y%m%d-%H%M%S')}"
        _run(["git", "checkout", "-q", "-b", branch], repo)
        print(f"Playing {len(chosen)} sessions through {args.gateway_url} ...")
        play(repo, chosen, gateway_sender(args.gateway_url, credential, args.gateway))
        format_python(repo)
        _commit(repo, "Demo: discount pricing, inventory and receipts", login, email)
        _run(["git", "push", "-q", "-u", "origin", branch], repo)
        body = (
            "Opened by `gca demo run`. The code came from scripted demo sessions sent through the AI gateway, "
            "plus a few human edits. Watch the **AI code attribution** check."
        )
        url = _run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                args.repo,
                "--head",
                branch,
                "--title",
                "Demo: discount pricing, inventory and receipts",
                "--body",
                body,
            ],
            repo,
        )
    print(f"Opened {url}")
    print("The AI code attribution check appears on the PR within about 2 minutes.")
    return 0


def sample_repo_dir() -> Path:
    packaged = resources.files("gca_demo").joinpath("sample_repo")
    if packaged.is_dir():
        return Path(str(packaged))
    source = Path(__file__).resolve().parents[2] / "sample-repo"  # running from the source tree
    if source.is_dir():
        return source
    raise DemoError("sample repository template not found")


def _cmd_init_repo(args: argparse.Namespace) -> int:
    login, email = _gh_identity()
    exists = subprocess.run(["gh", "repo", "view", args.repo], capture_output=True).returncode == 0  # noqa: S603, S607
    if not exists:
        _run(
            ["gh", "repo", "create", args.repo, "--private", "--description", "Gateway Code Attribution demo"]
        )
        print(f"Created private repository {args.repo}")
    with tempfile.TemporaryDirectory(prefix="gca-init-") as tmp:
        repo = Path(tmp) / "repo"
        _run(["gh", "repo", "clone", args.repo, str(repo), "--", "-q"])
        empty = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True).returncode != 0  # noqa: S607
        if empty:
            _run(["git", "checkout", "-q", "-b", "main"], repo)
        ignore = shutil.ignore_patterns("__pycache__", ".*_cache")
        shutil.copytree(sample_repo_dir(), repo, dirs_exist_ok=True, ignore=ignore)
        if not _run(["git", "status", "--porcelain"], repo):
            print(f"{args.repo} already has the sample project")
            return 0
        _commit(repo, "Add the gca sample project", login, email)
        _run(["git", "push", "-q", "-u", "origin", "HEAD:main"], repo)
    print(f"Pushed the sample project to {args.repo} (main). Install the GitHub App on it next.")
    return 0


def register(sub: Any) -> None:
    demo = sub.add_parser("demo", help="demo helpers")
    demo_sub = demo.add_subparsers(dest="demo_command", required=True)
    p = demo_sub.add_parser("run", help="play the demo sessions through the gateway and open a PR")
    p.add_argument("--repo", required=True, help="OWNER/NAME of the sample repository")
    p.add_argument("--gateway-url", default="http://localhost:4000")
    p.add_argument("--gateway", choices=["agentgateway", "litellm"], default="agentgateway")
    p.add_argument("--credential", default=None, help="personal gateway key (default: $GCA_CREDENTIAL)")
    p.add_argument("--sessions", nargs="*", help="session names (default: all)")
    p.set_defaults(func=lambda a: _guard(_cmd_run, a))
    i = demo_sub.add_parser("init-repo", help="create the sample repository and push the sample project")
    i.add_argument("--repo", required=True, help="OWNER/NAME")
    i.set_defaults(func=lambda a: _guard(_cmd_init_repo, a))


def _guard(fn: Callable[[argparse.Namespace], int], args: argparse.Namespace) -> int:
    try:
        return fn(args)
    except DemoError as exc:
        print(f"error: {exc}")
        return 1
