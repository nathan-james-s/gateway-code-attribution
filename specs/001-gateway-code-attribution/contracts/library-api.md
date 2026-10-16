# Contract: `gcattr` library and the `gca` CLI

**Consumers**: capture-extproc, capture-litellm, prcheck, the eval harness, and external users (User Story 5).
**Stability**: everything listed here is public API under semantic versioning. **The algorithm version (`alg`) is
part of the contract:** any change that alters a fingerprint or an outcome bumps `alg` (FR-032, Constitution III).

## Versioning guarantees

1. `gcattr.ALG`: an int, the current algorithm version. `gcattr.SUPPORTED_ALGS`: the versions this release can
   still compute.
2. For any `alg` in `SUPPORTED_ALGS`, the same input, key and key generation give **byte-identical** output on
   every supported platform (FR-033, SC-008). The golden corpus in `lib/tests/golden/alg-<n>/` enforces this.
3. Fingerprinting raises `UnicodeVersionMismatch` if `unicodedata.unidata_version` differs from the version
   pinned for that `alg` (R8). It never fingerprints silently under a different Unicode version.
4. A key is `bytes` (≥ 32 bytes) with a `key_gen: int`. The library never persists or logs keys or content.

## Python API (summary signatures)

```python
# Keys and versions
class FingerprintKey(NamedTuple):
    key_gen: int
    secret: bytes


# Capture side
class CapturedToolOutput(NamedTuple):  # produced by stream parsers or adapters
    api_format: Literal["openai_chat", "openai_responses", "anthropic_messages", "gemini_native"]
    tool_name: str | None  # None for code blocks in assistant text
    kind: Literal["json_args", "freeform", "text_block"]
    payload: str | dict  # in memory only
    complete: bool  # False if truncated or unparsable


def parse_stream(api_format, chunks: Iterable[bytes]) -> Iterator[CapturedToolOutput | CaptureFailure]: ...
def from_litellm(response_obj, call_type: str) -> Iterator[CapturedToolOutput | CaptureFailure]: ...


class LineFingerprint(NamedTuple):
    exact_fp: bytes  # 16 bytes
    minhash: tuple[int, ...]  # 128 × uint32
    lsh_bands: tuple[bytes, ...]  # 8 × 8 bytes, over the first 32 minhash values
    path_suffix_fps: tuple[bytes, ...]  # 0..3 × 16 bytes
    tool_call_ordinal: int
    line_ordinal: int


def extract(output: CapturedToolOutput, key: FingerprintKey, alg: int = ALG) -> list[LineFingerprint]:
    """R7 extraction → R8 normalization → R10 trivial filter → fingerprints. Trivial lines are dropped."""


# Attribution side
class AddedLine(NamedTuple):
    file_path: str
    line_no: int
    text: str  # in memory only
    credited_github_id: int | None  # None when GitHub links the commit author to no account → not_observed


class Candidate(NamedTuple):  # a CapturedLine row as loaded from storage (no content)
    capture_event_id: str
    exact_fp: bytes
    minhash: tuple[int, ...]
    path_suffix_fps: tuple[bytes, ...]
    tool_call_ordinal: int
    line_ordinal: int
    alg: int
    key_gen: int
    lsh_bands: tuple[bytes, ...] = ()  # needed for the broad tier's band lookup


class LineOutcome(NamedTuple):
    outcome: Literal["ai_unmodified", "ai_modified", "human", "indeterminate", "not_observed"]
    tier: Literal["exact", "anchored", "broad", "none"]
    confidence: Literal["high", "lower"] | None
    similarity: float | None
    matched_capture_event_id: str | None


def attribute(
    lines: Sequence[AddedLine],
    candidates_by_author: Mapping[
        int, Sequence[Candidate]
    ],  # keyed by credited_github_id; missing or None → not_observed
    keys: Mapping[int, FingerprintKey],  # key_gen → key (active and retired)
    alg: int = ALG,
) -> list[LineOutcome]:
    """R11 tiered, author-scoped, multiset matching. Pure and deterministic."""


class LookupKeys(NamedTuple):
    exact: frozenset[tuple[int, int, bytes]]  # (alg, key_gen, exact_fp)
    bands: frozenset[tuple[int, int, int, bytes]]  # (alg, key_gen, band, band_hash)


def lookup_keys(
    lines: Sequence[AddedLine], keys: Mapping[int, FingerprintKey], alg: int = ALG
) -> dict[int, LookupKeys]:  # keyed by credited_github_id
    """What `attribute` can look candidates up by: the exact fingerprint and LSH bands of each added line and of
    each window of consecutive lines the wrapped tier may join. A store need not load every capture in the window:
    `attribute` gives exactly the same outcomes when passed only the candidates `select_candidates` keeps."""


def select_candidates(candidates: Sequence[Candidate], keys: LookupKeys) -> list[Candidate]:
    """Exact or band hits, plus every line of a capture event with an exact hit (the anchored tier's pool). The PR
    check runs the same selection as an indexed query."""


def summarize(
    outcomes: Sequence[LineOutcome],
) -> dict: ...  # counts, with/without broad, percentages (FR-014)
```

**Errors**: `CaptureFailure(cause=…)` is yielded, never raised, for truncated, unparsable and unexpected-format
input, so callers can count loss (FR-005). `UnicodeVersionMismatch` and `UnsupportedAlg` are raised.

## CLI (`gca`)

| Command | Purpose | Exit codes |
|---|---|---|
| `gca fingerprint --alg N --key-file F --format openai_chat < stream.sse` | print fingerprints (JSON lines; no content) for a recorded stream | 0 ok; 2 input error; 3 Unicode mismatch |
| `gca attribute --repo PATH --base REF --head REF --captures captures.jsonl --key-file F` | attribute a local branch range against exported captures (memory-backed checkout; R11) | 0 ok |
| `gca eval --scenarios eval/scenarios --gateway agentgateway\|litellm\|both --out report.json` | run the scenario set; write a quality report ([quality-report.schema.json](./quality-report.schema.json)) | 0 bar met; 10 release bar missed; 11 silent loss detected |
| `gca setup github-app --org ORG --out values-github.yaml` | GitHub App manifest flow; writes the App ID, client ID and secrets to a values file | 0 ok |
| `gca version` | print the library semver, `ALG`, `SUPPORTED_ALGS` and the pinned Unicode version | 0 |

All CLI output is JSON when `--json` is given. No command writes code or prompt text to disk or stdout, except
`attribute --explain`, which prints line text that's already present in the user's local checkout.
