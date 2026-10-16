"""gcattr: the single, versioned matching library for gateway-sourced AI-code attribution.

Public API: see ``specs/001-gateway-code-attribution/contracts/library-api.md``.
"""

from __future__ import annotations

from importlib import metadata

from .adapters.litellm import from_litellm
from .algorithm import ALG, PARAMS, SUPPORTED_ALGS, AlgParams, UnicodeVersionMismatch, UnsupportedAlg
from .classify import summarize
from .extract import extract
from .fingerprint import FingerprintKey
from .match import LookupKeys, attribute, lookup_keys, select_candidates
from .streams import parse_stream
from .types import (
    AddedLine,
    ApiFormat,
    Candidate,
    CapturedToolOutput,
    CaptureFailure,
    LineFingerprint,
    LineOutcome,
)

try:
    __version__ = metadata.version("gcattr")
except metadata.PackageNotFoundError:  # running from a source tree
    __version__ = "0.0.0+source"

__all__ = [
    "ALG",
    "PARAMS",
    "SUPPORTED_ALGS",
    "AddedLine",
    "AlgParams",
    "ApiFormat",
    "Candidate",
    "CaptureFailure",
    "CapturedToolOutput",
    "FingerprintKey",
    "LineFingerprint",
    "LineOutcome",
    "LookupKeys",
    "UnicodeVersionMismatch",
    "UnsupportedAlg",
    "__version__",
    "attribute",
    "extract",
    "from_litellm",
    "lookup_keys",
    "parse_stream",
    "select_candidates",
    "summarize",
]
