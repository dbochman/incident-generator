# Ecommerce Lite Load Generator

`harness/ecommerce-lite/loadgen-preview.py` renders a deterministic request preview from the ecommerce-lite `trafficProfile`: seed, warm-up seconds, RPS, concurrency, route mix, dependency fanout, retry behavior, route counts, and first request URLs.

`harness/ecommerce-lite/apply-loadgen.sh` enables the optional ecommerce-lite Helm load-generator Deployment, waits for rollout, then waits the configured warm-up before returning so incident injection can start against a warm main app. `harness/ecommerce-lite/teardown-loadgen.sh` removes only the load-generator Deployment and ConfigMap.

The live runner and preview share the same Python planner in `harness/ecommerce-lite/chart/files/loadgen_runner.py`.

The normal traffic, retry, slow request, and edge request signals produced by this generator are cataloged as non-causal production noise in [production-noise-source-catalog.md](production-noise-source-catalog.md).
