# Ecommerce Lite Baseline

`harness/ecommerce-lite/` defines the shared `kind` main-app baseline for production-like non-Linux benchmark scenarios.

It installs:

- HTTP services for `storefront`, `api-gateway`, `checkout-api`, `search-api`, `profile-api`, and `edge-api` using the existing `sre-agent/misbehaving-app:local` image with healthy defaults;
- thin Postgres plus pgbench background load for benign database activity;
- lightweight async/Kafka role pods plus benign messaging-state evidence;
- ServiceMonitors, health checks, workload labels, and deploy metadata annotations;
- a seedable traffic profile ConfigMap consumed by the optional load-generator slice.

Install on a ready kind harness:

```sh
harness/ecommerce-lite/apply.sh
```

Remove it with:

```sh
harness/ecommerce-lite/teardown.sh
```

The baseline defines the living system before incident injection. The sustained traffic generator is disabled by default and enabled through `harness/ecommerce-lite/apply-loadgen.sh`; the checked traffic profile records seed, warm-up seconds, RPS/concurrency, request mix, dependency fanout, and retry behavior.
