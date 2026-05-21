# Docker Over SSH Runbook

Use Docker over SSH when the local host has the Docker CLI but cannot run or start a local Docker daemon. The live `kind` and `linux-vm` harnesses can target a remote Docker daemon through Docker's SSH transport.

## Preflight

Verify SSH and remote Docker access:

```sh
ssh <ssh-host> 'hostname; docker --version; docker compose version; docker info --format "{{.ServerVersion}} {{.OperatingSystem}} {{.Architecture}}"'
DOCKER_HOST=ssh://<ssh-host> docker info
```

The remote account must be able to run Docker without an interactive password prompt. If `DOCKER_HOST=ssh://<ssh-host> docker info` fails, fix SSH keys, host aliases, or remote Docker permissions before running real incidents.

You can create a named Docker context for ordinary Docker CLI use:

```sh
docker context create incident-remote --docker host=ssh://<ssh-host>
docker --context incident-remote ps
```

For this runner, prefer setting `DOCKER_HOST=ssh://<ssh-host>` explicitly. The `kind` harness detects that environment variable and opens an SSH tunnel back to the remote kind API server. A Docker context alone does not expose the SSH target to the harness scripts.

## Running Linux VM Incidents

```sh
DOCKER_HOST=ssh://<ssh-host> python3 -m incident_generator run \
  --scenario scenarios/linux/disk-full/capacity \
  --collection-mode real \
  --require-tools \
  --progress-json \
  --json
```

The Linux predicates run through `docker compose exec`, so they work against the remote daemon. Published provider ports such as `9090`, `3100`, `3200`, and `8081` are opened on the remote Docker host, not on the local client. If you need to inspect them locally, open SSH tunnels to the remote host.

## Running kind Incidents

```sh
DOCKER_HOST=ssh://<ssh-host> python3 -m incident_generator run \
  --scenario scenarios/kubernetes/pending-pod/unschedulable \
  --collection-mode real \
  --require-tools \
  --progress-json \
  --json
```

When `DOCKER_HOST` uses the `ssh://` form, `harness/archetypes/kind/up.sh` writes a local kubeconfig and starts an SSH tunnel for the remote API server port. Keep the same `DOCKER_HOST` value for cleanup commands.

## Cleanup

Run cleanup commands with the same remote Docker endpoint used for the incident:

```sh
DOCKER_HOST=ssh://<ssh-host> kind get clusters
DOCKER_HOST=ssh://<ssh-host> kind delete cluster --name "${SRE_AGENT_KIND_CLUSTER:-sre-agent-phase-a}"

COMPOSE_PROJECT_NAME="<compose-project-from-run-output>" \
  DOCKER_HOST=ssh://<ssh-host> \
  docker compose -f harness/archetypes/linux-vm/docker-compose.yaml down --remove-orphans --volumes
```

Also remove local kubeconfig and tunnel state if a kind run was interrupted:

```sh
rm -f .tmp/kubeconfig-kind-* .tmp/kubeconfig-sre-agent-phase-a .tmp/kubeconfig-*.tunnel.pid
```

## Caveats

- Remote Docker architecture matters. An `aarch64` Docker Desktop host may build or run different image variants than an `x86_64` local daemon.
- Docker bind mounts and build contexts are evaluated by the remote daemon. The current harness uses streamed builds for remote kind support and Docker Compose build contexts for `linux-vm`; verify a smoke run after changing Dockerfiles, Compose paths, or mount behavior.
- Do not use a production Docker daemon as the remote target. These harnesses intentionally create, mutate, and delete containers, volumes, and kind clusters.
