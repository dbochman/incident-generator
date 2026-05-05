#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 4 ]]; then
  echo "usage: apply.sh <namespace> <deployment> <recent-deploys.txt> <deploy-metadata.txt> [replicas]" >&2
  exit 2
fi

namespace="$1"
deployment="$2"
recent_deploys="$3"
deploy_metadata="$4"
replicas="${5:-1}"

command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 127; }

kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f -
python3 - "$namespace" "$deployment" "$recent_deploys" "$deploy_metadata" "$replicas" <<'PY' | kubectl apply -f -
from pathlib import Path
import sys
import yaml

namespace, deployment, recent_path, metadata_path, replicas = sys.argv[1:]
manifest = {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "metadata": {
        "name": deployment,
        "namespace": namespace,
        "labels": {"app": deployment, "service": deployment},
        "annotations": {
            "sre-agent.io/recent-deploys": Path(recent_path).read_text(encoding="utf-8"),
            "sre-agent.io/deploy-metadata": Path(metadata_path).read_text(encoding="utf-8"),
        },
    },
    "spec": {
        "replicas": int(replicas),
        "selector": {"matchLabels": {"app": deployment}},
        "template": {
            "metadata": {"labels": {"app": deployment, "service": deployment}},
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
}
yaml.safe_dump(manifest, sys.stdout, sort_keys=False)
PY
