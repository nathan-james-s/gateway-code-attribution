#!/usr/bin/env bash
# Add the chart repositories the chart's dependencies come from (Chart.yaml), so `helm dependency build`
# works on a fresh machine or CI runner. Idempotent.
set -euo pipefail
helm repo add nats https://nats-io.github.io/k8s/helm/charts/ --force-update >/dev/null
helm repo add grafana-community https://grafana-community.github.io/helm-charts --force-update >/dev/null
