"""Authoring scenarios (T101-T105). Scenarios are written as labelled source files; this module derives from them
the model's output streams, the committed repository and the expected outcome of every line. The labels come from
how a scenario was written (what the model wrote, what a person typed or edited), never from the algorithm.

    doc = Doc("src/cart.py")
    doc.ai("def subtotal(items):", "    return sum(i.price * i.qty for i in items)")
    doc.edit("    tax = 0.08", "    tax = 0.0825", tier="anchored")   # the model wrote the first, a person the second
    doc.human("    log.debug('subtotal computed')")

Trivial lines (too short, no identifier or literal, or common boilerplate; research R10) are expected to be
indeterminate whoever wrote them, which is how the spec defines them.

Formatter passes run here, at authoring time, at the versions pinned in eval/harness/formatters.lock, so running
the eval never needs the formatters installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from gca_demo.sessions import ToolCall, fault_call
from gca_demo.streams import render, render_fault
from gcattr import ALG
from gcattr.lexer import tokenize
from gcattr.normalize import normalize_line
from gcattr.trivial import is_trivial

__all__ = ["FORMATTERS", "Builder", "Doc", "format_source", "token_key"]

LOCK = Path(__file__).resolve().parents[2] / "formatters.lock"
WORKSPACE = "/workspace/"


def token_key(text: str) -> str:
    return " ".join(t.text for t in tokenize(normalize_line(text, ALG)))


def trivial(text: str) -> bool:
    return is_trivial(tokenize(normalize_line(text, ALG)), ALG)


@dataclass
class _Line:
    kind: str  # ai | edit | human | dropped (written by the model, deleted before committing)
    text: str  # as committed (for dropped: as the model wrote it)
    original: str | None = None  # edit: what the model wrote
    tier: str | None = None  # edit: anchored | broad | any
    tags: tuple[str, ...] = ()


@dataclass
class Doc:
    """One file, written line by line with who wrote each line."""

    path: str
    lines: list[_Line] = field(default_factory=list)

    def ai(self, *texts: str, tags: tuple[str, ...] = ()) -> Doc:
        self.lines += [_Line("ai", t, tags=tags) for t in texts]
        return self

    def edit(self, original: str, new: str, *, tier: str = "any", tags: tuple[str, ...] = ()) -> Doc:
        self.lines.append(_Line("edit", new, original, tier, tags))
        return self

    def human(self, *texts: str, tags: tuple[str, ...] = ()) -> Doc:
        self.lines += [_Line("human", t, tags=tags) for t in texts]
        return self

    def dropped(self, *texts: str) -> Doc:
        self.lines += [_Line("dropped", t) for t in texts]
        return self

    def model_text(self) -> str:
        """What the model wrote."""
        return "".join(
            (ln.original if ln.kind == "edit" else ln.text) + "\n"
            for ln in self.lines
            if ln.kind in ("ai", "edit", "dropped")
        )

    def final_text(self) -> str:
        """What was committed."""
        return "".join(ln.text + "\n" for ln in self.lines if ln.kind != "dropped")

    def expected(self, extra_tags: tuple[str, ...] = ()) -> dict[int, dict[str, Any]]:
        out: dict[int, dict[str, Any]] = {}
        n = 0
        for ln in self.lines:
            if ln.kind == "dropped":
                continue
            n += 1
            tags = list(dict.fromkeys(ln.tags + extra_tags))
            if trivial(ln.text):
                out[n] = {"outcome": "indeterminate", "tags": tags}
            elif ln.kind == "ai":
                out[n] = {"outcome": "ai_unmodified", "tags": tags}
            elif ln.kind == "edit":
                out[n] = {"outcome": "ai_modified", "tier": ln.tier, "tags": tags}
            else:
                out[n] = {"outcome": "human", "tags": tags}
        return out


# ---------------------------------------------------------------------------------------------- formatters
def _lock() -> dict[str, Any]:
    return yaml.safe_load(LOCK.read_text())["formatters"]


FORMATTERS = ("black", "prettier", "gofmt")


def format_source(formatter: str, path: str, text: str) -> str:
    """Run a pinned formatter over ``text`` (stdin to stdout)."""
    pin = _lock()[formatter]
    if formatter == "black":
        cmd = ["uv", "run", "--quiet", "--with", f"black=={pin['version']}", "black", "-q", "-"]
    elif formatter == "prettier":
        cmd = ["docker", "run", "--rm", "-i", pin["image"], "npx", "-y", f"prettier@{pin['version']}",
               "--stdin-filepath", path]  # fmt: skip
    else:
        cmd = ["docker", "run", "--rm", "-i", pin["image"], "gofmt"]
    if shutil.which(cmd[0]) is None:
        raise RuntimeError(f"{cmd[0]} is needed to author {formatter} scenarios")
    res = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=600)  # noqa: S603
    if res.returncode != 0:
        raise RuntimeError(f"{formatter} failed: {res.stderr[-500:]}")
    return res.stdout


def formatted_doc(path: str, model_text: str, formatter: str) -> tuple[Doc, dict[str, Any]]:
    """A file the model wrote and a formatter then reformatted. A committed line whose tokens equal a model line
    is unmodified (whitespace isn't a change); any other non-trivial line is AI modified by the formatter."""
    final = format_source(formatter, path, model_text)
    written = {token_key(ln) for ln in model_text.splitlines()}
    doc = Doc(path)
    for ln in final.splitlines():
        if token_key(ln) in written or trivial(ln):
            doc.ai(ln)
        else:
            # The model wrote this code; only the formatter changed it. Which tier finds it depends on the change.
            doc.lines.append(_Line("edit", ln, ln, "any", ("formatter",)))
    doc_model = model_text
    return doc, {"formatter": formatter, "model_text_lines": len(doc_model.splitlines())}


# ---------------------------------------------------------------------------------------------- tool calls
def write_call(doc: Doc | str, api_format: str, n: int, content: str | None = None) -> ToolCall:
    """The tool call a coding tool would make to write ``doc`` as the model wrote it."""
    path = doc if isinstance(doc, str) else doc.path
    text = content if content is not None else (doc.model_text() if isinstance(doc, Doc) else "")
    if api_format == "anthropic_messages":  # Claude Code's Write tool
        return ToolCall(f"toolu_{n:03d}", "Write", {"file_path": WORKSPACE + path, "content": text})
    if api_format == "gemini_native":  # Gemini CLI
        return ToolCall(f"g_{n:03d}", "write_file", {"file_path": WORKSPACE + path, "content": text})
    return ToolCall(
        f"call_{n:03d}", "write_file", {"path": path, "content": text}
    )  # Chat Completions, Responses


def patch_call(doc: Doc, n: int) -> ToolCall:
    """Codex's freeform apply_patch, adding the whole file (OpenAI Responses)."""
    body = "".join("+" + ln + "\n" for ln in doc.model_text().splitlines())
    patch = f"*** Begin Patch\n*** Add File: {doc.path}\n{body}*** End Patch\n"
    return ToolCall(f"call_{n:03d}", "apply_patch", None, patch)


# ---------------------------------------------------------------------------------------------- scenarios
class Builder:
    """Collects one scenario and writes its directory."""

    def __init__(self, name: str, category: str, description: str) -> None:
        self.name, self.category, self.description = name, category, description
        self.authors: dict[str, str] = {"base": "owner@example.test"}
        self.unmapped: list[str] = []
        self.streams: list[dict[str, Any]] = []
        self.stream_data: dict[str, bytes] = {}
        self.operations: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self.expected: dict[str, dict[str, Any]] = {}
        self.loss: dict[str, int] = {}
        self.attributable = True
        self.pr = {"base": "main", "head": "feature"}
        self._n = 0

    def author(self, alias: str, *, unmapped: bool = False) -> str:
        self.authors[alias] = f"{alias}@example.test"
        if unmapped:
            self.unmapped.append(alias)
        return alias

    def stream(
        self,
        author: str,
        api_format: str,
        calls: list[ToolCall],
        *,
        key_gen: int = 1,
        fault: str | None = None,
    ) -> None:
        self._n += 1
        name = f"{self._n:02d}-{author}-{api_format}.sse"
        if fault in ("truncated", "unexpected_format"):
            data = render_fault(fault, calls[0] if calls else fault_call(self._n))[1]
        else:
            data = render(api_format, calls, stream=True)[1]
        self.stream_data[name] = data
        entry: dict[str, Any] = {"file": name, "author": author, "api_format": api_format}
        if key_gen != 1:
            entry["key_gen"] = key_gen
        if fault:
            entry["fault"] = fault
        self.streams.append(entry)

    def recorded(self, author: str, api_format: str, data: bytes) -> None:
        """A response recorded from a real tool (eval/corpus), sent byte for byte as recorded."""
        self._n += 1
        name = f"{self._n:02d}-{author}-{api_format}.sse"
        self.stream_data[name] = data
        self.streams.append({"file": name, "author": author, "api_format": api_format})

    def write_docs(self, author: str, api_format: str, docs: list[Doc], **kw: Any) -> None:
        """One response in which the model writes each document with one tool call."""
        self.stream(author, api_format, [write_call(d, api_format, i + 1) for i, d in enumerate(docs)], **kw)

    def commit(
        self, author: str, files: dict[str, str | None], *, branch: str = "feature", message: str = ""
    ) -> None:
        self.operations.append(
            {
                "op": "commit",
                "branch": branch,
                "author": author,
                "message": message or f"{author}: change",
                "files": files,
            }
        )

    def branch(self, name: str, base: str = "main") -> None:
        self.operations.append({"op": "branch", "name": name, "from": base})

    def op(self, **op: Any) -> None:
        self.operations.append(op)

    def expect(self, doc: Doc, *, tags: tuple[str, ...] = (), unmapped: bool = False) -> None:
        for line_no, e in doc.expected(tags).items():
            if unmapped:
                e = {"outcome": "not_observed", "tags": e.get("tags", [])}
            self.expected[f"{doc.path}:{line_no}"] = e

    def note(self, **edit: Any) -> None:
        self.edits.append(edit)

    def write(self, root: Path) -> Path:
        d = root / self.name
        if d.exists():
            shutil.rmtree(d)
        (d / "streams").mkdir(parents=True)
        for name, data in self.stream_data.items():
            (d / "streams" / name).write_bytes(data)
        repo = {
            "description": self.description,
            "category": self.category,
            "authors": self.authors,
            "unmapped": self.unmapped,
            "streams": self.streams,
            "operations": self.operations,
            "pr": self.pr,
        }
        (d / "repo.yaml").write_text(yaml.safe_dump(repo, sort_keys=False, allow_unicode=True, width=120))
        (d / "edits.yaml").write_text(
            yaml.safe_dump({"edits": self.edits}, sort_keys=False, allow_unicode=True)
        )
        exp = {
            "lines": dict(sorted(self.expected.items())),
            "loss": self.loss,
            "attributable": self.attributable,
        }
        (d / "expected.json").write_text(json.dumps(exp, indent=1, ensure_ascii=False) + "\n")
        return d
