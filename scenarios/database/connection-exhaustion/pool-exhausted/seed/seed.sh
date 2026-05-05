#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
NAMESPACE="${SRE_AGENT_DATABASE_NAMESPACE:-payments}"
POSTGRES_RELEASE="${SRE_AGENT_DATABASE_RELEASE:-checkout-postgres}"
LOADGEN_RELEASE="${SRE_AGENT_DATABASE_LOADGEN_RELEASE:-checkout-postgres-loadgen}"

"$ROOT/harness/shared/seed-helm.sh" "$POSTGRES_RELEASE" "$ROOT/harness/postgres-target/chart" "$NAMESPACE" "$SCRIPT_DIR/postgres-values.yaml"
"$ROOT/harness/shared/seed-helm.sh" "$LOADGEN_RELEASE" "$ROOT/harness/pgbench-loadgen/chart" "$NAMESPACE" "$SCRIPT_DIR/loadgen-values.yaml"
