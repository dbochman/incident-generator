# Incident Generator Progress Dashboard

Status: `ok`
Failure class: `none`
Elapsed: `48:03`

## Phase Timing

| Phase | Status | Events | First | Last | Duration | Last message |
| --- | --- | ---: | --- | --- | --- | --- |
| `run` | `ok` | 32 | `00:00` | `47:43` | `47:43` | incident generation complete |
| `validate` | `ok` | 32 | `00:00` | `46:25` | `46:25` | combinatorial scenario contract is valid |
| `archetype` | `ok` | 32 | `00:00` | `47:22` | `47:22` | kind ready |
| `seed` | `ok` | 64 | `10:49` | `47:27` | `36:38` | scenario seed applied: service-queue-backlog-consumer-lag-consumer-lag-backlog |
| `port_forward` | `ok` | 32 | `11:41` | `47:33` | `35:52` | provider port-forwards ready |
| `providers` | `ok` | 16 | `11:46` | `47:33` | `35:46` | provider endpoints available |
| `wait_for` | `ok` | 141 | `11:46` | `47:34` | `35:48` | all wait predicates matched |
| `selector` | `ok` | 64 | `12:00` | `47:34` | `35:34` | selectors resolved: service-queue-backlog-consumer-lag-consumer-lag-backlog |
| `teardown` | `ok` | 176 | `12:00` | `47:43` | `35:43` | teardown verified |
| `warm_kind_cleanup` | `ok` | 2 | `47:43` | `48:03` | `00:19` | retained kind cluster deleted |
| `batch` | `ok` | 1 | `48:03` | `48:03` | `00:00` | combinatorial batch complete |

## Runtime State

- archetype: `kind`
- cluster: `sre-agent-phase-a`
- docker_host: `ssh://JYW4HTC26N`
- kubeconfig_path: `/home/dbochman/repos/sre-incident-agent-skills/.tmp/kubeconfig-kind-5af89_kv`

### Containers

| Name | Image | Status |
| --- | --- | --- |
| sre-agent-phase-a-worker2 | kindest/node:v1.35.0 | Up 46 minutes |
| sre-agent-phase-a-worker | kindest/node:v1.35.0 | Up 46 minutes |
| sre-agent-phase-a-control-plane | kindest/node:v1.35.0 | Up 46 minutes |

### Images

No entries yet.

## Seed Checkpoints

