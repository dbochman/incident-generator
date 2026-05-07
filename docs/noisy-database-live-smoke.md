# Noisy Database Live Smoke Setup

`harness/noisy-database-live-smoke.yaml` defines the first production-like noisy database live target after the checkout canary. It scopes the first non-service live noisy domain to one database incident so the retained run can reuse the existing `incident_generator noisy-live-result` payload shape.

| Scenario | Workload path | Noise profile | Expected hypothesis |
| --- | --- | --- | --- |
| `database-connection-exhaustion-pool-exhausted` | `kind/ecommerce-lite/data` | `data-noise` | `pool_exhausted` |

The setup uses `checkout-api` under the same ecommerce-lite 60-second warm-up and 24 RPS load-generator profile as the first noisy live canary. The smoke plan requires data-path ambient sources for normal connection churn, slow-but-acceptable query samples, retries, slow normal requests, background deploy metadata, and observability scrape noise. The retained live run sets `SRE_AGENT_DATABASE_NAMESPACE=ecommerce` so the pool-exhaustion seed targets the same namespace as the noisy ecommerce workload.

## Fixture Gate

Render the deterministic noisy smoke report before starting live infrastructure:

```sh
python3 -m incident_generator --root . noisy-smoke \
  --smoke harness/noisy-database-live-smoke.yaml \
  --json
```

The report includes a `live_replay_contract` with:

- benchmark set id `noisy-database-live-20260506`;
- run id `20260506-noisy-live-database-pool-exhausted`;
- retained artifact directory `benchmark-artifacts/runs/20260506-noisy-live-database-pool-exhausted`;
- the required retained files for registry and replay validation;
- the exact `noisy-live-result` replay command for the retained run.

## Operator Flow

After the fixture gate passes, retain the live run under the contract directory:

```sh
mkdir -p benchmark-artifacts/runs/20260506-noisy-live-database-pool-exhausted

python3 -m incident_generator --root . noisy-smoke \
  --smoke harness/noisy-database-live-smoke.yaml \
  --json \
  > benchmark-artifacts/runs/20260506-noisy-live-database-pool-exhausted/noisy-smoke-report.json

harness/ecommerce-lite/loadgen-preview.py \
  > benchmark-artifacts/runs/20260506-noisy-live-database-pool-exhausted/loadgen-preview.json

DOCKER_HOST=ssh://JYW4HTC26N \
harness/archetypes/kind/up.sh

DOCKER_HOST=ssh://JYW4HTC26N \
harness/archetypes/kind/install-observability.sh

DOCKER_HOST=ssh://JYW4HTC26N \
harness/ecommerce-lite/apply.sh

DOCKER_HOST=ssh://JYW4HTC26N \
SRE_AGENT_ECOMMERCE_LOADGEN_PREVIEW=$PWD/benchmark-artifacts/runs/20260506-noisy-live-database-pool-exhausted/loadgen-preview.json \
harness/ecommerce-lite/apply-loadgen.sh

DOCKER_HOST=ssh://JYW4HTC26N \
SRE_AGENT_DATABASE_NAMESPACE=ecommerce \
SRE_AGENT_OBSERVABILITY_REUSE_READY=1 \
SRE_AGENT_KIND_KEEP_CLUSTER=1 \
python3 -m incident_generator --root . run \
  --scenario scenarios/database/connection-exhaustion/pool-exhausted \
  --collection-mode real \
  --require-tools \
  --progress-json \
  --progress-artifact-dir benchmark-artifacts/runs/20260506-noisy-live-database-pool-exhausted \
  --incident-session-id 20260506-noisy-live-database-pool-exhausted \
  --hold-seconds 5 \
  --json
```

After the generator exits, tear down the load generator, ecommerce baseline, and kind cluster, then retain `cleanup-summary.json`. The 2026-05-06 operator run matched the database wait predicate at `connection_count=72.0`, generated with `failure_class=none`, and verified final cluster absence.

Register the retained run after cleanup artifacts are present:

```sh
python3 -m incident_generator --root . artifact-registry add \
  --registry benchmark-artifacts/registry.json \
  --artifact-dir benchmark-artifacts/runs/20260506-noisy-live-database-pool-exhausted \
  --benchmark-set-id noisy-database-live-20260506 \
  --run-id 20260506-noisy-live-database-pool-exhausted \
  --seed 20260506 \
  --host-profile kind/ecommerce-lite/noisy-live \
  --docker-host-kind ssh \
  --docker-host ssh://JYW4HTC26N \
  --env SRE_AGENT_DATABASE_NAMESPACE=ecommerce \
  --env SRE_AGENT_OBSERVABILITY_REUSE_READY=1 \
  --env SRE_AGENT_KIND_KEEP_CLUSTER=1 \
  --command "python3 -m incident_generator --root . run --scenario scenarios/database/connection-exhaustion/pool-exhausted --collection-mode real --require-tools --progress-json --progress-artifact-dir benchmark-artifacts/runs/20260506-noisy-live-database-pool-exhausted --incident-session-id 20260506-noisy-live-database-pool-exhausted --hold-seconds 5 --json" \
  --json
```

Then emit the schema-backed replay payload:

```sh
python3 -m incident_generator --root . noisy-live-result \
  --run-id 20260506-noisy-live-database-pool-exhausted \
  --benchmark-set-id noisy-database-live-20260506 \
  --json
```

The replay path is intentionally the same as the checkout canary: it verifies registry hashes, `result.json`, the noisy smoke report, loadgen metadata, cleanup state, required abstention, false-attribution guards, and evidence-role counts without rerunning live infrastructure.

## Retained Result

The retained `20260506-noisy-live-database-pool-exhausted` run is registered as `noisy-database-live-20260506`. The emitted payload reports `passed_count=1`, `failed_count=0`, `required_abstentions=1`, `abstentions_observed=1`, `judge_passed_count=1`, and `overall_pass=true`.
