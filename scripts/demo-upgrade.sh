#!/usr/bin/env bash
# make demo-upgrade [VALUES=...] : rebuild images and upgrade the running demo release in place.
set -euo pipefail
cd "$(dirname "$0")/.."
GATEWAY=${GATEWAY:-$(helm get values "${RELEASE:-gca}" -n "${NAMESPACE:-gca}" -o json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("gateway",{}).get("type","agentgateway"))' || echo agentgateway)}
GATEWAY="$GATEWAY" exec scripts/demo.sh