| Scenario | Status | Applied | Elapsed |
| --- | --- | --- | --- |
| database-connection-exhaustion-connection-storm | started | - | 10:49 |
| database-connection-exhaustion-connection-storm | ok | True | 11:11 |
| service-certificate-rotation-readiness-expired | started | - | 11:11 |
| service-certificate-rotation-readiness-expired | ok | True | 11:41 |
| database-connection-exhaustion-connection-storm | started | - | 13:53 |
| database-connection-exhaustion-connection-storm | ok | True | 14:06 |
| service-deployment-rollback-decision-rollback-candidate | started | - | 14:06 |
| service-deployment-rollback-decision-rollback-candidate | ok | True | 14:08 |
| database-connection-exhaustion-pool-exhausted | started | - | 15:28 |
| database-connection-exhaustion-pool-exhausted | ok | True | 15:41 |
| service-latency-spike-downstream-db | started | - | 15:41 |
| service-latency-spike-downstream-db | ok | True | 16:18 |
| kubernetes-crashloopbackoff-config | started | - | 19:11 |
| kubernetes-crashloopbackoff-config | ok | True | 19:12 |
| service-certificate-rotation-readiness-hostname-mismatch | started | - | 19:12 |
| service-certificate-rotation-readiness-hostname-mismatch | ok | True | 19:33 |
| kubernetes-crashloopbackoff-config | started | - | 21:37 |
| kubernetes-crashloopbackoff-config | ok | True | 21:38 |
| service-kafka-rebalance-deploy-induced-rebalance | started | - | 21:38 |
| service-kafka-rebalance-deploy-induced-rebalance | ok | True | 21:41 |
| kubernetes-crashloopbackoff-dependency | started | - | 23:09 |
| kubernetes-crashloopbackoff-dependency | ok | True | 23:11 |
| kubernetes-node-pressure-disk-pressure | started | - | 23:11 |
| kubernetes-node-pressure-disk-pressure | ok | True | 23:15 |
| kubernetes-crashloopbackoff-dependency | started | - | 24:36 |
| kubernetes-crashloopbackoff-dependency | ok | True | 24:38 |
| service-queue-backlog-consumer-lag-dead-letter-backlog | started | - | 24:38 |
| service-queue-backlog-consumer-lag-dead-letter-backlog | ok | True | 24:40 |
| kubernetes-node-pressure-memory-pressure | started | - | 26:04 |
| kubernetes-node-pressure-memory-pressure | ok | True | 26:09 |
| service-latency-spike-downstream-db | started | - | 26:09 |
| service-latency-spike-downstream-db | ok | True | 26:46 |
| kubernetes-pending-pod-pvc-unbound | started | - | 30:09 |
| kubernetes-pending-pod-pvc-unbound | ok | True | 30:11 |
| service-http-5xx-spike-dependency | started | - | 30:11 |
| service-http-5xx-spike-dependency | ok | True | 31:11 |
| kubernetes-pending-pod-taint-mismatch | started | - | 34:30 |
| kubernetes-pending-pod-taint-mismatch | ok | True | 34:31 |
| service-deployment-rollback-decision-dependency-no-rollback | started | - | 34:31 |
| service-deployment-rollback-decision-dependency-no-rollback | ok | True | 34:33 |
| kubernetes-pending-pod-taint-mismatch | started | - | 35:52 |
| kubernetes-pending-pod-taint-mismatch | ok | True | 35:54 |
| service-dns-tls-failure-nxdomain | started | - | 35:54 |
| service-dns-tls-failure-nxdomain | ok | True | 36:01 |
| kubernetes-pending-pod-taint-mismatch | started | - | 37:23 |
| kubernetes-pending-pod-taint-mismatch | ok | True | 37:24 |
| service-http-5xx-spike-canary-rollout | started | - | 37:24 |
| service-http-5xx-spike-canary-rollout | ok | True | 37:55 |
| network-path-degradation-high-latency-hop | started | - | 39:17 |
| network-path-degradation-high-latency-hop | ok | True | 41:04 |
| service-deployment-rollback-decision-insufficient-rollback-evidence | started | - | 41:04 |
| service-deployment-rollback-decision-insufficient-rollback-evidence | ok | True | 41:06 |
| network-path-degradation-high-latency-hop | started | - | 42:23 |
| network-path-degradation-high-latency-hop | ok | True | 43:17 |
| service-kafka-rebalance-partition-skew | started | - | 43:17 |
| service-kafka-rebalance-partition-skew | ok | True | 43:20 |
| service-certificate-rotation-readiness-expired | started | - | 44:36 |
| service-certificate-rotation-readiness-expired | ok | True | 44:57 |
| service-dns-tls-failure-expired | started | - | 44:57 |
| service-dns-tls-failure-expired | ok | True | 45:19 |
| service-kafka-rebalance-rebalance-stall | started | - | 47:22 |
| service-kafka-rebalance-rebalance-stall | ok | True | 47:25 |
| service-queue-backlog-consumer-lag-consumer-lag-backlog | started | - | 47:25 |
| service-queue-backlog-consumer-lag-consumer-lag-backlog | ok | True | 47:27 |

## Wait Predicates

