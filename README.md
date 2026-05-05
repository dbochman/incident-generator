# Incident Generator

Standalone deterministic incident environment generator for agent evaluation and benchmarking.

This repo was extracted from `sre-incident-agent-skills` and keeps the incident-generation surface independent from the original agent package:

- `scenarios/` contains 41 scenario packages across Kubernetes, Linux, service, database, and network domains.
- `harness/` contains the local `kind` and Docker Compose Linux VM harnesses plus supporting target apps.
- `evals/` and `skills/` provide deterministic fixture and benchmark metadata referenced by the scenario packages.
- `incident_generator/` contains the standalone Python runner for listing, validating, and generating environments.

## Quick Start

```sh
python3 -m incident_generator list
python3 -m incident_generator validate
python3 -m incident_generator run \
  --scenario scenarios/linux/disk-full/capacity \
  --collection-mode fixture \
  --json
```

Fixture mode is deterministic and does not start live infrastructure. Real mode starts the declared environment archetype, applies the scenario seed, waits for the symptom predicates, exposes provider endpoints where applicable, and tears down after the run.

```sh
python3 -m incident_generator doctor
python3 -m incident_generator run \
  --scenario scenarios/kubernetes/pending-pod/unschedulable \
  --collection-mode real \
  --variant k8s_version=1.29 \
  --require-tools \
  --hold
```

Use `--hold` only when you want to inspect the generated environment manually. Interrupt the process to trigger teardown.

## Git Privacy

This project is intended to remain private. The local repository has no remote configured by default, and the Python package is not published.

