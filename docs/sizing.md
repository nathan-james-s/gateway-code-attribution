# Sizing

A default install is sized for **500 active developers** (SC-013): their captured AI output over the retention
period (90 days by default) and their pull requests, with the PR check result within 2 minutes (SC-009) and
capture adding no noticeable delay to responses (SC-010). Everything below was measured with `make perf`
(tests/perf, T114) unless it says otherwise. High availability isn't part of v1.

**Where the numbers come from**: an Apple-silicon laptop, PostgreSQL 17 in Docker, the real agentgateway binary
and LiteLLM with our capture code running locally (the same harness as conformance and the eval). A cluster's
numbers will differ; the ratios and the headroom are what to take from them.

## The load assumed

| | Default (R14) | Per day at 500 developers |
|---|---|---|
| Captured non-trivial AI lines per developer per day | 2,000 | 1M lines |
| Retention | 90 days | 90M lines held |
| Wire size per captured line | ~950 bytes | ~0.95 GB through NATS |

"Captured lines" are lines in model responses that write code, before anyone edits them: usually more than ends up
committed. Scale the tables below by your own figure.

## PostgreSQL

**Measured: 1,474 bytes per captured line**, tables and indexes included (4.67M lines: 180k with real
fingerprints, the rest filler of the same shape). That's about **1.4 GiB per million lines**.

| Developers | 2,000 lines/dev/day, 90 days | Captured fingerprints |
|---|---|---|
| 100 | 18M lines | ~25 GiB |
| 500 (SC-013) | 90M lines | **~123 GiB** |
| 1,000 | 180M lines | ~247 GiB |
| 2,000 | 360M lines | ~494 GiB |

The default volume is **200 Gi**: 123 GiB of fingerprints, plus capture event metadata, PR results (kept
indefinitely; a few hundred bytes per attributed line, estimated, not measured), the write-ahead log and normal
table bloat. Size your own volume as roughly

    developers × captured lines per day × retention days × 1.5 KB × 1.3

Retention scales storage linearly: 30 days instead of 90 needs a third. Fingerprints older than the matching
window (14 days by default) are kept only for re-running old checks, so shorter retention mostly costs that.

Of each line's 1,474 bytes, the 128-value similarity signature is about 530 and the band index about 450. The rest
is the row and its two B-tree indexes. Before migration 0007 the bands were a separate table and a line took
about 2,650 bytes.

**Production**: the chart's single PostgreSQL StatefulSet suits evaluation and small teams. For production, run
PostgreSQL 17 with the **CloudNativePG** operator or a managed service, and point the chart at it
(`postgres.internal: false`, [configuration](configuration.md#postgres)). The database needs the `btree_gin`
extension (it ships with PostgreSQL). v1 makes no high-availability guarantee either way.

## The PR check (SC-009)

**Measured: a 1,000-line PR matched in 16.7 seconds**, with the author's full 90 days of captures (180k lines)
in a 4.67M-line store. 16.2 seconds of it is the indexed candidate lookup. GitHub's API calls (diff, blame, check
run) come on top.

The lookup cost grows with the size of the PR and the length of the matching window, not with how much the whole
organization has captured. It's a few index lookups per line, per day of the window. The PR check runs one
replica and works through pending heads in order.

## Capture (SC-010)

**Measured at the SC-013 load**: 500 simulated developers, each sending a streamed tool-call response (about 2
seconds long, like a model) every 10 to 60 seconds, for 5 minutes, capture off and then on:

| | p95 without capture | p95 with capture | Overhead | Responses | Lost |
|---|---|---|---|---|---|
| agentgateway + capture-extproc | 2,598 ms | 2,660 ms | **+2.4%** | 4,195 | 0 |
| LiteLLM + callback | 2,665 ms | 2,662 ms | **−0.1%** | 4,157 | 0 |

SC-010 allows 5%. The agentgateway figure is with **one** capture worker process; a default install runs two
capture-extproc replicas.

- **capture-extproc** (agentgateway): 2 replicas by default (`capture.replicas`). Its work grows with concurrent
  streams. Add a replica for each additional 500 developers or so; that's an extrapolation from this run, not a
  measurement.
- **LiteLLM**: capture runs in the gateway process and showed no measurable cost; scale LiteLLM as its own
  documentation says for your traffic.

## Ingest and NATS

**Measured: one ingest replica stores 4,842 lines per second** (1,000 events of 40 lines, one transaction per
message, as the consumer does). 500 developers need about 12 a second on average and a few dozen at peak. Ingest
runs **one replica** on purpose: it reads each capture instance's messages in order, which the sequence-gap loss
accounting and the watermark depend on.

NATS JetStream holds capture messages only until ingest stores them. Its default 10 Gi volume holds about **10
days** of backlog at the SC-013 rate if ingest stops, longer for fewer developers. A capture message is at most
900 KB; larger responses are sent in parts.

## Beyond 500 developers

- **Storage** grows linearly: use the formula above, or shorten retention.
- **The PR check** depends on PR size and window, not organization size. It runs one replica; at very high PR
  volume, checks wait their turn.
- **Capture**: add capture-extproc replicas as concurrent streams grow.
- **Ingest** has about 100 times the SC-013 rate in hand; past a few thousand captured lines a second, the
  database's write capacity is the limit, not ingest.
- Move PostgreSQL to CloudNativePG or a managed service early, and watch its disk.

Re-measure on your own hardware with `make perf` (settings in `tests/perf/run.sh`).