| Scenario | Kind | Status | Matched | Observed |
| --- | --- | --- | --- | --- |
| database-connection-exhaustion-connection-storm | - | started | - |  |
| database-connection-exhaustion-connection-storm | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "search"} |
| database-connection-exhaustion-connection-storm | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "search"} |
| database-connection-exhaustion-connection-storm | postgres_connection_count_min | observed | True | {"connection_count": 64.0, "database": "search"} |
| database-connection-exhaustion-connection-storm | - | ok | - |  |
| service-certificate-rotation-readiness-expired | - | started | - |  |
| service-certificate-rotation-readiness-expired | tls_certificate_invalid | observed | True | {"days_remaining": -2, "error": "certificate_expired", "hostname_match": true, "issuer": "CN_sre-agent-test-ca", "not_after_epoch": "1777887431", "raw": "valid=false days_remaining=-2 subject=CN_expired.example.com issuer=CN_sre-agent-te... |
| service-certificate-rotation-readiness-expired | - | ok | - |  |
| database-connection-exhaustion-connection-storm | - | started | - |  |
| database-connection-exhaustion-connection-storm | postgres_connection_count_min | observed | False | {"connection_count": 4.0, "database": "search"} |
| database-connection-exhaustion-connection-storm | postgres_connection_count_min | observed | True | {"connection_count": 64.0, "database": "search"} |
| database-connection-exhaustion-connection-storm | - | ok | - |  |
| service-deployment-rollback-decision-rollback-candidate | - | started | - |  |
| service-deployment-rollback-decision-rollback-candidate | deployment_replicas_ready | observed | True | [1] |
| service-deployment-rollback-decision-rollback-candidate | - | ok | - |  |
| database-connection-exhaustion-pool-exhausted | - | started | - |  |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | True | {"connection_count": 31.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | - | ok | - |  |
| service-latency-spike-downstream-db | - | started | - |  |
| service-latency-spike-downstream-db | pod_condition | observed | True | ["True"] |
| service-latency-spike-downstream-db | http_endpoint_status | observed | True | "200" |
| service-latency-spike-downstream-db | - | ok | - |  |
| kubernetes-crashloopbackoff-config | - | started | - |  |
| kubernetes-crashloopbackoff-config | pod_restart_count_min | observed | True | [2] |
| kubernetes-crashloopbackoff-config | pod_condition | observed | True | ["False"] |
| kubernetes-crashloopbackoff-config | - | ok | - |  |
| service-certificate-rotation-readiness-hostname-mismatch | - | started | - |  |
| service-certificate-rotation-readiness-hostname-mismatch | tls_certificate_invalid | observed | True | {"days_remaining": 44, "error": "hostname_mismatch", "hostname_match": false, "issuer": "CN_sre-agent-test-ca", "not_after_epoch": "1781948712", "raw": "valid=false days_remaining=44 subject=CN_edge-shared.example.net issuer=CN_sre-agent... |
| service-certificate-rotation-readiness-hostname-mismatch | - | ok | - |  |
| kubernetes-crashloopbackoff-config | - | started | - |  |
| kubernetes-crashloopbackoff-config | pod_restart_count_min | observed | False | [1] |
| kubernetes-crashloopbackoff-config | pod_condition | observed | True | ["False"] |
| kubernetes-crashloopbackoff-config | pod_restart_count_min | observed | False | [1] |
| kubernetes-crashloopbackoff-config | pod_condition | observed | True | ["False"] |
| kubernetes-crashloopbackoff-config | pod_restart_count_min | observed | False | [1] |
| kubernetes-crashloopbackoff-config | pod_condition | observed | True | ["False"] |
| kubernetes-crashloopbackoff-config | pod_restart_count_min | observed | True | [2] |
| kubernetes-crashloopbackoff-config | pod_condition | observed | True | ["False"] |
| kubernetes-crashloopbackoff-config | - | ok | - |  |
| service-kafka-rebalance-deploy-induced-rebalance | - | started | - |  |
| service-kafka-rebalance-deploy-induced-rebalance | kafka_partition_rebalance_active | observed | True | {"assignments_revoked": 3, "coordinator": "broker-2", "events": [], "expected_members": 6, "generation": 188, "group": "inventory-indexer", "member_details": [{"assignment": "revoked", "heartbeat_lag_seconds": 42, "member": "inventory-co... |
| service-kafka-rebalance-deploy-induced-rebalance | - | ok | - |  |
| kubernetes-crashloopbackoff-dependency | - | started | - |  |
| kubernetes-crashloopbackoff-dependency | pod_restart_count_min | observed | False | [1] |
| kubernetes-crashloopbackoff-dependency | pod_condition | observed | True | ["False"] |
| kubernetes-crashloopbackoff-dependency | pod_restart_count_min | observed | True | [2] |
| kubernetes-crashloopbackoff-dependency | pod_condition | observed | True | ["False"] |
| kubernetes-crashloopbackoff-dependency | - | ok | - |  |
| kubernetes-node-pressure-disk-pressure | - | started | - |  |
| kubernetes-node-pressure-disk-pressure | node_condition | observed | True | ["True"] |
| kubernetes-node-pressure-disk-pressure | - | ok | - |  |
| kubernetes-crashloopbackoff-dependency | - | started | - |  |
| kubernetes-crashloopbackoff-dependency | pod_restart_count_min | observed | False | [1] |
| kubernetes-crashloopbackoff-dependency | pod_condition | observed | True | ["False"] |
| kubernetes-crashloopbackoff-dependency | pod_restart_count_min | observed | False | [1] |
| kubernetes-crashloopbackoff-dependency | pod_condition | observed | True | ["False"] |
| kubernetes-crashloopbackoff-dependency | pod_restart_count_min | observed | True | [2] |
| kubernetes-crashloopbackoff-dependency | pod_condition | observed | True | ["False"] |
| kubernetes-crashloopbackoff-dependency | - | ok | - |  |
| service-queue-backlog-consumer-lag-dead-letter-backlog | - | started | - |  |
| service-queue-backlog-consumer-lag-dead-letter-backlog | queue_dead_letter_min | observed | True | {"message_count": 420, "oldest_age_seconds": 1800, "queue": "orders.events", "raw": "queue=orders.events message_count=420 oldest_age_seconds=1800\nsample message_id=evt-291 error=deserialization poison payload\nsample message_id=evt-292... |
| service-queue-backlog-consumer-lag-dead-letter-backlog | - | ok | - |  |
| kubernetes-node-pressure-memory-pressure | - | started | - |  |
| kubernetes-node-pressure-memory-pressure | node_condition | observed | True | ["True"] |
| kubernetes-node-pressure-memory-pressure | - | ok | - |  |
| service-latency-spike-downstream-db | - | started | - |  |
| service-latency-spike-downstream-db | pod_condition | observed | True | ["True"] |
| service-latency-spike-downstream-db | http_endpoint_status | observed | True | "200" |
| service-latency-spike-downstream-db | - | ok | - |  |
| kubernetes-pending-pod-pvc-unbound | - | started | - |  |
| kubernetes-pending-pod-pvc-unbound | pvc_phase | observed | True | ["Pending"] |
| kubernetes-pending-pod-pvc-unbound | pod_phase | observed | True | ["Pending"] |
| kubernetes-pending-pod-pvc-unbound | pod_event_reason | observed | True | ["FailedScheduling"] |
| kubernetes-pending-pod-pvc-unbound | - | ok | - |  |
| service-http-5xx-spike-dependency | - | started | - |  |
| service-http-5xx-spike-dependency | pod_condition | observed | True | ["True"] |
| service-http-5xx-spike-dependency | http_endpoint_status | observed | True | "503" |
| service-http-5xx-spike-dependency | - | ok | - |  |
| kubernetes-pending-pod-taint-mismatch | - | started | - |  |
| kubernetes-pending-pod-taint-mismatch | pod_phase | observed | True | ["Pending"] |
| kubernetes-pending-pod-taint-mismatch | pod_event_reason | observed | True | ["FailedScheduling"] |
| kubernetes-pending-pod-taint-mismatch | - | ok | - |  |
| service-deployment-rollback-decision-dependency-no-rollback | - | started | - |  |
| service-deployment-rollback-decision-dependency-no-rollback | deployment_replicas_ready | observed | True | [1] |
| service-deployment-rollback-decision-dependency-no-rollback | - | ok | - |  |
| kubernetes-pending-pod-taint-mismatch | - | started | - |  |
| kubernetes-pending-pod-taint-mismatch | pod_phase | observed | True | ["Pending"] |
| kubernetes-pending-pod-taint-mismatch | pod_event_reason | observed | True | ["FailedScheduling"] |
| kubernetes-pending-pod-taint-mismatch | - | ok | - |  |
| service-dns-tls-failure-nxdomain | - | started | - |  |
| service-dns-tls-failure-nxdomain | dns_resolution_fails | observed | True | {"errors": [";; ->>HEADER<<- opcode: QUERY, status: NXDOMAIN, id: 46709"], "raw": ";; Got answer:\n;; ->>HEADER<<- opcode: QUERY, status: NXDOMAIN, id: 46709\n;; flags: qr aa rd; QUERY: 1, ANSWER: 0, AUTHORITY: 0, ADDITIONAL: 1\n;; WARNI... |
| service-dns-tls-failure-nxdomain | - | ok | - |  |
| kubernetes-pending-pod-taint-mismatch | - | started | - |  |
| kubernetes-pending-pod-taint-mismatch | pod_phase | observed | True | ["Pending"] |
| kubernetes-pending-pod-taint-mismatch | pod_event_reason | observed | True | ["FailedScheduling"] |
| kubernetes-pending-pod-taint-mismatch | - | ok | - |  |
| service-http-5xx-spike-canary-rollout | - | started | - |  |
| service-http-5xx-spike-canary-rollout | pod_condition | observed | True | ["True"] |
| service-http-5xx-spike-canary-rollout | http_endpoint_status | observed | True | "503" |
| service-http-5xx-spike-canary-rollout | - | ok | - |  |
| network-path-degradation-high-latency-hop | - | started | - |  |
| network-path-degradation-high-latency-hop | chaos_mesh_phase | observed | True | "Run" |
| network-path-degradation-high-latency-hop | - | ok | - |  |
| service-deployment-rollback-decision-insufficient-rollback-evidence | - | started | - |  |
| service-deployment-rollback-decision-insufficient-rollback-evidence | deployment_replicas_ready | observed | True | [1] |
| service-deployment-rollback-decision-insufficient-rollback-evidence | - | ok | - |  |
| network-path-degradation-high-latency-hop | - | started | - |  |
| network-path-degradation-high-latency-hop | chaos_mesh_phase | observed | True | "Run" |
| network-path-degradation-high-latency-hop | - | ok | - |  |
| service-kafka-rebalance-partition-skew | - | started | - |  |
| service-kafka-rebalance-partition-skew | kafka_consumer_lag_min | observed | True | {"active_consumers": 6, "consumer_group": "billing-writer", "expected_consumers": 6, "ingress_rate_per_sec": 540.0, "max_partition_lag": 16500, "oldest_message_age_seconds": 520, "partition_lags": [{"lag": 300, "owner": "billing-consumer... |
| service-kafka-rebalance-partition-skew | - | ok | - |  |
| service-certificate-rotation-readiness-expired | - | started | - |  |
| service-certificate-rotation-readiness-expired | tls_certificate_invalid | observed | True | {"days_remaining": -2, "error": "certificate_expired", "hostname_match": true, "issuer": "CN_sre-agent-test-ca", "not_after_epoch": "1777889436", "raw": "valid=false days_remaining=-2 subject=CN_expired.example.com issuer=CN_sre-agent-te... |
| service-certificate-rotation-readiness-expired | - | ok | - |  |
| service-dns-tls-failure-expired | - | started | - |  |
| service-dns-tls-failure-expired | tls_certificate_invalid | observed | True | {"days_remaining": -2, "error": "certificate_expired", "hostname_match": true, "issuer": "CN_sre-agent-test-ca", "not_after_epoch": "1777889457", "raw": "valid=false days_remaining=-2 subject=CN_api.example.com issuer=CN_sre-agent-test-c... |
| service-dns-tls-failure-expired | - | ok | - |  |
| service-kafka-rebalance-rebalance-stall | - | started | - |  |
| service-kafka-rebalance-rebalance-stall | kafka_partition_rebalance_active | observed | True | {"assignments_revoked": 4, "coordinator": "broker-4", "events": [], "expected_members": 6, "generation": 884, "group": "payments-ledger", "member_details": [{"assignment": "revoked", "heartbeat_lag_seconds": 45, "member": "payments-consu... |
| service-kafka-rebalance-rebalance-stall | - | ok | - |  |
| service-queue-backlog-consumer-lag-consumer-lag-backlog | - | started | - |  |
| service-queue-backlog-consumer-lag-consumer-lag-backlog | kafka_consumer_lag_min | observed | True | {"active_consumers": 6, "consumer_group": "fulfillment", "expected_consumers": 6, "ingress_rate_per_sec": 700.0, "max_partition_lag": 9000, "oldest_message_age_seconds": 900, "partition_lags": [{"lag": 9000, "partition": 0}, {"lag": 8000... |
| service-queue-backlog-consumer-lag-consumer-lag-backlog | - | ok | - |  |

## Teardown

| Phase | Step | Scenario | Status | Failures |
| --- | --- | --- | --- | --- |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | service-certificate-rotation-readiness-expired | started |  |
| teardown | seed_teardown | service-certificate-rotation-readiness-expired | ok |  |
| teardown | seed_teardown | database-connection-exhaustion-connection-storm | started |  |
| teardown | seed_teardown | database-connection-exhaustion-connection-storm | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | service-deployment-rollback-decision-rollback-candidate | started |  |
| teardown | seed_teardown | service-deployment-rollback-decision-rollback-candidate | ok |  |
| teardown | seed_teardown | database-connection-exhaustion-connection-storm | started |  |
| teardown | seed_teardown | database-connection-exhaustion-connection-storm | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | service-latency-spike-downstream-db | started |  |
| teardown | seed_teardown | service-latency-spike-downstream-db | ok |  |
| teardown | seed_teardown | database-connection-exhaustion-pool-exhausted | started |  |
| teardown | seed_teardown | database-connection-exhaustion-pool-exhausted | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | service-certificate-rotation-readiness-hostname-mismatch | started |  |
| teardown | seed_teardown | service-certificate-rotation-readiness-hostname-mismatch | ok |  |
| teardown | seed_teardown | kubernetes-crashloopbackoff-config | started |  |
| teardown | seed_teardown | kubernetes-crashloopbackoff-config | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | service-kafka-rebalance-deploy-induced-rebalance | started |  |
| teardown | seed_teardown | service-kafka-rebalance-deploy-induced-rebalance | ok |  |
| teardown | seed_teardown | kubernetes-crashloopbackoff-config | started |  |
| teardown | seed_teardown | kubernetes-crashloopbackoff-config | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | kubernetes-node-pressure-disk-pressure | started |  |
| teardown | seed_teardown | kubernetes-node-pressure-disk-pressure | ok |  |
| teardown | seed_teardown | kubernetes-crashloopbackoff-dependency | started |  |
| teardown | seed_teardown | kubernetes-crashloopbackoff-dependency | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | service-queue-backlog-consumer-lag-dead-letter-backlog | started |  |
| teardown | seed_teardown | service-queue-backlog-consumer-lag-dead-letter-backlog | ok |  |
| teardown | seed_teardown | kubernetes-crashloopbackoff-dependency | started |  |
| teardown | seed_teardown | kubernetes-crashloopbackoff-dependency | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | service-latency-spike-downstream-db | started |  |
| teardown | seed_teardown | service-latency-spike-downstream-db | ok |  |
| teardown | seed_teardown | kubernetes-node-pressure-memory-pressure | started |  |
| teardown | seed_teardown | kubernetes-node-pressure-memory-pressure | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | service-http-5xx-spike-dependency | started |  |
| teardown | seed_teardown | service-http-5xx-spike-dependency | ok |  |
| teardown | seed_teardown | kubernetes-pending-pod-pvc-unbound | started |  |
| teardown | seed_teardown | kubernetes-pending-pod-pvc-unbound | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | service-deployment-rollback-decision-dependency-no-rollback | started |  |
| teardown | seed_teardown | service-deployment-rollback-decision-dependency-no-rollback | ok |  |
| teardown | seed_teardown | kubernetes-pending-pod-taint-mismatch | started |  |
| teardown | seed_teardown | kubernetes-pending-pod-taint-mismatch | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | service-dns-tls-failure-nxdomain | started |  |
| teardown | seed_teardown | service-dns-tls-failure-nxdomain | ok |  |
| teardown | seed_teardown | kubernetes-pending-pod-taint-mismatch | started |  |
| teardown | seed_teardown | kubernetes-pending-pod-taint-mismatch | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | service-http-5xx-spike-canary-rollout | started |  |
| teardown | seed_teardown | service-http-5xx-spike-canary-rollout | ok |  |
| teardown | seed_teardown | kubernetes-pending-pod-taint-mismatch | started |  |
| teardown | seed_teardown | kubernetes-pending-pod-taint-mismatch | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | service-deployment-rollback-decision-insufficient-rollback-evidence | started |  |
| teardown | seed_teardown | service-deployment-rollback-decision-insufficient-rollback-evidence | ok |  |
| teardown | seed_teardown | network-path-degradation-high-latency-hop | started |  |
| teardown | seed_teardown | network-path-degradation-high-latency-hop | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | service-kafka-rebalance-partition-skew | started |  |
| teardown | seed_teardown | service-kafka-rebalance-partition-skew | ok |  |
| teardown | seed_teardown | network-path-degradation-high-latency-hop | started |  |
| teardown | seed_teardown | network-path-degradation-high-latency-hop | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | service-dns-tls-failure-expired | started |  |
| teardown | seed_teardown | service-dns-tls-failure-expired | ok |  |
| teardown | seed_teardown | service-certificate-rotation-readiness-expired | started |  |
| teardown | seed_teardown | service-certificate-rotation-readiness-expired | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | service-queue-backlog-consumer-lag-consumer-lag-backlog | started |  |
| teardown | seed_teardown | service-queue-backlog-consumer-lag-consumer-lag-backlog | ok |  |
| teardown | seed_teardown | service-kafka-rebalance-rebalance-stall | started |  |
| teardown | seed_teardown | service-kafka-rebalance-rebalance-stall | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| warm_kind_cleanup | - | - | started |  |
| warm_kind_cleanup | - | - | ok |  |
