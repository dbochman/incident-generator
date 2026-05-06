#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$ROOT/harness/ecommerce-lite"
NAMESPACE="${SRE_AGENT_ECOMMERCE_NAMESPACE:-ecommerce}"
RELEASE="${SRE_AGENT_ECOMMERCE_RELEASE:-ecommerce-lite}"
POSTGRES_RELEASE="${SRE_AGENT_ECOMMERCE_POSTGRES_RELEASE:-checkout-postgres}"
LOADGEN_RELEASE="${SRE_AGENT_ECOMMERCE_LOADGEN_RELEASE:-checkout-postgres-loadgen}"
MESSAGING_SERVICE="${SRE_AGENT_ECOMMERCE_MESSAGING_SERVICE:-ecommerce-lite-messaging}"
MESSAGING_CONFIGMAP="${SRE_AGENT_ECOMMERCE_MESSAGING_CONFIGMAP:-ecommerce-lite-messaging-evidence}"
TIMEOUT="${SRE_AGENT_ECOMMERCE_TIMEOUT:-5m}"

command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }
command -v helm >/dev/null 2>&1 || { echo "helm is required" >&2; exit 127; }

"$ROOT/harness/shared/seed-helm.sh" \
  "$POSTGRES_RELEASE" \
  "$ROOT/harness/postgres-target/chart" \
  "$NAMESPACE" \
  "$SCRIPT_DIR/postgres-values.yaml"

"$ROOT/harness/shared/seed-helm.sh" \
  "$LOADGEN_RELEASE" \
  "$ROOT/harness/pgbench-loadgen/chart" \
  "$NAMESPACE" \
  "$SCRIPT_DIR/pgbench-values.yaml"

"$ROOT/harness/shared/seed-helm.sh" \
  "$RELEASE" \
  "$SCRIPT_DIR/chart" \
  "$NAMESPACE" \
  "$SCRIPT_DIR/chart/values.yaml"

"$ROOT/harness/messaging-state-shell/apply.sh" \
  "$NAMESPACE" \
  "$MESSAGING_SERVICE" \
  "checkout.events" \
  "checkout-consumers" \
  "$SCRIPT_DIR/evidence/recent_deploys.txt" \
  "$SCRIPT_DIR/evidence/queue_consumer_lag.txt" \
  "$SCRIPT_DIR/evidence/kafka_group_state.txt" \
  "$SCRIPT_DIR/evidence/queue_dead_letter.txt" \
  "$SCRIPT_DIR/evidence/error_logs.txt" \
  "$MESSAGING_CONFIGMAP" \
  "2"

for deployment in \
  "$RELEASE-storefront" \
  "$RELEASE-api-gateway" \
  "$RELEASE-checkout-api" \
  "$RELEASE-search-api" \
  "$RELEASE-profile-api" \
  "$RELEASE-edge-api" \
  "$MESSAGING_SERVICE"
do
  kubectl -n "$NAMESPACE" rollout status "deployment/$deployment" --timeout="$TIMEOUT"
done
