#!/usr/bin/env bash
set -euo pipefail

node="sre-agent-memory-pressure"

kubectl label node -l 'sre-agent.io/node-pressure' sre-agent.io/node-pressure- --overwrite >/dev/null 2>&1 || true
kubectl delete node "$node" --ignore-not-found >/dev/null
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Node
metadata:
  name: ${node}
  labels:
    sre-agent.io/node-pressure: memory
    kubernetes.io/hostname: ${node}
EOF
uid="$(kubectl get node "$node" -o 'jsonpath={.metadata.uid}')"
timestamp="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

patch="$(cat <<JSON
{
  "status": {
    "conditions": [
      {"type":"Ready","status":"True","lastHeartbeatTime":"${timestamp}","lastTransitionTime":"${timestamp}","reason":"KubeletReady","message":"kubelet is posting ready status"},
      {"type":"MemoryPressure","status":"True","lastHeartbeatTime":"${timestamp}","lastTransitionTime":"${timestamp}","reason":"KubeletHasInsufficientMemory","message":"kubelet has insufficient memory available"},
      {"type":"DiskPressure","status":"False","lastHeartbeatTime":"${timestamp}","lastTransitionTime":"${timestamp}","reason":"KubeletHasNoDiskPressure","message":"kubelet has no disk pressure"},
      {"type":"PIDPressure","status":"False","lastHeartbeatTime":"${timestamp}","lastTransitionTime":"${timestamp}","reason":"KubeletHasSufficientPID","message":"kubelet has sufficient PID available"}
    ]
  }
}
JSON
)"
kubectl patch node "$node" --subresource=status --type=merge -p "$patch"

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Event
metadata:
  name: ${node}.memory-pressure
  namespace: default
involvedObject:
  apiVersion: v1
  kind: Node
  name: ${node}
  uid: ${uid}
reason: EvictionThresholdMet
message: "kubelet Memory available below hard eviction threshold"
source:
  component: kubelet
firstTimestamp: "${timestamp}"
lastTimestamp: "${timestamp}"
count: 1
type: Warning
EOF
