#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
NAMESPACE="${SRE_AGENT_MESSAGING_NAMESPACE:-commerce}"
SERVICE="${SRE_AGENT_MESSAGING_SERVICE:-inventory-consumer}"

"$ROOT/harness/messaging-state-shell/teardown.sh" "$NAMESPACE" "$SERVICE"
