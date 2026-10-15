#!/usr/bin/env bash
# make demo-down : delete the local demo cluster (kind) or the release (CLUSTER=orbstack).
set -euo pipefail
if [ "${CLUSTER:-kind}" = kind ]; then
  kind delete cluster --name "${KIND_CLUSTER:-gca}"
else
  helm uninstall "${RELEASE:-gca}" -n "${NAMESPACE:-gca}" || true
  kubectl delete namespace "${NAMESPACE:-gca}" --ignore-not-found
fi
echo "Removed. Delete the GitHub App and sample repository on GitHub by hand if you no longer need them."
