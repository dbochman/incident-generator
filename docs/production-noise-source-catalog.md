# Production Noise Source Catalog

`harness/production-noise-source-catalog.yaml` is the standalone package's canonical list of non-causal production-like signals for noisy benchmark runs.

The catalog maps ambient profiles to stable source IDs:

| Profile | Source IDs |
| --- | --- |
| `api-noise` | `http.benign_404`, `http.low_rate_5xx`, `http.retry`, `http.slow_normal_request`, `runtime.gc_log_churn`, `deploy.metadata_background`, `observability.scrape_noise` |
| `edge-noise` | `edge.dns_retry`, `edge.tls_probe`, `http.benign_404`, `http.low_rate_5xx`, `deploy.metadata_background` |
| `async-noise` | `async.queue_lag_blip`, `async.dead_letter_trickle`, `runtime.gc_log_churn`, `deploy.metadata_background`, `observability.scrape_noise` |
| `data-noise` | `database.connection_churn`, `database.slow_query_sample`, `http.retry`, `http.slow_normal_request`, `deploy.metadata_background`, `observability.scrape_noise` |
| `platform-noise` | `kubernetes.normal_event`, `observability.scrape_noise`, `runtime.gc_log_churn`, `deploy.metadata_background`, `http.benign_404` |
| `client-noise` | `http.retry`, `http.slow_normal_request`, `edge.dns_retry`, `http.benign_404`, `observability.scrape_noise` |
| `linux-noise` | `linux.healthcheck_heartbeat`, `linux.temp_disk_churn`, `runtime.gc_log_churn`, `http.benign_404`, `http.retry` |

Required source families include benign 404s, low-rate 5xxs, retries, slow-but-normal requests, GC/log churn, Kubernetes events, queue lag blips, database connection churn, DNS retries, and background deploy metadata. Each source records evidence adapters, live harness sources, fixture fields, and bounds so renderers can mix context without satisfying a causal incident hypothesis by itself. `incident_generator noisy-fixture` is the first manifest-level consumer. Internal role labels are defined in [evidence-signal-role-taxonomy.md](evidence-signal-role-taxonomy.md).
