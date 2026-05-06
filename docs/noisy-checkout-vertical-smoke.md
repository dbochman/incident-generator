# Noisy Checkout Vertical Smoke

`harness/noisy-checkout-vertical-smoke.yaml` defines the first checkout-api noisy smoke plan for fixture-mode benchmark previews.

Run the standalone report:

```sh
python3 -m incident_generator noisy-smoke --json
```

The report renders noisy fixture manifests for HTTP 5xx, latency, database pool exhaustion, pending pod, and network packet-loss checkout scenarios. It verifies the shared ecommerce-lite load profile, `checkout-api` main service, expected-hypothesis linkage, hidden internal role/source metadata, and required production-noise source coverage.

The full canonical repo also has `tools/run_noisy_checkout_smoke.py`, which appends the agent-visible noise to temporary fixtures and runs deterministic skill-agent replay.
