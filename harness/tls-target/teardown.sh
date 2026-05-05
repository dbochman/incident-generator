#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:?namespace is required}"
RELEASE="${2:?release is required}"
BACKUP_FILE="${3:?CoreDNS backup file is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

"$ROOT/harness/coredns-overrides/restore.sh" "$BACKUP_FILE" || true

if command -v helm >/dev/null 2>&1; then
  helm uninstall "$RELEASE" --namespace "$NAMESPACE" >/dev/null 2>&1 || true
fi
if command -v kubectl >/dev/null 2>&1; then
  kubectl delete namespace "$NAMESPACE" --ignore-not-found --wait=true --timeout=120s >/dev/null 2>&1 || true
fi
