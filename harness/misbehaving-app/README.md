# Misbehaving App

`misbehaving-app` is a deterministic HTTP workload for service-domain live scenarios. It exposes `/healthz`, `/readyz`, `/api/v1/checkout/{order_id}`, and `/metrics`, and it emits JSON logs on stdout.

## Knobs

| Env var | Default | Purpose |
| --- | --- | --- |
| `MISBEHAVE_SERVICE_NAME` | `checkout-api` | Service name included in structured logs. |
| `MISBEHAVE_ROUTE_LABEL` | `/api/v1/checkout` | Bounded route label used in logs and metrics. |
| `MISBEHAVE_5XX_RATIO` | `0.0` | Deterministic fraction of checkout requests that return 503. |
| `MISBEHAVE_LATENCY_BASE_MS` | `25` | Baseline checkout response latency. |
| `MISBEHAVE_LATENCY_P99_MS` | `50` | Deterministic 1% tail latency. |
| `MISBEHAVE_DEPLOY_TIME` | startup time | `app_info` deploy-time label. |
| `MISBEHAVE_VERSION` | `v0.0.0` | Response, log, and `app_info` version. |
| `MISBEHAVE_READY_DELAY_S` | `0` | Readiness warmup delay. |
| `MISBEHAVE_DEPENDENCY_5XX_RATIO` | `0.0` | Deterministic fraction of requests that emit downstream error logs without changing response status. |
| `MISBEHAVE_DEPENDENCY_NAME` | `checkout-db` | Downstream name used in dependency error and latency logs. |
| `MISBEHAVE_DEPENDENCY_LATENCY_MS` | `0` | Emits a deterministic downstream slow-query log line when non-zero. |
| `MISBEHAVE_ERROR_MESSAGE` | `upstream_unavailable` | Error body/log message, intentionally unsanitized for adversarial fixtures. |

The Helm chart in `chart/` is installed by scenario seed scripts; the observability install only builds and loads the image into kind.
