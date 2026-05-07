# Noisy Checkout Vertical Smoke

`harness/noisy-checkout-vertical-smoke.yaml` defines the first checkout-api noisy smoke plan for fixture-mode benchmark previews.

Run the standalone report:

```sh
python3 -m incident_generator noisy-smoke --json
```

The report renders noisy fixture manifests for HTTP 5xx, latency, database pool exhaustion, pending pod, and network packet-loss checkout scenarios. It verifies the shared ecommerce-lite load profile, `checkout-api` main service, expected-hypothesis linkage, hidden internal role/source metadata, and required production-noise source coverage.

The full canonical repo also has `tools/run_noisy_checkout_smoke.py`, which appends the agent-visible noise to temporary fixtures and runs deterministic skill-agent replay.

The canonical repo retains the first live noisy checkout run as `20260506-noisy-live-checkout-canary-5xx` in the benchmark artifact registry. That run installed ecommerce-lite, warmed the 24 RPS load generator for 60 seconds, rendered this noisy smoke report, and generated `service-http-5xx-spike-canary-rollout` under live load with `failure_class=none`.

`python3 -m incident_generator noisy-live-result` converts the retained noisy live registry entry into `incident-generator.benchmark-result/v1` without rerunning live infrastructure.

## Database Domain Run

[noisy-database-live-smoke.md](noisy-database-live-smoke.md) defines the first scoped database live target using the same payload shape: `database-connection-exhaustion-pool-exhausted` under ecommerce-lite data-path noise. The retained run `20260506-noisy-live-database-pool-exhausted` is indexed as `noisy-database-live-20260506` and replays through `incident_generator noisy-live-result` without rerunning live infrastructure.
