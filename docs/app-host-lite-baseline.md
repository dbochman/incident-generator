# App Host Lite Baseline

`harness/archetypes/linux-vm/` includes the shared `linux-vm/app-host-lite` baseline for production-like Linux benchmark scenarios.

The baseline runs inside `linux-target`, preserving the existing Docker Compose seed and evidence path. It adds a bounded worker supervisor, Docker healthcheck, health heartbeat, rotated application logs, journald-shaped log entries, temp-file churn, small disk writes, low CPU and memory background pressure, and benign service noise before incident injection.

Start the stack with the existing real-mode runner or directly:

```sh
docker compose -f harness/archetypes/linux-vm/docker-compose.yaml up --build -d
```

Stop it with:

```sh
docker compose -f harness/archetypes/linux-vm/docker-compose.yaml down --remove-orphans --volumes
```

The baseline defines the living Linux host before incident injection. It does not change existing Linux seeds, predicates, or provider rewrites; those continue to execute through `docker compose exec linux-target ...`.
