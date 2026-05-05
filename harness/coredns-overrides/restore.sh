#!/usr/bin/env bash
set -euo pipefail

BACKUP_FILE="${1:?backup file is required}"
TIMEOUT="${SRE_AGENT_COREDNS_ROLLOUT_TIMEOUT:-120s}"

command -v kubectl >/dev/null 2>&1 || exit 0
[[ -f "$BACKUP_FILE" ]] || exit 0

kubectl -n kube-system create configmap coredns --from-file=Corefile="$BACKUP_FILE" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n kube-system rollout restart deployment/coredns >/dev/null
kubectl -n kube-system rollout status deployment/coredns --timeout="$TIMEOUT" >/dev/null || true
