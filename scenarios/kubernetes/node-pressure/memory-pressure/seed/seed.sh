#!/usr/bin/env bash
set -euo pipefail

node="$(kubectl get node -l '!node-role.kubernetes.io/control-plane' -o 'jsonpath={.items[0].metadata.name}')"
if [ -z "$node" ]; then
  echo "no worker node available for memory-pressure seed" >&2
  exit 1
fi

kubectl label node "$node" sre-agent.io/node-pressure=memory --overwrite
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
