"""Golden corpus for one algorithm version (T094; FR-032, FR-033, SC-008; Constitution III).

`lib/tests/golden/alg-<n>/` holds:

- `inputs/`: recorded responses, frozen when the corpus was created (raw streams, and LiteLLM callback objects);
- `fingerprints/<input>.jsonl`: every fingerprint for that input under the test key, then one line per failure;
- `attribute.json`: added lines and the captures they're matched against, by reference to the inputs;
- `attribute.expected.jsonl`: the outcome for each added line.

The test key is 32 bytes of 0x42, key generation 1. Outputs are byte-identical on every supported platform; the
test recomputes them from `inputs/` and compares bytes. A change that alters any output needs a new `ALG` and a new
corpus directory, never a regenerated one (scripts/check-alg-bump.sh).

    uv run python -m lib.tests.golden.generate          # writes alg-<ALG>/, refusing to overwrite outputs
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from gcattr import ALG, AddedLine, Candidate, FingerprintKey, attribute, from_litellm, parse_stream
from gcattr.io import fingerprint_outputs, fingerprint_to_json

HERE = Path(__file__).resolve().parent
KEY = FingerprintKey(1, b"\x42" * 32)
JSON = {"sort_keys": True, "separators": (",", ":"), "ensure_ascii": True}

# input name -> how to read it: ("stream", api_format) for a raw response, ("litellm", call_type, api_format)
SOURCES: dict[str, tuple[str, ...]] = {
    "openai_chat.sse": ("stream", "openai_chat"),
    "openai_responses.sse": ("stream", "openai_responses"),
    "anthropic.sse": ("stream", "anthropic_messages"),
    "anthropic_truncated.sse": ("stream", "anthropic_messages"),
    "gemini.sse": ("stream", "gemini_native"),
    "litellm_acompletion.json": ("litellm", "acompletion", "openai_chat"),
    "litellm_aresponses.json": ("litellm", "aresponses", "openai_responses"),
    "litellm_anthropic_messages.json": ("litellm", "anthropic_messages", "anthropic_messages"),
    "litellm_agenerate_content_stream.json": ("litellm", "agenerate_content_stream", "gemini_native"),
}

# Added lines for the attribution case. Author 4242 used the gateway (captures below); 5151 has a credential but
# no captures; None is a commit author GitHub links to no account. Expected outcomes are whatever the algorithm
# gives; `test_golden` checks that the case covers every outcome and tier.
CAPTURES = {4242: ["openai_chat.sse", "anthropic.sse"]}
LINES: list[tuple[str, int, str, int | None]] = [
    ("src/app.py", 1, "def total(items):", 4242),
    ("src/app.py", 2, "\tsubtotal = sum(i.price for i in items)  # cafe", 4242),  # edited: anchored
    ("src/app.py", 3, "    print(\"a\\nb\", 'quote')", 4242),
    ("src/app.py", 4, "    tax = 1.0825", 4242),
    ("src/app.py", 5, "    return round(subtotal * tax, 2)", 4242),
    ("src/app.py", 6, "", 4242),
    ("src/app.py", 7, 'émoji = "🚀"', 4242),
    ("src/app.py", 8, "    subtotal = sum(item.price for item in items)  # café", 4242),
    ("src/app.py", 9, "    log_everything_to_a_remote_audit_service(items, verbose=True)", 4242),
    ("src/app.py", 10, "}", 4242),
    ("lib/other.py", 1, "\tsubtotal = sum(i.price for i in items)  # cafe", 4242),  # moved and edited: broad
    ("lib/other.py", 2, "    return round(subtotal * 1.0825, 3)", 5151),
    ("lib/other.py", 3, "    return round(subtotal * tax, 2)", None),
    ("web/add.ts", 1, "export const add = (a: number, b: number): number => a + b;", 4242),
]


def fixture_inputs() -> dict[str, bytes]:
    """The inputs a new corpus starts from, taken from lib/tests/fixtures."""
    sys.path.insert(0, str(HERE.parents[2]))
    from lib.tests.fixtures.streams import FIXTURES

    out = {}
    for name, src in SOURCES.items():
        if src[0] == "stream":
            out[name] = FIXTURES[name.removesuffix(".sse")]()[0].encode("utf-8")
        else:
            path = HERE.parent / "fixtures" / "litellm_1_105" / f"{src[1]}.json"
            out[name] = path.read_bytes()
    return out


def _results(name: str, data: bytes) -> Any:
    src = SOURCES[name]
    if src[0] == "stream":
        return parse_stream(src[1], [data])  # type: ignore[arg-type]
    return from_litellm(json.loads(data)["response_obj"], src[1], src[2])  # type: ignore[arg-type]


def outputs(alg: int, inputs: dict[str, bytes]) -> dict[str, bytes]:
    """Every expected-output file of the corpus, computed from its inputs."""
    files: dict[str, bytes] = {}
    fingerprints = {}
    for name in sorted(SOURCES):
        result = fingerprint_outputs(_results(name, inputs[name]), KEY, alg)
        fingerprints[name] = result.lines
        rows = [json.dumps(fingerprint_to_json(fp), **JSON) for fp in result.lines]
        rows += [json.dumps({"failure": c}, **JSON) for c in result.failures]
        files[f"fingerprints/{name}.jsonl"] = ("\n".join(rows) + "\n").encode("ascii")
    candidates = {
        gid: [
            Candidate(name, f.exact_fp, f.minhash, f.path_suffix_fps, f.tool_call_ordinal, f.line_ordinal,
                      f.alg, f.key_gen, f.lsh_bands)
            for name in names
            for f in fingerprints[name]
        ]
        for gid, names in CAPTURES.items()
    }  # fmt: skip
    candidates[5151] = []
    case = {"key_gen": KEY.key_gen, "captures": {str(k): v for k, v in CAPTURES.items()}, "lines": LINES}
    files["attribute.json"] = (json.dumps(case, indent=1, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "ascii"
    )
    lines = [AddedLine(*ln) for ln in LINES]
    rows = [json.dumps(o._asdict(), **JSON) for o in attribute(lines, candidates, {KEY.key_gen: KEY}, alg)]
    files["attribute.expected.jsonl"] = ("\n".join(rows) + "\n").encode("ascii")
    return files


def read_inputs(corpus: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted((corpus / "inputs").iterdir())}


def main(alg: int = ALG) -> int:
    corpus = HERE / f"alg-{alg}"
    if (corpus / "fingerprints").exists():
        print(
            f"{corpus} already exists. A corpus is never regenerated: bump ALG for a new one.",
            file=sys.stderr,
        )
        return 1
    inputs = fixture_inputs()
    for name, data in inputs.items():
        (corpus / "inputs").mkdir(parents=True, exist_ok=True)
        (corpus / "inputs" / name).write_bytes(data)
    for rel, data in outputs(alg, inputs).items():
        (corpus / rel).parent.mkdir(parents=True, exist_ok=True)
        (corpus / rel).write_bytes(data)
    print(f"wrote {corpus}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
