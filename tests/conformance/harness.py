"""Cross-gateway conformance harness (T063; FR-006; research R4).

The gateways themselves run through `gca_eval.gateways` (shared with the eval runner, T106). This module adds
what's specific to conformance: one test credential, and an upstream that also serves the assessment probe's
fixture streams (`gca-fixture=<name>` in the prompt) and the recorded real-traffic corpus
(`gca-corpus=<tool>/<api_format>/<n>`; eval/corpus, T112), byte for byte as the tool received it.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import re
from pathlib import Path

from gca_core.messages import line_to_wire
from gca_eval.gateways import Credential, canonical, replay, stack
from gcattr import FingerprintKey, parse_stream
from gcattr.io import fingerprint_outputs

__all__ = [
    "CREDENTIAL",
    "FIXTURE_FORMATS",
    "canonical",
    "corpus_cases",
    "corpus_lines",
    "replay",
    "respond",
    "stack",
    "write_keys",
]

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


CORPUS = ROOT / "eval" / "corpus"
_CORPUS = re.compile(r"gca-corpus=([a-z-]+/[a-z_]+/[0-9]+)")


def corpus_cases() -> list[tuple[str, str, str]]:
    """(case id, api format, prompt) for every recorded response of every tool with consent."""
    out = []
    for f in sorted(CORPUS.glob("*/*/*.sse")):
        tool, fmt = f.parent.parent.name, f.parent.name
        if (CORPUS / tool / "consent.yaml").is_file():
            ref = f"{tool}/{fmt}/{f.stem}"
            out.append((f"corpus-{ref.replace('/', '-')}", fmt, f"gca-corpus={ref}"))
    return out


def corpus_lines(ref: str) -> list[str]:
    """What the library itself reads from a recorded response, in the canonical form of `canonical()`."""
    tool, fmt, n = ref.split("/")
    raw = (CORPUS / tool / fmt / f"{n}.sse").read_bytes()
    res = fingerprint_outputs(parse_stream(fmt, [raw]), FingerprintKey(1, SECRET))
    wires = [line_to_wire(fp) for fp in res.lines]
    return sorted(json.dumps([w["t"], w["l"], w["x"], w["m"], w["b"], w.get("p", [])]) for w in wires)


def respond(api_format: str, path: str, body: str) -> bytes | None:
    """A probe fixture or a recorded response when the prompt names one; otherwise demo-model's own answer."""
    m = _FIXTURE.search(body)
    if m and m.group(1) in FIXTURE_FORMATS:
        return fixtures.FIXTURES[m.group(1)]()[0].encode("utf-8")
    c = _CORPUS.search(body)
    if c:
        tool, fmt, n = c.group(1).split("/")
        recorded = CORPUS / tool / fmt / f"{n}.sse"
        if recorded.is_file():
            return recorded.read_bytes()
    return None
