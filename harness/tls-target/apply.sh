#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:?namespace is required}"
RELEASE="${2:?release is required}"
SERVICE_NAME="${3:?service name is required}"
HOSTNAME="${4:?hostname is required}"
COMMON_NAME="${5:?common name is required}"
SUBJECT_ALT_NAMES="${6:?subjectAltName is required}"
DAYS="${7:?validity days is required}"
BACKUP_FILE="${8:?CoreDNS backup file is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TIMEOUT="${SRE_AGENT_TLS_TARGET_HELM_TIMEOUT:-3m}"
SECRET_NAME="${RELEASE}-tls"
CERT_DIR="$(dirname "$BACKUP_FILE")/${RELEASE}-cert"

command -v helm >/dev/null 2>&1 || { echo "helm is required" >&2; exit 127; }
command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }
command -v openssl >/dev/null 2>&1 || { echo "openssl is required" >&2; exit 127; }

"$SCRIPT_DIR/generate-cert.sh" "$DAYS" "$COMMON_NAME" "$SUBJECT_ALT_NAMES" "$SECRET_NAME" "$NAMESPACE" "$CERT_DIR"

helm upgrade --install "$RELEASE" "$SCRIPT_DIR/chart" \
  --namespace "$NAMESPACE" \
  --create-namespace \
  --set "app.serviceName=$SERVICE_NAME" \
  --set "tls.secretName=$SECRET_NAME" \
  --wait --timeout "$TIMEOUT"

kubectl -n "$NAMESPACE" rollout status "deployment/$RELEASE" --timeout="$TIMEOUT"
"$ROOT/harness/dns-probe/apply.sh" "$NAMESPACE"

CLUSTER_IP="$(kubectl -n "$NAMESPACE" get service "$RELEASE" -o jsonpath='{.spec.clusterIP}')"
"$ROOT/harness/coredns-overrides/apply.sh" resolved "$HOSTNAME" "$CLUSTER_IP" "$BACKUP_FILE"
