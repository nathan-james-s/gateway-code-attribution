# Privacy assessment

This is the documented assessment that Constitution Principle II ("No Retained Code or Prompts") requires before
release. It covers what the stack stores, what the stored fingerprints reveal, and who can read what.

## Jurisdiction

The project is US-based and isn't designed around GDPR or works-council requirements. Adopters elsewhere are
responsible for their own compliance (FR-040).

## What is never stored

- Prompts, model responses and code, from the gateway or from GitHub. The capture services parse responses in
  memory, fingerprint them and drop the text. The PR check reads diffs and blame from GitHub in memory and drops
  them once a head is attributed.
- LiteLLM is configured with `turn_off_message_logging: true` and `store_prompts_in_spend_logs: false`.
- Logs never include request or response bodies. The privacy audit (`tests/privacy`) scans the database, the
  queue and every service's logs for code from a demo run.

## What is stored

| Data | Where | Holds |
|---|---|---|
| Exact fingerprint | `captured_line.exact_fp` | first 16 bytes of HMAC-SHA256(key, normalized tokens) |
| Similarity signature | `captured_line.minhash` | 32 keyed MinHash values over the line's token 3-grams |
| LSH bands | `lsh_band` | 8 keyed hashes of groups of 4 MinHash values |
| Path fingerprints | `captured_line.path_suffix_fps` | keyed hashes of the last 1 to 3 path components named by the tool call |
| Capture metadata | `capture_event` | time, developer, model name, API format, tool hint, counts. No content |
| Results | `line_result`, `change_head` | file path, line number, outcome, tier, similarity, credited developer |

File paths and line numbers of PR changes are stored; they're already visible to anyone with access to the
repository. Captured lines and their bands are deleted after `attribution.retentionDays` (90 by default).

## What a fingerprint reveals

All fingerprints are **keyed**. The key is a random 32-byte secret generated at install and kept in a Kubernetes
Secret.

- **Without the key**, stored values can't be computed, compared or reversed, and dictionary attacks don't work.
- **With the key**, someone can test a *guess*: fingerprint a candidate line and look for it. That's the same
  exposure for the exact fingerprint and the similarity signature. They can also estimate how similar two stored
  lines are.
- **Short lines leak most**, because they're easiest to guess. Lines with fewer than 3 tokens, or with no
  identifier, number or string, or on the common-lines list, are *indeterminate*: they get no fingerprint and
  are never stored.

**Residual risk**: an operator holding the key can confirm guesses about short, predictable lines a developer's
AI tool produced. They can't recover code they can't guess.

## Who can read what

| Component | Fingerprint key | Captured fingerprints | Per-line results |
|---|---|---|---|
| Capture (ext_proc, LiteLLM callback) | yes | writes only (via the queue) | no |
| Ingest | no | writes | no |
| PR check | yes | reads | writes |
| Portal | no | no | reads; per-developer views are role-checked |
| Grafana (`gca_reporting`) | no | no | no: aggregate views only, no per-developer columns |

Rotating the key (portal, admin) starts a new key generation; captures under the old one stay matchable until
they expire.
