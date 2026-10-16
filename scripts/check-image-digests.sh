#!/usr/bin/env bash
# T119 (Constitution VI): every image the chart renders, for either gateway, is pinned by digest. This project's
# own images (gca-*) only get digests when release.yml builds them, so they're exempt unless --release.
set -euo pipefail
cd "$(dirname "$0")/.."
release=0
[ "${1:-}" = "--release" ] && release=1
images=$(for gw in agentgateway litellm; do
  helm template t charts/gateway-code-attribution --set github.existingSecret=gca-github-app \
    --set demo.enabled=true --set gateway.type="$gw"
done | sed -nE 's/^[[:space:]]+image:[[:space:]]*"?([^"]+)"?[[:space:]]*$/\1/p' | sort -u)
missing=$(echo "$images" | grep -v '@sha256:[0-9a-f]\{64\}$' || true)
if [ "$release" = 0 ]; then missing=$(echo "$missing" | grep -v '/gca-' || true); fi
if [ -n "$missing" ]; then
  echo "images without a digest:" >&2
  echo "$missing" >&2
  exit 1
fi
echo "image digests: all $(echo "$images" | wc -l | tr -d ' ') images pinned$([ "$release" = 0 ] && echo ' (gca-* exempt until release)')"
