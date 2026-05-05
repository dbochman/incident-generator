#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
NAMESPACE="${SRE_AGENT_ROLLBACK_NAMESPACE:-payments}"
DEPLOYMENT="${SRE_AGENT_ROLLBACK_DEPLOYMENT:-checkout-api}"

"$ROOT/harness/deployment-metadata-shell/apply.sh" "$NAMESPACE" "$DEPLOYMENT" "$SCRIPT_DIR/recent-deploys.txt" "$SCRIPT_DIR/deploy-metadata.txt"
