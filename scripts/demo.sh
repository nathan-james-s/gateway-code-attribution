#!/usr/bin/env bash
# make demo GATEWAY=agentgateway|litellm [VALUES=values-github.yaml] [SECRET=github-app.secret.yaml] [CLUSTER=kind|orbstack]
# Creates a local cluster, builds and loads the images, installs the chart in demo mode (T062).
set -euo pipefail
cd "$(dirname "$0")/.."

GATEWAY=${GATEWAY:-agentgateway}
CLUSTER=${CLUSTER:-kind}
NAME=${KIND_CLUSTER:-gca}
NS=${NAMESPACE:-gca}
RELEASE=${RELEASE:-gca}
VALUES=${VALUES:-$([ -f values-github.yaml ] && echo values-github.yaml || true)}
SECRET=${SECRET:-$([ -f github-app.secret.yaml ] && echo github-app.secret.yaml || true)}
CHART=charts/gateway-code-attribution
TAG=${TAG:-0.1.0}

need() { command -v "$1" >/dev/null || { echo "error: $1 is required (see docs/install.md)"; exit 1; }; }
need docker; need helm; need kubectl
case "$GATEWAY" in agentgateway|litellm) ;; *) echo "error: GATEWAY must be agentgateway or litellm"; exit 1;; esac
[ -n "$VALUES" ] || { echo "error: no values-github.yaml; run: uv run gca setup github-app (docs/install.md 2.2)"; exit 1; }

node_image() {  # kindest/node pinned in versions.yaml
  awk '/kind-node:/{f=1} f&&/ref:/{r=$2} f&&/tag:/{t=$2} f&&/digest:/{print r":"t"@"$2; exit}' versions.yaml
}

if [ "$CLUSTER" = kind ]; then
  need kind
  if ! kind get clusters 2>/dev/null | grep -qx "$NAME"; then
    echo "==> creating kind cluster $NAME"
    cat <<KIND | kind create cluster --name "$NAME" --image "$(node_image)" --config -
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraPortMappings:
      - {containerPort: 30080, hostPort: 8080, listenAddress: 127.0.0.1}   # portal
      - {containerPort: 30400, hostPort: 4000, listenAddress: 127.0.0.1}   # gateway
      - {containerPort: 30300, hostPort: 3000, listenAddress: 127.0.0.1}   # Grafana
KIND
  fi
  kubectl config use-context "kind-$NAME" >/dev/null
  KIND=1 KIND_CLUSTER="$NAME" TAG="$TAG" scripts/build-images.sh
else
  kubectl config use-context orbstack >/dev/null   # OrbStack's Kubernetes sees images built with its Docker
  TAG="$TAG" scripts/build-images.sh
fi

kubectl get namespace "$NS" >/dev/null 2>&1 || kubectl create namespace "$NS"
if [ -n "$SECRET" ]; then kubectl apply -n "$NS" -f "$SECRET" >/dev/null && echo "==> applied $SECRET"; fi

helm dependency build "$CHART" >/dev/null
echo "==> installing $RELEASE ($GATEWAY) into namespace $NS"
helm upgrade --install "$RELEASE" "$CHART" -n "$NS" -f "$VALUES" \
  --set gateway.type="$GATEWAY" \
  --set demo.enabled=true \
  --set prcheck.delivery=polling \
  --set images.tag="$TAG" \
  --set images.pullPolicy=Never \
  --set gateway.litellm.image.repository=ghcr.io/nathan-james-s/gca-litellm \
  --set gateway.litellm.image.tag="$TAG" \
  --set gateway.litellm.image.digest= \
  --set expose.nodePorts=true \
  --set grafana.service.type=NodePort \
  --set grafana.service.nodePort=30300 \
  --set postgres.storage=5Gi \
  --set nats.config.jetstream.fileStore.pvc.size=1Gi \
  --wait --timeout 10m

# Images are rebuilt under the same tag, so restart the project's pods to pick them up on re-runs.
kubectl -n "$NS" rollout restart deployment -l app.kubernetes.io/part-of=gateway-code-attribution >/dev/null
kubectl -n "$NS" rollout status deployment -l app.kubernetes.io/part-of=gateway-code-attribution --timeout=5m >/dev/null

PORTAL=http://localhost:8080; GW=http://localhost:4000; GRAFANA=http://localhost:3000
if [ "$CLUSTER" != kind ]; then
  echo "OrbStack: services are reachable at <service>.$NS.svc.cluster.local, or port-forward them, for example:"
  echo "  kubectl -n $NS port-forward svc/$RELEASE-gca-portal 8080:8080"
fi
cat <<DONE

Ready.
  Portal   $PORTAL   sign in with GitHub, then "Get gateway credential"
  Gateway  $GW   ($GATEWAY)
  Grafana  $GRAFANA   sign in with GitHub (admin password: kubectl -n $NS get secret $RELEASE-grafana -o jsonpath='{.data.admin-password}' | base64 -d)

Next:
  GCA_CREDENTIAL=<key> uv run gca demo run --repo <OWNER/REPO> --gateway $GATEWAY
DONE
