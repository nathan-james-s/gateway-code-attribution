#!/usr/bin/env bash
# Resolve every image tag in versions.yaml to its current digest and write it back (T007, Constitution VI).
# Also mirrors the digests into the chart's values.yaml when the chart exists.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v yq >/dev/null || { echo "yq is required (https://github.com/mikefarah/yq)" >&2; exit 2; }
resolve() {
  if command -v crane >/dev/null; then crane digest "$1"
  else docker buildx imagetools inspect "$1" --format '{{json .Manifest.Digest}}' | tr -d '"'; fi
}
for name in $(yq '.images | keys | .[]' versions.yaml); do
  ref=$(yq ".images.\"$name\".ref" versions.yaml); tag=$(yq ".images.\"$name\".tag" versions.yaml)
  digest=$(resolve "$ref:$tag")
  yq -i ".images.\"$name\".digest = \"$digest\"" versions.yaml
  echo "$name $ref:$tag -> $digest"
done
# Third-party images in the chart. This project's own images (gca-*, including gca-litellm) are pinned by
# release.yml from the digests of the images it builds; versions.yaml's litellm entry is the upstream image we
# don't run, so it is never mirrored.
values=charts/gateway-code-attribution/values.yaml
if [ -f "$values" ]; then
  d() { yq ".images.\"$1\".digest" versions.yaml; }
  yq -i ".gateway.agentgateway.image.digest = \"$(d agentgateway)\"" "$values"
  yq -i ".postgres.image.digest = \"$(d postgres)\"" "$values"
  yq -i ".nats.container.image.digest = \"$(d nats)\"" "$values"
  yq -i ".nats.reloader.image.digest = \"$(d nats-reloader)\"" "$values"
  yq -i ".grafana.image.sha = \"$(d grafana | sed 's/^sha256://')\"" "$values"
  echo "updated $values"
fi
