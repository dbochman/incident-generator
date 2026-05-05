#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 9 ]]; then
  echo "usage: apply.sh <namespace> <service> <queue> <consumer_group> <recent_deploys> <queue_lag> <kafka_state> <dead_letter> <error_logs> [configmap] [replicas]" >&2
  exit 2
fi

namespace="$1"
service="$2"
queue="$3"
consumer_group="$4"
recent_deploys="$5"
queue_lag="$6"
kafka_state="$7"
dead_letter="$8"
error_logs="$9"
configmap="${10:-sre-agent-messaging-evidence}"
replicas="${11:-1}"

command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 127; }

kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f -
python3 - "$namespace" "$service" "$queue" "$consumer_group" "$recent_deploys" "$queue_lag" "$kafka_state" "$dead_letter" "$error_logs" "$configmap" "$replicas" <<'PY' | kubectl apply -f -
from pathlib import Path
import sys
import yaml

namespace, service, queue, consumer_group, recent_deploys, queue_lag, kafka_state, dead_letter, error_logs, configmap, replicas = sys.argv[1:]


def read(path: str) -> str:
    candidate = Path(path)
    return candidate.read_text(encoding="utf-8") if candidate.is_file() else ""


documents = [
    {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": configmap,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/name": "messaging-state-shell",
                "service": service,
                "queue": queue,
                "consumer-group": consumer_group,
            },
        },
        "data": {
            "queue_consumer_lag.txt": read(queue_lag),
            "kafka_group_state.txt": read(kafka_state),
            "queue_dead_letter.txt": read(dead_letter),
            "error_logs.txt": read(error_logs),
        },
    },
    {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": service,
            "namespace": namespace,
            "labels": {"app": service, "service": service},
            "annotations": {
                "sre-agent.io/recent-deploys": read(recent_deploys),
                "sre-agent.io/deploy-metadata": f"service={service} queue={queue} consumer_group={consumer_group}",
            },
        },
        "spec": {
            "replicas": int(replicas),
            "selector": {"matchLabels": {"app": service}},
            "template": {
                "metadata": {"labels": {"app": service, "service": service}},
                "spec": {
                    "containers": [
                        {
                            "name": "pause",
                            "image": "registry.k8s.io/pause:3.10",
                            "resources": {
                                "requests": {"cpu": "5m", "memory": "16Mi"},
                                "limits": {"memory": "32Mi"},
                            },
                        }
                    ]
                },
            },
        },
    },
]
yaml.safe_dump_all(documents, sys.stdout, sort_keys=False)
PY
