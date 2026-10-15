"""Added lines of a local branch range, credited the way the PR check credits them (T096; research R11).

- Added lines come from `git diff -M --unified=0 <merge-base> <head>`, parsed by the same code as the PR check.
- Each added line is credited through `git blame --porcelain <head>`: a line whose blame commit is in
  `<merge-base>..<head>` goes to that commit's author, anything else is unmapped (not observed, FR-015).
- An author's GitHub account id comes from a GitHub no-reply address (`<id>+<login>@users.noreply.github.com`) or
  from an explicit ``authors`` map (email -> id). GitHub links commits by email the same way.

Everything is held in memory; nothing is written to disk.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field

from .diff import ExclusionRules, added_from_patch
from .types import AddedLine

__all__ = ["MAX_ADDED_LINES", "GitError", "LocalChange", "read_change"]

MAX_ADDED_LINES = 5_000  # per file, as in the PR check
_NOREPLY = re.compile(r"^(\d+)\+[^@]+@users\.noreply\.github\.com$", re.IGNORECASE)
_BLAME_HEADER = re.compile(r"^([0-9a-f]{40}) \d+ (\d+)(?: \d+)?$")


class GitError(RuntimeError):
    pass


@dataclass
class LocalChange:
    merge_base: str
    head: str
    lines: list[AddedLine] = field(default_factory=list)
    excluded: list[dict[str, str]] = field(default_factory=list)


def _git(repo: str, *args: str) -> str:
    res = subprocess.run(["git", "-C", repo, *args], capture_output=True, check=False)  # noqa: S603, S607
    if res.returncode != 0:
        raise GitError(f"git {args[0]} failed: {res.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return res.stdout.decode("utf-8", "replace")


def github_id_for(email: str, authors: Mapping[str, int]) -> int | None:
    if email.lower() in authors:
        return authors[email.lower()]
    m = _NOREPLY.match(email)
    return int(m.group(1)) if m else None


def _path(raw: str, prefix: str = "") -> str:
    """A path from a diff header: git appends a tab to names with spaces, and C-quotes unusual names."""
    raw = raw.rstrip("\t")
    if raw.startswith('"') and raw.endswith('"'):
        raw = (
            raw[1:-1]
            .encode("latin-1", "backslashreplace")
            .decode("unicode_escape")
            .encode("latin-1")
            .decode("utf-8")
        )
    return raw[len(prefix) :] if prefix and raw.startswith(prefix) else raw


def _files(diff: str) -> list[tuple[str | None, str | None, bool, str]]:
    """(old path, new path, binary, patch text) per file section of a `git diff` (paths None for /dev/null)."""
    out: list[tuple[str | None, str | None, bool, str]] = []
    for section in re.split(r"^diff --git ", diff, flags=re.MULTILINE)[1:]:
        head, _, rest = section.partition("\n@@")
        old = new = None
        binary = False
        for ln in head.splitlines():
            if ln.startswith("--- "):
                old = None if ln[4:] == "/dev/null" else _path(ln[4:], "a/")
            elif ln.startswith("+++ "):
                new = None if ln[4:] == "/dev/null" else _path(ln[4:], "b/")
            elif ln.startswith("rename from "):
                old = _path(ln[len("rename from ") :])
            elif ln.startswith("rename to "):
                new = _path(ln[len("rename to ") :])
            elif ln.startswith("Binary files "):
                binary = True
        if new is None and old is None and not binary:
            # A pure rename or mode change has no ---/+++ lines; the header names both paths.
            m = re.match(r"a/(.+) b/(.+)$", head.splitlines()[0])
            if m:
                old, new = m.group(1), m.group(2)
        patch = "@@" + rest if rest else ""
        out.append((old, new, binary, patch))
    return out


def _blame(repo: str, head: str, path: str) -> dict[int, str]:
    by_line: dict[int, str] = {}
    for ln in _git(repo, "blame", "--porcelain", head, "--", path).splitlines():
        m = _BLAME_HEADER.match(ln)
        if m:
            by_line[int(m.group(2))] = m.group(1)
    return by_line


def read_change(
    repo: str,
    base: str,
    head: str,
    *,
    rules: ExclusionRules | None = None,
    authors: Mapping[str, int] | None = None,
) -> LocalChange:
    authors = {k.lower(): v for k, v in (authors or {}).items()}
    head_sha = _git(repo, "rev-parse", "--verify", f"{head}^{{commit}}").strip()
    merge_base = _git(repo, "merge-base", base, head_sha).strip()
    commit_author = {}
    for row in _git(repo, "log", "--format=%H%x00%ae", f"{merge_base}..{head_sha}").splitlines():
        sha, _, email = row.partition("\x00")
        commit_author[sha] = github_id_for(email, authors)
    change = LocalChange(merge_base, head_sha)
    diff = _git(
        repo, "-c", "core.quotepath=false", "diff", "-M", "--unified=0", "--no-color", "--no-ext-diff",
        merge_base, head_sha,
    )  # fmt: skip
    for _old, new, binary, patch in _files(diff):
        if new is None:
            continue  # removed
        if rules is not None and rules.match(new):
            change.excluded.append({"path": new, "reason": "rule"})  # never read (FR-021)
            continue
        if binary:
            change.excluded.append({"path": new, "reason": "binary"})
            continue
        added = added_from_patch(patch)
        if not added:
            continue
        if len(added) > MAX_ADDED_LINES:
            change.excluded.append({"path": new, "reason": "too_large"})
            continue
        blame = _blame(repo, head_sha, new)
        for line_no, text in added:
            blamed = blame.get(line_no)
            gid = commit_author.get(blamed) if blamed else None
            change.lines.append(AddedLine(new, line_no, text, gid))
    return change
