#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:-default}"
PROBE_NAME="${2:-sre-agent-dns-tls-probe}"
PROBE_IMAGE="${SRE_AGENT_DNS_TLS_PROBE_IMAGE:-nicolaka/netshoot:v0.13}"
TIMEOUT="${SRE_AGENT_DNS_TLS_PROBE_TIMEOUT:-120s}"

command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NAMESPACE" apply -f - <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: ${PROBE_NAME}
  labels:
    app.kubernetes.io/name: sre-agent-dns-tls-probe
    app.kubernetes.io/instance: ${PROBE_NAME}
spec:
  restartPolicy: Always
  containers:
    - name: probe
      image: ${PROBE_IMAGE}
      imagePullPolicy: IfNotPresent
      command: ["sh", "-c", "sleep 3600"]
      resources:
        requests:
          cpu: 10m
          memory: 32Mi
        limits:
          memory: 128Mi
YAML

kubectl -n "$NAMESPACE" wait --for=condition=Ready "pod/$PROBE_NAME" --timeout="$TIMEOUT"
