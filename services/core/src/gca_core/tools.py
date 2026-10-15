"""Which coding tool sent a request, from its headers (both capture adapters; FR-007). No content involved."""

from __future__ import annotations

from collections.abc import Mapping

__all__ = ["session_id", "tool_hint"]

_TOOLS = (
    ("claude-cli", "claude-code"),
    ("claude-code", "claude-code"),
    ("codex", "codex-cli"),
    ("gemini-cli", "gemini-cli"),
    ("geminicli", "gemini-cli"),
    ("opencode", "opencode"),
)


def tool_hint(headers: Mapping[str, str]) -> str | None:
    if "x-claude-code-session-id" in headers:
        return "claude-code"
    if "x-opencode-session-id" in headers:
        return "opencode"
    ua = headers.get("user-agent", "").lower()
    for needle, name in _TOOLS:
        if needle in ua:
            return name
    return None


def session_id(headers: Mapping[str, str]) -> str | None:
    for h in ("x-claude-code-session-id", "x-opencode-session-id", "session_id", "x-session-id"):
        if headers.get(h):
            return headers[h][:128]
    return None
