"""Needles and scanning for the privacy audit (T064; SC-006; Constitution II).

A needle is one line of demo code, AI-written or human-written, or one line of the sample repository: whitespace
trimmed, at least 12 characters. Lines that also occur anywhere in this project's own source (code, chart,
defaults such as the exclusion rules) are left out, because a match on them would prove nothing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from gca_demo import agent, model
from gca_demo.sessions import demo_sessions, sessions

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_REPO = ROOT / "services/demo/sample-repo"
MIN_LEN = 12
OWN_SOURCE = [ROOT / "lib/src", ROOT / "services", ROOT / "charts"]
TEXT_SUFFIXES = {".py", ".yaml", ".yml", ".tpl", ".json", ".html", ".toml", ".md", ".ts", ".txt"}


def _own_source() -> str:
    parts: list[str] = []
    for root in OWN_SOURCE:
        for p in root.rglob("*"):
            if (
                p.is_file()
                and p.suffix in TEXT_SUFFIXES
                and SAMPLE_REPO not in p.parents
                and "sessions" not in p.parts
            ):
                parts.append(p.read_text(errors="replace"))
    return "\n".join(parts)


def _demo_texts() -> list[str]:
    texts: list[str] = []
    for s in sessions().values():
        for step in s.steps:
            texts += [t for t in (step.write, step.edit_old, step.edit_new) if t]
        for edit in s.human_edits:
            texts += [v for k, v in edit.items() if k in ("write", "append") and isinstance(v, str)]
            if "replace" in edit:
                texts += [edit["replace"]["old"], edit["replace"]["new"]]
    for p in SAMPLE_REPO.rglob("*"):
        if p.is_file() and p.suffix in TEXT_SUFFIXES | {""}:
            texts.append(p.read_text(errors="replace"))
    return texts + _files_as_pushed()


def _files_as_pushed() -> list[str]:
    """Replay the demo offline (sessions, human edits, formatter) to get every line as it lands in the PR.
    Human edits create lines that appear in no session script on their own."""

    def send(api_format: str, text: str) -> bytes:
        path = (
            "/v1beta/models/demo-gemini:streamGenerateContent" if api_format == "gemini_native" else "/v1/x"
        )
        body = json.dumps({"stream": True, "messages": [{"role": "user", "content": text}], "input": text})
        return model.respond(api_format, path, body)[1]

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        shutil.copytree(SAMPLE_REPO, repo, ignore=shutil.ignore_patterns("__pycache__", ".*_cache"))
        agent.play(repo, demo_sessions().values(), send)
        agent.format_python(repo)
        return [p.read_text(errors="replace") for p in repo.rglob("*") if p.is_file()]


@cache
def needles() -> list[str]:
    own = _own_source()
    found = {ln.strip() for text in _demo_texts() for ln in text.splitlines()}
    return sorted(n for n in found if len(n) >= MIN_LEN and n not in own)


def variants(needle: str) -> list[bytes]:
    """The forms a leaked line would take: raw, JSON-escaped (logs, jsonb), hex (pg_dump of bytea)."""
    raw = needle.encode("utf-8")
    escaped = json.dumps(needle)[1:-1].encode("utf-8")
    return list(dict.fromkeys([raw, escaped, raw.hex().encode()]))


def find(blob: bytes, needle_list: list[str]) -> list[str]:
    return [n for n in needle_list if any(v in blob for v in variants(n))]


@dataclass
class Cluster:
    context: str
    namespace: str
    release: str

    def kubectl(self, *args: str, stdin: bytes | None = None, check: bool = True) -> bytes:
        cmd = ["kubectl", "--context", self.context, "-n", self.namespace, *args]
        res = subprocess.run(cmd, input=stdin, capture_output=True, timeout=300)
        if check and res.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd[:6])} failed: {res.stderr.decode(errors='replace')[:300]}")
        return res.stdout

    @property
    def fullname(self) -> str:
        return f"{self.release}-gca"

    def psql(self, sql: str) -> str:
        return self.kubectl(
            "exec", f"{self.fullname}-postgres-0", "--", "psql", "-U", "gca", "-d", "gca", "-Atc", sql
        ).decode()

    def pods(self) -> list[tuple[str, list[str]]]:
        data = json.loads(self.kubectl("get", "pods", "-o", "json"))
        return [(p["metadata"]["name"], [c["name"] for c in p["spec"]["containers"]]) for p in data["items"]]
