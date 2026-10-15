"""Derive the API format and a tool hint from the request (T042, T090). No content involved."""

from __future__ import annotations

from gca_core.tools import session_id, tool_hint

__all__ = ["UNSUPPORTED", "api_format_for_path", "classify", "model_from_path", "session_id", "tool_hint"]

UNSUPPORTED = "unsupported"

# Routes that never carry model-written code. Any other route through the gateway that capture can't parse is
# reported as an unsupported combination (FR-007) rather than dropped silently.
_NO_CODE_ENDINGS = (
    "/models",
    "/embeddings",
    "/moderations",
    "/files",
    "/batches",
    "/rerank",
    "/count_tokens",
    "/health",
    "/healthz",
    ":countTokens",
    ":embedContent",
    ":batchEmbedContents",
)
_NO_CODE_PARTS = ("/images/", "/audio/", "/files/", "/batches/")


def classify(path: str | None) -> str | None:
    """The API format of a model response capture reads; UNSUPPORTED for a route that may carry model output but
    can't be read; None for a route that never carries code."""
    if not path:
        return None
    fmt = api_format_for_path(path)
    if fmt is not None:
        return fmt
    p = path.split("?", 1)[0].rstrip("/")
    last = p.rsplit("/", 1)[-1]
    if p.endswith(_NO_CODE_ENDINGS) or any(part in p + "/" for part in _NO_CODE_PARTS):
        return None
    if "/models/" in p and ":" not in last:
        return None  # model metadata, e.g. GET /v1/models/{id}
    return UNSUPPORTED


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


def model_from_path(path: str | None) -> str | None:
    """Gemini puts the model in the URL: /v1beta/models/<model>:streamGenerateContent."""
    if not path or "/models/" not in path:
        return None
    tail = path.split("?", 1)[0].split("/models/", 1)[1]
    return tail.split(":", 1)[0][:128] or None
