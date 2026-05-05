# Live Cleanup Runbook

Use this runbook when a real-mode run exits with `teardown_failures`, is interrupted, or leaves local harness resources behind.

## Triage

Capture the failed run output first. The JSON result includes:

- `scenario`
- `collection_mode`
- `environment_archetype`
- `context.teardown.verified`
- `teardown_failures`
- `context.kubeconfig_path` or `context.compose_project` when applicable

Run the local preflight after cleanup to verify tool access:

```sh
python3 -m incident_generator doctor
```

## kind Cleanup

The default kind cluster name is `sre-agent-phase-a` unless `SRE_AGENT_KIND_CLUSTER` was set.

```sh
kind get clusters
kind delete cluster --name "${SRE_AGENT_KIND_CLUSTER:-sre-agent-phase-a}"
rm -f .tmp/kubeconfig-kind-* .tmp/kubeconfig-sre-agent-phase-a
```

Verify:

```sh
! kind get clusters | grep -Fx "${SRE_AGENT_KIND_CLUSTER:-sre-agent-phase-a}"
test ! -e .tmp/kubeconfig-sre-agent-phase-a
```

If port-forward processes remain, stop any command that references the generated kubeconfig:

```sh
ps -ef | grep 'kubectl.*port-forward' | grep 'SRE_AGENT_KIND_KUBECONFIG\|kubeconfig-kind' || true
```

## Linux VM Cleanup

The Compose project is `incident-generator-<scenario-name>`. The runner reports it as `context.compose_project`.

```sh
COMPOSE_PROJECT_NAME="<compose-project-from-run-output>" \
  docker compose -f harness/archetypes/linux-vm/docker-compose.yaml down --remove-orphans --volumes
```

Verify:

```sh
COMPOSE_PROJECT_NAME="<compose-project-from-run-output>" \
  docker compose -f harness/archetypes/linux-vm/docker-compose.yaml ps -q
docker volume ls --filter "label=com.docker.compose.project=<compose-project-from-run-output>" -q
```

Both commands should return no resources.

## EKS Staging

`eks-staging` remains blocked in the runner. If Terraform experiments are added later, cleanup must use the run-scoped `run_id` and sandbox account from the approval record. Do not run broad AWS deletion commands from this repo.

## Escalation Notes

- Keep failed run JSON and cleanup command output with the incident or release artifact.
- Treat any cleanup failure as release-blocking until the owner acknowledges it.
- Do not rerun the same live scenario against the same target until cleanup verification passes.
