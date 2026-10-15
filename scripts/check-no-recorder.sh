#!/usr/bin/env bash
# Fails if shipped code could record traffic (Constitution II; T066). The consented-corpus recorder lives in
# eval/ and must never be reachable from services/ or charts/. T111 adds an image check.
set -euo pipefail
cd "$(dirname "$0")/.."
fail=0
check() {  # description, grep -E pattern
  local hits
  hits=$(grep -rnE --include='*.py' --include='*.yaml' --include='*.yml' --include='*.tpl' --include='*.json' \
    --include='Dockerfile' --exclude-dir=tests --exclude-dir=sample-repo "$2" services charts || true)
  if [ -n "$hits" ]; then echo "no-recorder: $1"; echo "$hits"; fail=1; fi
}
check "shipped code imports from eval/" '^\s*(from|import)\s+(eval|gca_eval)\b'
check "shipped code references GCA_RECORD_DIR" 'GCA_RECORD_DIR'
check "a capture service has a record mode" '(--record\b|record_mode|RECORD_MODE|recording\s*=\s*True)'
# Images may copy only eval/harness/pyproject.toml (a workspace manifest uv needs), never other eval/ files.
copies=$(grep -nE '^COPY\s+eval' services/*/Dockerfile | grep -v 'COPY eval/harness/pyproject.toml eval/harness/pyproject.toml' || true)
if [ -n "$copies" ]; then echo "no-recorder: a Dockerfile copies eval/ content"; echo "$copies"; fail=1; fi
if [ "$fail" = 0 ]; then echo "no-recorder: ok"; fi
exit "$fail"
