# The `gcattr` library

`gcattr` is the matching library at the centre of the stack, released on its own so other tools can reuse it
(User Story 5). Capture, the PR check and the `gca` CLI all use this one implementation, so a result computed
outside the stack is the same as the stack's. It has no runtime dependencies beyond the Python 3.12 standard
library.

```bash
pip install gcattr
gca version
```

## What it does

1. **Reads model output.** `parse_stream(api_format, chunks)` reassembles a recorded response (streamed or not) for
   OpenAI Chat Completions, OpenAI Responses, Anthropic Messages and Gemini; `from_litellm(obj, call_type)` reads
   LiteLLM's callback objects. Both yield `CapturedToolOutput` values, and `CaptureFailure` values instead of
   raising, so a caller can count what it couldn't read.
2. **Fingerprints code lines.** `extract(output, key, alg)` normalizes each line, drops trivial ones and returns
   `LineFingerprint`s: a 16-byte keyed exact fingerprint, a 32-value MinHash signature with 8 LSH bands, and keyed
   fingerprints of the last one to three path components. Nothing in a fingerprint can be turned back into code
   without the key. `gcattr.io.fingerprint_outputs` does this for a whole response, numbering its tool calls.
3. **Attributes added lines.** `attribute(lines, candidates_by_author, keys, alg)` matches each `AddedLine` against
   the captures of the developer it's credited to, in tiers (exact; anchored similarity; broad similarity; then
   lines a formatter wrapped or split, joined back together), each capture used at most once. `summarize(outcomes)` counts the results with and without broad matches.

See [outcomes.md](outcomes.md) for what each outcome means, and
[contracts/library-api.md](../specs/001-gateway-code-attribution/contracts/library-api.md) for the full API.

## Versioning guarantees

- **Semantic versioning** for the Python API and the CLI.
- **`ALG`** is a separate integer, recorded on every fingerprint and result. Any change that alters a fingerprint
  or an outcome raises `ALG` and is at least a minor release. `SUPPORTED_ALGS` lists the versions a release can
  still compute, so stored fingerprints stay matchable after an upgrade.
- **Byte-identical output.** For every algorithm version in `SUPPORTED_ALGS`, the same input, key and key
  generation give the same bytes on every supported platform. The golden corpus in `lib/tests/golden/alg-<n>/`
  checks this on Linux and macOS in CI, and the `golden-frozen` check stops anyone regenerating a corpus instead
  of raising `ALG`.
- **Unicode pin.** Normalization depends on Unicode data, so each `alg` pins a Unicode version. Fingerprinting
  raises `UnicodeVersionMismatch` under any other version rather than silently producing different fingerprints.
  `gca version` shows the pin and your interpreter's version.
- **Keys** are at least 32 bytes with a key generation number. The library never logs, stores or prints keys or
  code.

## The CLI

All commands take `--json` (before the command) for machine-readable output. Exit codes: 0 ok, 2 input error,
3 Unicode version mismatch, 4 unsupported algorithm version.

A key file holds the key base64-encoded. `--key-file` also accepts a directory in the stack's Secret layout (one
file per key generation, plus `active`), for matching captures made under several generations.

### `gca fingerprint`

Fingerprints for a recorded response, read from stdin, one JSON line per code line and one per failure:

```bash
gca fingerprint --key-file key.b64 --format anthropic_messages < response.sse
```

### `gca attribute`

Attributes a local branch range against exported captures, the way the PR check attributes a pull request:

```bash
gca attribute --repo . --base main --head my-branch --captures captures.jsonl --key-file keys/
```

- Added lines come from `git diff` between the merge base and the head, read by the same code as the PR check.
- Each line is credited through `git blame` at the head: a line whose commit is in the range goes to that
  commit's author, anything else is *not observed*. Authors are GitHub account ids, taken from GitHub no-reply
  addresses (`<id>+<login>@users.noreply.github.com`) or given with `--author EMAIL=GITHUB_ID`.
- The stack's default exclusion rules apply; `--exclude GLOB` (repeatable) replaces them.
- Nothing is written to disk. Output has positions and outcomes only; `--explain` adds each line's text, which is
  already in your checkout.

A captures file is JSON lines, one captured line each, with the GitHub account id of the developer whose gateway
credential captured it:

```json
{"github_id": 4242, "capture_event_id": "…", "alg": 1, "key_gen": 1, "tool_call_ordinal": 1, "line_ordinal": 3,
 "exact_fp": "<base64>", "minhash": [32 integers], "lsh_bands": ["<base64>", …], "path_suffix_fps": ["<base64>", …]}
```

`tests/integration/test_cli_matches_prcheck.py` exports one from a running stack and checks that `gca attribute`
reproduces the PR check's result for every line.

## Using it outside the stack

A tool that sits in front of a model can fingerprint what the model writes and keep only the fingerprints:

```python
from gcattr import AddedLine, Candidate, FingerprintKey, attribute, parse_stream, summarize
from gcattr.io import fingerprint_outputs

key = FingerprintKey(1, secret_bytes).check()  # 32+ random bytes, kept secret

# At capture time: fingerprints only, never the response itself.
fps = fingerprint_outputs(parse_stream("openai_chat", [response_bytes]), key).lines

# Later, for a change: the lines it adds, credited to GitHub account 4242.
captures = {
    4242: [
        Candidate(
            "response-1",
            f.exact_fp,
            f.minhash,
            f.path_suffix_fps,
            f.tool_call_ordinal,
            f.line_ordinal,
            f.alg,
            f.key_gen,
            f.lsh_bands,
        )
        for f in fps
    ]
}
lines = [AddedLine("src/app.py", 10, "def total(items):", 4242)]
outcomes = attribute(lines, captures, {key.key_gen: key})
print(summarize(outcomes)["counts"])
```
