"""Cross-gateway conformance harness (T063; FR-006; research R4).

The gateways themselves run through `gca_eval.gateways` (shared with the eval runner, T106). This module adds
what's specific to conformance: one test credential, and an upstream that also serves the assessment probe's
fixture streams on request (`gca-fixture=<name>` in the prompt).
"""

from __future__ import annotations

import base64
import importlib.util
import re
from pathlib import Path

from gca_eval.gateways import Credential, canonical, replay, stack

__all__ = ["CREDENTIAL", "FIXTURE_FORMATS", "canonical", "replay", "respond", "stack", "write_keys"]

ROOT = Path(__file__).resolve().parents[2]
SECRET = b"\x5a" * 32
CREDENTIAL = Credential("sk-gca-conformance-agentgateway-key", "11111111-2222-3333-4444-555555555555", 4242)

_spec = importlib.util.spec_from_file_location("probe_fixtures", ROOT / "lib/tests/fixtures/streams.py")
fixtures = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(fixtures)  # type: ignore[union-attr]
_FIXTURE = re.compile(r"gca-fixture=([a-z_]+)")
FIXTURE_FORMATS = {
    "openai_chat": "openai_chat",
    "openai_responses": "openai_responses",
    "anthropic": "anthropic_messages",
    "anthropic_truncated": "anthropic_messages",
    "gemini": "gemini_native",
}


def write_keys(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "1").write_text(base64.b64encode(SECRET).decode())
    (directory / "active").write_text("1")
    return directory


def respond(api_format: str, path: str, body: str) -> bytes | None:
    """A probe fixture when the prompt names one; otherwise demo-model's own answer (None)."""
    m = _FIXTURE.search(body)
    if m and m.group(1) in FIXTURE_FORMATS:
        return fixtures.FIXTURES[m.group(1)]()[0].encode("utf-8")
    return None
