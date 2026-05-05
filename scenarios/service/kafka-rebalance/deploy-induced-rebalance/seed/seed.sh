#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
OUTPUTS="$ROOT/evals/kafka-rebalance-fixtures/deploy-induced-rebalance/outputs"
NAMESPACE="${SRE_AGENT_MESSAGING_NAMESPACE:-commerce}"
SERVICE="${SRE_AGENT_MESSAGING_SERVICE:-inventory-consumer}"
QUEUE="${SRE_AGENT_MESSAGING_QUEUE:-inventory.events}"
CONSUMER_GROUP="${SRE_AGENT_MESSAGING_CONSUMER_GROUP:-inventory-indexer}"

"$ROOT/harness/messaging-state-shell/apply.sh" \
  "$NAMESPACE" "$SERVICE" "$QUEUE" "$CONSUMER_GROUP" \
  "$OUTPUTS/recent_deploys.txt" \
  "$OUTPUTS/queue_consumer_lag.txt" \
  "$OUTPUTS/kafka_group_state.txt" \
  "$OUTPUTS/queue_dead_letter.txt" \
  "$OUTPUTS/error_logs.txt"
