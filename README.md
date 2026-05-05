# Incident Generator

Standalone deterministic incident environment generator for agent evaluation and benchmarking.

This repo was extracted from `sre-incident-agent-skills` and keeps the incident-generation surface independent from the original agent package. It provides:

- `scenarios/` contains 41 scenario packages across Kubernetes, Linux, service, database, and network domains.
- `harness/` contains the local `kind` and Docker Compose Linux VM harnesses plus supporting target apps.
- `evals/` and `skills/` provide deterministic fixture and benchmark metadata referenced by the scenario packages.
- `incident_generator/` contains the standalone Python runner for listing, validating, and generating environments.

Fixture mode is the default and uses checked-in evidence. Real mode starts the declared environment archetype, applies the scenario seed, waits for symptom predicates, exposes provider endpoints where applicable, and tears down after the run.

For the production readiness plan, see [docs/production-roadmap.md](docs/production-roadmap.md).

## Quick Start

```sh
python3 -m incident_generator list
python3 -m incident_generator catalog
python3 -m incident_generator validate
python3 -m incident_generator run \
  --scenario scenarios/linux/disk-full/capacity \
  --collection-mode fixture \
  --json
```

Use `--hold` only when you want to inspect a generated real environment manually. Interrupt the process to trigger teardown.

```sh
python3 -m incident_generator doctor
python3 -m incident_generator run \
  --scenario scenarios/kubernetes/pending-pod/unschedulable \
  --collection-mode real \
  --variant k8s_version=1.29 \
  --require-tools \
  --progress \
  --hold
```

If a local live archetype is missing required tools, real mode falls back to fixture mode unless `--require-tools` is set.

## CLI Surface

| Command | Purpose |
| --- | --- |
| `python3 -m incident_generator list` | List scenario packages and their default variants. |
| `python3 -m incident_generator catalog` | Report scenario coverage by domain, archetype, evidence adapter, and live-readiness state. |
| `python3 -m incident_generator validate` | Validate scenario package structure, fixtures, executable hooks, and benchmark assets. |
| `python3 -m incident_generator run` | Generate one fixture-backed or real incident environment. |
| `python3 -m incident_generator doctor` | Report local tool availability for real modes. |
| `python3 -m incident_generator docs-check` | Check repository Markdown links. |
| `python3 -m incident_generator fixture-hygiene` | Scan fixture files for unallowlisted secrets and prompt-injection spillover. |
| `python3 -m incident_generator release-manifest` | Generate a release manifest with catalog and artifact hashes. |

`run` supports operator progress output for real-mode inspection:

- `--progress` emits a human-readable lifecycle timeline to stderr.
- `--progress-json` emits newline-delimited JSON progress events to stderr.
- `--progress-artifact-dir <dir>` writes `events.ndjson` and `summary.json`; when omitted with progress enabled, artifacts go under `.tmp/incidents/<incident-session-id>/`.

Progress events cover validation, archetype startup, seed application, provider port-forwards, wait predicate observations, selector resolution, holds, teardown, and cleanup verification. Final `--json` output remains on stdout so automation can parse it separately from progress.

The `Makefile` wraps the local development gates:

```sh
make list
make catalog
make validate
make smoke
make doctor
make docs-check
make fixture-hygiene
make lint
make test
make package
make release-manifest
make release-check
```

## Scenario Package Anatomy

Each scenario directory contains a `scenario.yaml` contract plus supporting assets:

- `scenario.yaml`: metadata, target skill, fixture path, environment archetype, inputs, required evidence adapters, expected hypotheses and actions, forbidden actions, success criteria, latency budget, variants, and optional cross-incident metadata.
- `expect.yaml`: wait predicates and expected behavior used by real-mode symptom checks.
- `infra/`: scenario-specific environment notes.
- `seed/`: manifests or scripts that create the incident state.
- `inject.sh` and `cleanup.sh`: executable hooks required by validation.

The runner currently supports the `fixture`, `kind`, and `linux-vm` archetypes. The `eks-staging` Terraform skeleton exists under `harness/archetypes/eks-staging/`, but runner dispatch for that archetype is intentionally not implemented yet.

## Live Harnesses

`kind` scenarios use an isolated kubeconfig under `.tmp/`, install local observability components, apply the scenario seed, start port-forwards for provider endpoints, wait for configured predicates, and tear down the cluster.

`linux-vm` scenarios use Docker Compose to run a target Linux container plus local Prometheus and Tempo services. Scenario seeds are copied into the target container before execution, and cleanup removes the Compose project and volumes.

Before using real mode, run:

```sh
python3 -m incident_generator doctor
```

Real mode is for controlled harnesses and staging-like environments. Do not point scenario seeds at production infrastructure without completing the production gates in [docs/production-roadmap.md](docs/production-roadmap.md).

Real-mode JSON results include `teardown_failures` and `context.teardown` when live infrastructure was attempted, so operators can verify whether cleanup completed.

For failed cleanup, use [docs/runbooks/live-cleanup.md](docs/runbooks/live-cleanup.md). For approved operator-run live smoke checks, use `make live-smoke PYTHON=/path/to/python3.10-or-newer`.

## Development Notes

Run the deterministic gates before changing scenario contracts, runner behavior, or fixture paths:

```sh
make validate
make smoke
make docs-check
make fixture-hygiene
make lint
make test
```

Use `make release-check` before cutting an internal release candidate. It runs syntax checks, strict scenario validation, catalog reporting, fixture smoke, docs link checks, fixture hygiene, unit tests, a wheel build, and release manifest generation. Set `PYTHON=/path/to/python3.10-or-newer` if the system `python3` is older than the package requirement.

When adding a scenario:

1. Add the `scenario.yaml`, `expect.yaml`, `infra/`, `seed/`, `inject.sh`, and `cleanup.sh` files.
2. Link a fixture directory with `fixture.yaml` and `outputs/`.
3. Link the skill under test and required evidence adapters.
4. Add or update the relevant eval fixture and rubric metadata.
5. Run `python3 -m incident_generator validate --scenario <scenario-dir>`.

## Git Privacy

This project is intended to remain private. The local repository has no remote configured by default, and the Python package is not published.
