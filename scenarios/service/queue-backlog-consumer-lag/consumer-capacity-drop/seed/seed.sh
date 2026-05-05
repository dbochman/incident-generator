#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
OUTPUTS="$ROOT/evals/queue-backlog-fixtures/consumer-capacity-drop/outputs"
NAMESPACE="${SRE_AGENT_MESSAGING_NAMESPACE:-orders}"
SERVICE="${SRE_AGENT_MESSAGING_SERVICE:-fulfillment-consumer}"
QUEUE="${SRE_AGENT_MESSAGING_QUEUE:-orders.events}"
CONSUMER_GROUP="${SRE_AGENT_MESSAGING_CONSUMER_GROUP:-fulfillment}"

"$ROOT/harness/messaging-state-shell/apply.sh" \
  "$NAMESPACE" "$SERVICE" "$QUEUE" "$CONSUMER_GROUP" \
  "$OUTPUTS/recent_deploys.txt" \
  "$OUTPUTS/queue_consumer_lag.txt" \
  "$OUTPUTS/kafka_group_state.txt" \
  "$OUTPUTS/queue_dead_letter.txt" \
  "$OUTPUTS/error_logs.txt"
