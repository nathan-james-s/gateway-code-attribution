#!/usr/bin/env bash
# make perf (T114): capture's overhead on response time at load (SC-010) for both gateways, the PR check's matching
# time for a 1,000-line PR against a large store with storage per captured line (SC-009, SC-013), and how fast one
# ingest replica stores lines (T115).
# Results land in tests/perf/results/. Settings (defaults are the SC-013 load):
#   PERF_USERS=500 PERF_DURATION=300 PERF_THINK=10,60 PERF_STREAM_SECONDS=2 PERF_GATEWAYS=agentgateway,litellm
#   PERF_SCALE=0.05   fraction of the other developers' 90 days of captures to load (1.0 is about 130 GB)
set -euo pipefail
cd "$(dirname "$0")/../.."
status=0
uv run --group perf python tests/perf/gateway_overhead.py \
  --gateways "${PERF_GATEWAYS:-agentgateway,litellm}" --users "${PERF_USERS:-500}" \
  --duration "${PERF_DURATION:-300}" --think "${PERF_THINK:-10,60}" \
  --stream-seconds "${PERF_STREAM_SECONDS:-2}" || status=1
uv run python -m tests.perf.prcheck_scale --scale "${PERF_SCALE:-0.05}" || status=1
uv run python -m tests.perf.ingest_rate || status=1
exit "$status"
