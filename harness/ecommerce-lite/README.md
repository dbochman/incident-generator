# Ecommerce Lite Baseline

`ecommerce-lite` is the low-footprint `kind` workload baseline for production-like incident-generator benchmark slices. It gives non-Linux scenarios a living service graph before causal injection starts:

- `storefront`, `api-gateway`, `checkout-api`, `search-api`, `profile-api`, and `edge-api` HTTP services run on the existing `sre-agent/misbehaving-app:local` image with healthy defaults.
- `checkout-postgres` and `checkout-postgres-loadgen` reuse the thin Postgres and pgbench charts with non-saturating background query load.
- `checkout-events-producer`, `checkout-events-consumer`, `profile-events-consumer`, and `kafka-broker` are lightweight async-role pods with benign queue/Kafka evidence.
- `ecommerce-lite-loadgen` is optional and drives the checked traffic profile when `apply-loadgen.sh` is run.
- ServiceMonitor resources, readiness/liveness probes, deploy annotations, and stable workload labels make the baseline visible to the existing provider adapters.

Install it into a ready `kind` harness after observability is installed:

```sh
harness/ecommerce-lite/apply.sh
```

Remove it with:

```sh
harness/ecommerce-lite/teardown.sh
```

The checked-in `trafficProfile` in `chart/values.yaml` records seed, warm-up seconds, RPS/concurrency, traffic mix, dependency fanout, and retry behavior. The baseline install keeps sustained HTTP traffic disabled until the load generator is explicitly enabled.
Preview and start sustained traffic with:

```sh
harness/ecommerce-lite/loadgen-preview.py --limit 30
harness/ecommerce-lite/apply-loadgen.sh
```

Stop only the HTTP load generator with:

```sh
harness/ecommerce-lite/teardown-loadgen.sh
```
