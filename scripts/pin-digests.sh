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
values=charts/gateway-code-attribution/values.yaml
if [ -f "$values" ]; then
  yq -i ".gateway.agentgateway.image.digest = \"$(yq '.images.agentgateway.digest' versions.yaml)\"" "$values"
  yq -i ".gateway.litellm.image.digest = \"$(yq '.images.litellm.digest' versions.yaml)\"" "$values"
  yq -i ".postgres.image.digest = \"$(yq '.images.postgres.digest' versions.yaml)\"" "$values"
  echo "updated $values"
fi
