#!/usr/bin/env bash
# Build all project images (T037). KIND=1 also loads them into the kind cluster named by KIND_CLUSTER.
set -euo pipefail
cd "$(dirname "$0")/.."
REGISTRY=${REGISTRY:-ghcr.io/nathan-james-s}
TAG=${TAG:-0.1.0}
for svc in capture-extproc capture-litellm ingest prcheck portal demo; do
  name="gca-${svc}"
  [ "$svc" = capture-litellm ] && name=gca-litellm
  echo "==> building $REGISTRY/$name:$TAG"
  docker build -f "services/$svc/Dockerfile" -t "$REGISTRY/$name:$TAG" .
  if [ "${KIND:-0}" = 1 ]; then kind load docker-image "$REGISTRY/$name:$TAG" --name "${KIND_CLUSTER:-gca}"; fi
done
