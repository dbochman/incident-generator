# Incident Generator Artifact Registry

- Registry: `benchmark-artifacts/registry.json`
- Schema: `incident-generator.artifact-registry/v1`
- Entries: 4
- Check: pass (0 errors, 0 warnings)

## Entries

| Run ID | Benchmark Set | Seed | Scenarios | Size | Mode | Host | State | Failure Class | Artifacts |
| --- | --- | ---: | --- | ---: | --- | --- | --- | --- | ---: |
| 20260506-kind-random8-warm-rerun | kind-random8-warm-20260506 | 20260506 | database-connection-exhaustion-connection-storm, service-certificate-rotation-readiness-expired, kubernetes-crashloopbackoff-config, service-kafka-rebalance-deploy-induced-rebalance, kubernetes-crashloopbackoff-dependency, service-queue-backlog-consumer-lag-dead-letter-backlog, kubernetes-pending-pod-taint-mismatch, service-deployment-rollback-decision-dependency-no-rollback, service-http-5xx-spike-canary-rollout, network-path-degradation-high-latency-hop, service-deployment-rollback-decision-insufficient-rollback-evidence, service-kafka-rebalance-partition-skew, service-kafka-rebalance-rebalance-stall, service-queue-backlog-consumer-lag-consumer-lag-backlog | 2 | kind/real | kind/warm-batch (ssh) | passed | none | 6 |
| 20260506-kind-random16-warm | kind-random16-warm-20260506 | 20260506 | database-connection-exhaustion-connection-storm, service-certificate-rotation-readiness-expired, service-deployment-rollback-decision-rollback-candidate, database-connection-exhaustion-pool-exhausted, service-latency-spike-downstream-db, kubernetes-crashloopbackoff-config, service-certificate-rotation-readiness-hostname-mismatch, service-kafka-rebalance-deploy-induced-rebalance, kubernetes-crashloopbackoff-dependency, kubernetes-node-pressure-disk-pressure, service-queue-backlog-consumer-lag-dead-letter-backlog, kubernetes-node-pressure-memory-pressure, kubernetes-pending-pod-pvc-unbound, service-http-5xx-spike-dependency, kubernetes-pending-pod-taint-mismatch, service-deployment-rollback-decision-dependency-no-rollback, service-dns-tls-failure-nxdomain, service-http-5xx-spike-canary-rollout, network-path-degradation-high-latency-hop, service-deployment-rollback-decision-insufficient-rollback-evidence, service-kafka-rebalance-partition-skew, service-dns-tls-failure-expired, service-kafka-rebalance-rebalance-stall, service-queue-backlog-consumer-lag-consumer-lag-backlog | 2 | kind/real | kind/warm-batch (ssh) | passed | none | 6 |
| 20260506-noisy-live-checkout-canary-5xx | noisy-checkout-live-20260506 | 20260506 | service-http-5xx-spike-canary-rollout | 1 | kind/real | kind/ecommerce-lite/noisy-live (ssh) | generated | none | 8 |
| 20260506-noisy-live-database-pool-exhausted | noisy-database-live-20260506 | 20260506 | database-connection-exhaustion-pool-exhausted | 1 | kind/real | kind/ecommerce-lite/noisy-live (ssh) | generated | none | 8 |
