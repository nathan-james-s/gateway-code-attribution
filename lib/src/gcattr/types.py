"""Public value types (contracts/library-api.md). All are immutable; none is ever persisted with content."""

from __future__ import annotations

from typing import Literal, NamedTuple

ApiFormat = Literal["openai_chat", "openai_responses", "anthropic_messages", "gemini_native"]
API_FORMATS: tuple[ApiFormat, ...] = (
    "openai_chat",
    "openai_responses",
    "anthropic_messages",
    "gemini_native",
)

FailureCause = Literal["truncated", "unparsable", "unexpected_format"]
Outcome = Literal["ai_unmodified", "ai_modified", "human", "indeterminate", "not_observed"]
Tier = Literal["exact", "anchored", "broad", "none"]
Confidence = Literal["high", "lower"]


class CapturedToolOutput(NamedTuple):
    """One code-bearing unit of model output. ``payload`` is held in memory only."""

    api_format: ApiFormat
    tool_name: str | None  # None for code in assistant text
    kind: Literal["json_args", "freeform", "text_block"]
    payload: (
        str | dict[str, object]
    )  # dict for parsed JSON args; raw str otherwise (or when JSON is incomplete)
    complete: bool  # False if truncated or unparsable
    call_id: str | None = None


class CaptureFailure(NamedTuple):
    """A capture problem, yielded (never raised) so callers can count loss (FR-005)."""

    cause: FailureCause
    detail: str = ""


class LineFingerprint(NamedTuple):
    exact_fp: bytes  # 16 bytes
    minhash: tuple[int, ...]  # minhash_size x uint32
    lsh_bands: tuple[bytes, ...]  # lsh_bands x 8 bytes
    path_suffix_fps: tuple[bytes, ...]  # 0..3 x 16 bytes
    tool_call_ordinal: int
    line_ordinal: int
    alg: int
    key_gen: int


class AddedLine(NamedTuple):
    file_path: str
    line_no: int
    text: str  # in memory only
    credited_github_id: int | None  # None when GitHub links the commit author to no account -> not_observed


class Candidate(NamedTuple):
    """A captured line as loaded from storage (no content)."""

    capture_event_id: str
    exact_fp: bytes
    minhash: tuple[int, ...]
    path_suffix_fps: tuple[bytes, ...]
    tool_call_ordinal: int
    line_ordinal: int
    alg: int
    key_gen: int
    lsh_bands: tuple[bytes, ...] = ()


class LineOutcome(NamedTuple):
    outcome: Outcome
    tier: Tier
    confidence: Confidence | None
    similarity: float | None
    matched_capture_event_id: str | None
