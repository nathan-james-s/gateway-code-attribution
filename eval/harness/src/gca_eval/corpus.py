"""The recorded real-traffic corpus (eval/corpus, T112) as scenario material.

A recorded session is replayed to recover the files it left behind: each ``Write`` sets a file's content and each
``Edit`` replaces its ``old_string`` (once, or everywhere with ``replace_all``), in the order the tool called them.
When the owner accepted every edit, as the corpus tasks ask, those files are the model's output line for line,
which gives labels that don't come from the matching algorithm. ``replay`` checks that every edit applied cleanly.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path

from gcattr import parse_stream
from gcattr.extract import code_units
from gcattr.types import CaptureFailure

from .author import token_key

__all__ = ["CORPUS", "Recorded", "recorded", "replay", "written_lines"]

CORPUS = Path(__file__).resolve().parents[3] / "corpus"  # eval/corpus


@dataclass(frozen=True)
class Recorded:
    name: str  # e.g. "003"
    api_format: str
    data: bytes


def recorded(tool: str) -> list[Recorded]:
    """The tool's recorded responses, in recording order (only with the owner's consent.yaml)."""
    if not (CORPUS / tool / "consent.yaml").is_file():
        raise FileNotFoundError(f"no consent.yaml for {tool}: its recordings can't be used")
    files = sorted(CORPUS.glob(f"{tool}/*/*.sse"), key=lambda p: (int(p.stem), p.parent.name))
    return [Recorded(f.stem, f.parent.name, f.read_bytes()) for f in files]


def replay(responses: list[Recorded]) -> dict[str, str]:
    """The files the session's Write and Edit calls leave behind, keyed by path relative to the folder they share."""
    files: dict[str, str] = {}
    for r in responses:
        for out in parse_stream(r.api_format, [r.data]):
            if isinstance(out, CaptureFailure) or not isinstance(out.payload, dict):
                continue
            p = out.payload
            if out.tool_name == "Write":
                files[p["file_path"]] = p["content"]
            elif out.tool_name == "Edit":
                cur = files.get(p["file_path"])
                n = cur.count(p["old_string"]) if cur is not None else 0
                if n == 0 or (n > 1 and not p.get("replace_all")):
                    raise ValueError(
                        f"{r.name}: an Edit of {p['file_path']} doesn't apply to the replayed file"
                    )
                files[p["file_path"]] = cur.replace(
                    p["old_string"], p["new_string"], -1 if p.get("replace_all") else 1
                )  # type: ignore[union-attr]
    root = posixpath.commonpath([posixpath.dirname(f) for f in files]) if files else ""
    return {posixpath.relpath(f, root): text for f, text in sorted(files.items())}


def written_lines(responses: list[Recorded]) -> set[str]:
    """Every line the model wrote anywhere in the session (all code the capture reads, every version), as token
    keys. A line a person types that equals one of these is AI unmodified by the spec's definition (it matches
    observed AI output), so a scenario must not label it human."""
    out: set[str] = set()
    for r in responses:
        for o in parse_stream(r.api_format, [r.data]):
            if not isinstance(o, CaptureFailure):
                for _, text, _ in code_units(o):
                    out.update(token_key(ln) for ln in text.splitlines())
    return out
