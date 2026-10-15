"""Scripted demo sessions (T056). All code in them is synthetic, written for the sample repository.

A session is a list of AI steps, each served in one API format with that format's tool idiom, plus the human
edits `gca demo run` applies afterwards. The demo agent marks each request with ``gca-demo session=<name>
step=<n>`` so demo-model knows which step to answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any

import yaml

__all__ = ["Session", "Step", "ToolCall", "demo_sessions", "marker", "parse_marker", "sessions", "tool_calls"]

API_FORMATS = ("anthropic_messages", "openai_chat", "openai_responses", "gemini_native")
_MARKER = re.compile(r"gca-demo session=([a-z0-9-]+) step=(\d+)")


@dataclass(frozen=True)
class Step:
    format: str
    file: str
    write: str | None = None
    edit_old: str | None = None
    edit_new: str | None = None
    author: str = "first"  # scenarios: which developer's credential sends it and whose commit holds it
    push: str = "first"  # scenarios: which push the file lands in


@dataclass(frozen=True)
class Session:
    name: str
    description: str
    steps: tuple[Step, ...]
    human_edits: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    kind: str = "demo"  # "demo" (gca demo run) or "scenario" (gca demo scenarios)
    expect: dict[str, Any] = field(default_factory=dict)  # scenario answer-key hints


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    args: dict[str, Any] | None = None  # JSON-argument tools
    freeform: str | None = None  # freeform tools (apply_patch)


def marker(session: str, step: int) -> str:
    return f"gca-demo session={session} step={step}"


def parse_marker(body: str) -> tuple[str, int] | None:
    m = _MARKER.search(body)
    return (m.group(1), int(m.group(2))) if m else None


def _step(d: dict[str, Any]) -> Step:
    if d["format"] not in API_FORMATS:
        raise ValueError(f"unknown format {d['format']!r}")
    edit = d.get("edit") or {}
    if bool(d.get("write") is not None) == bool(edit):
        raise ValueError(f"step for {d['file']} needs exactly one of write or edit")
    return Step(
        d["format"],
        d["file"],
        d.get("write"),
        edit.get("old"),
        edit.get("new"),
        d.get("author", "first"),
        d.get("push", "first"),
    )


@cache
def sessions() -> dict[str, Session]:
    out: dict[str, Session] = {}
    for entry in sorted(resources.files("gca_demo").joinpath("sessions").iterdir(), key=lambda p: p.name):
        if not entry.name.endswith(".yaml"):
            continue
        d = yaml.safe_load(entry.read_text("utf-8"))
        out[d["name"]] = Session(
            d["name"],
            d.get("description", ""),
            tuple(_step(s) for s in d.get("steps") or ()),
            tuple(d.get("human_edits") or ()),
            d.get("kind", "demo"),
            d.get("expect") or {},
        )
    return out


def demo_sessions() -> dict[str, Session]:
    """The sessions `gca demo run` plays (scenario sessions belong to `gca demo scenarios`)."""
    return {k: v for k, v in sessions().items() if v.kind == "demo"}


def _patch(step: Step) -> str:
    if step.write is not None:
        body = "".join(f"+{ln}\n" for ln in step.write.splitlines())
        return f"*** Begin Patch\n*** Add File: {step.file}\n{body}*** End Patch\n"
    old = "".join(f"-{ln}\n" for ln in (step.edit_old or "").splitlines())
    new = "".join(f"+{ln}\n" for ln in (step.edit_new or "").splitlines())
    return f"*** Begin Patch\n*** Update File: {step.file}\n@@\n{old}{new}*** End Patch\n"


def tool_calls(step: Step, call_id: str) -> list[ToolCall]:
    """The tool call a real coding tool would receive for this step, in the step's API format (research R6)."""
    if step.format == "openai_responses":  # Codex CLI: freeform apply_patch
        return [ToolCall(call_id, "apply_patch", freeform=_patch(step))]
    if step.format == "anthropic_messages":  # Claude Code
        path = f"/workspace/{step.file}"
        if step.write is not None:
            return [ToolCall(call_id, "Write", {"file_path": path, "content": step.write})]
        return [
            ToolCall(
                call_id, "Edit", {"file_path": path, "old_string": step.edit_old, "new_string": step.edit_new}
            )
        ]
    if step.format == "gemini_native":  # Gemini CLI
        if step.write is not None:
            return [ToolCall(call_id, "write_file", {"file_path": step.file, "content": step.write})]
        return [
            ToolCall(
                call_id,
                "replace",
                {"file_path": step.file, "old_string": step.edit_old, "new_string": step.edit_new},
            )
        ]
    # openai_chat (OpenCode-style)
    if step.write is not None:
        return [ToolCall(call_id, "write", {"path": step.file, "content": step.write})]
    return [
        ToolCall(
            call_id, "edit", {"path": step.file, "old_string": step.edit_old, "new_string": step.edit_new}
        )
    ]
