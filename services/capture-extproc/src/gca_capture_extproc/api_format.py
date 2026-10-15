"""Derive the API format and a tool hint from request headers (T042). No content involved."""

from __future__ import annotations

from collections.abc import Mapping

__all__ = ["api_format_for_path", "tool_hint"]


def api_format_for_path(path: str | None) -> str | None:
    """Map a request path to an API format; None means "not a model response we capture"."""
    if not path:
        return None
    p = path.split("?", 1)[0]
    if p.endswith("/chat/completions"):
        return "openai_chat"
    if p.endswith("/responses"):
        return "openai_responses"
    if p.endswith("/messages"):
        return "anthropic_messages"
    if ":streamGenerateContent" in p or ":generateContent" in p:
        return "gemini_native"
    return None


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


def model_from_path(path: str | None) -> str | None:
    """Gemini puts the model in the URL: /v1beta/models/<model>:streamGenerateContent."""
    if not path or "/models/" not in path:
        return None
    tail = path.split("?", 1)[0].split("/models/", 1)[1]
    return tail.split(":", 1)[0][:128] or None
