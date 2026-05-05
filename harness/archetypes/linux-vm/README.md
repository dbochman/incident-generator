# Linux VM Archetype

This archetype is a runnable local real-environment target for Linux host
incidents. It uses Docker Compose to start:

- `linux-target`: the fault-injected host container.
- `prometheus`: local metrics collection.
- `loki`: local log storage.
- `tempo`: local trace storage.
- `fake-pagerduty`: local incident API capture.

The standalone runner checks for Docker and Docker Compose v2, starts the
Compose project with a scenario-specific project name, copies executable seed
scripts into the target container, waits for Linux predicates in `expect.yaml`,
and tears down the project with volumes when the run exits.

Example:

```sh
python3 -m incident_generator doctor
python3 -m incident_generator run \
  --scenario scenarios/linux/disk-full/capacity \
  --collection-mode real \
  --require-tools
```

Set `INCIDENT_GENERATOR_LINUX_VM_REBUILD=1` when you need to rebuild the local
target and observability images before a run.
