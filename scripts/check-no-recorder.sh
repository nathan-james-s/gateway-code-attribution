#!/usr/bin/env bash
# Fails if shipped code could record traffic (Constitution II; T066, T111). The consented-corpus recorder lives in
# eval/ and must never be reachable from services/ or charts/.
#
#   scripts/check-no-recorder.sh            source checks
#   scripts/check-no-recorder.sh --images   also inspect the built images (scripts/build-images.sh; REGISTRY, TAG):
#                                           none may contain eval/corpus/record.py or any eval/ file but the
#                                           workspace manifest eval/harness/pyproject.toml
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
if [ "${1:-}" = "--images" ]; then
  REGISTRY=${REGISTRY:-ghcr.io/nathan-james-s}
  TAG=${TAG:-0.1.0}
  for name in gca-capture-extproc gca-litellm gca-ingest gca-prcheck gca-portal gca-demo; do
    image="$REGISTRY/$name:$TAG"
    if ! docker image inspect "$image" >/dev/null 2>&1; then
      echo "no-recorder: $image is not built here"; fail=1; continue
    fi
    cid=$(docker create "$image")
    found=$(docker export "$cid" | tar -t | grep -E '(^|/)eval/' | grep -vE '(^|/)eval/(harness/)?$|(^|/)eval/harness/pyproject\.toml$' || true)
    docker rm "$cid" >/dev/null
    if [ -n "$found" ]; then echo "no-recorder: $image contains eval/ files:"; echo "$found" | head -20; fail=1; fi
  done
  [ "$fail" = 0 ] && echo "no-recorder: images contain no eval/ files"
fi
if [ "$fail" = 0 ]; then echo "no-recorder: ok"; fi
exit "$fail"
