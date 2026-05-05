#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

SCENARIOS=("$@")
if [ "${#SCENARIOS[@]}" -eq 0 ]; then
  SCENARIOS=(
    "scenarios/kubernetes/pending-pod/unschedulable"
    "scenarios/linux/disk-full/capacity"
  )
fi

"$PYTHON" -m incident_generator doctor

for scenario in "${SCENARIOS[@]}"; do
  "$PYTHON" -m incident_generator run \
    --root "$ROOT" \
    --scenario "$scenario" \
    --collection-mode real \
    --require-tools \
    --hold-seconds "${INCIDENT_GENERATOR_LIVE_SMOKE_HOLD_SECONDS:-0}" \
    --json
done
