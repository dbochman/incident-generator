#!/usr/bin/env bash
set -euo pipefail

kubectl delete event sre-agent-memory-pressure.memory-pressure -n default --ignore-not-found >/dev/null
kubectl delete node sre-agent-memory-pressure --ignore-not-found >/dev/null
kubectl label node -l 'sre-agent.io/node-pressure=memory' sre-agent.io/node-pressure- --overwrite >/dev/null 2>&1 || true
