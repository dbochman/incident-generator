# Incident Generator Progress Dashboard

Status: `ok`
Failure class: `none`
Elapsed: `26:29`

## Phase Timing

| Phase | Status | Events | First | Last | Duration | Last message |
| --- | --- | ---: | --- | --- | --- | --- |
| `run` | `ok` | 16 | `00:00` | `26:10` | `26:10` | incident generation complete |
| `validate` | `ok` | 16 | `00:00` | `24:52` | `24:52` | combinatorial scenario contract is valid |
| `archetype` | `ok` | 16 | `00:00` | `25:49` | `25:49` | kind ready |
| `seed` | `ok` | 32 | `10:52` | `25:54` | `15:01` | scenario seed applied: service-queue-backlog-consumer-lag-consumer-lag-backlog |
| `port_forward` | `ok` | 16 | `11:44` | `26:00` | `14:15` | provider port-forwards ready |
| `providers` | `ok` | 8 | `11:50` | `26:00` | `14:09` | provider endpoints available |
| `wait_for` | `ok` | 72 | `11:50` | `26:01` | `14:11` | all wait predicates matched |
| `selector` | `ok` | 32 | `12:31` | `26:01` | `13:30` | selectors resolved: service-queue-backlog-consumer-lag-consumer-lag-backlog |
| `teardown` | `ok` | 88 | `12:31` | `26:10` | `13:38` | teardown verified |
| `warm_kind_cleanup` | `ok` | 2 | `26:10` | `26:29` | `00:19` | retained kind cluster deleted |
| `batch` | `ok` | 1 | `26:29` | `26:29` | `00:00` | combinatorial batch complete |

## Runtime State

- archetype: `kind`
- cluster: `sre-agent-phase-a`
- docker_host: `ssh://JYW4HTC26N`
- kubeconfig_path: `/home/dbochman/repos/sre-incident-agent-skills/.tmp/kubeconfig-kind-qm_fqn_j`

### Containers

| Name | Image | Status |
| --- | --- | --- |
| sre-agent-phase-a-worker2 | kindest/node:v1.35.0 | Up 24 minutes |
| sre-agent-phase-a-worker | kindest/node:v1.35.0 | Up 24 minutes |
| sre-agent-phase-a-control-plane | kindest/node:v1.35.0 | Up 24 minutes |

### Images

No entries yet.

## Seed Checkpoints

| Scenario | Status | Applied | Elapsed |
| --- | --- | --- | --- |
| database-connection-exhaustion-connection-storm | started | - | 10:52 |
| database-connection-exhaustion-connection-storm | ok | True | 11:14 |
| service-certificate-rotation-readiness-expired | started | - | 11:14 |
| service-certificate-rotation-readiness-expired | ok | True | 11:44 |
| kubernetes-crashloopbackoff-config | started | - | 14:24 |
| kubernetes-crashloopbackoff-config | ok | True | 14:26 |
| service-kafka-rebalance-deploy-induced-rebalance | started | - | 14:26 |
| service-kafka-rebalance-deploy-induced-rebalance | ok | True | 14:28 |
| kubernetes-crashloopbackoff-dependency | started | - | 15:55 |
| kubernetes-crashloopbackoff-dependency | ok | True | 15:57 |
| service-queue-backlog-consumer-lag-dead-letter-backlog | started | - | 15:57 |
| service-queue-backlog-consumer-lag-dead-letter-backlog | ok | True | 15:59 |
| kubernetes-pending-pod-taint-mismatch | started | - | 17:26 |
| kubernetes-pending-pod-taint-mismatch | ok | True | 17:28 |
| service-deployment-rollback-decision-dependency-no-rollback | started | - | 17:28 |
| service-deployment-rollback-decision-dependency-no-rollback | ok | True | 17:30 |
| kubernetes-pending-pod-taint-mismatch | started | - | 18:47 |
| kubernetes-pending-pod-taint-mismatch | ok | True | 18:49 |
| service-http-5xx-spike-canary-rollout | started | - | 18:49 |
| service-http-5xx-spike-canary-rollout | ok | True | 19:23 |
| network-path-degradation-high-latency-hop | started | - | 20:45 |
| network-path-degradation-high-latency-hop | ok | True | 22:22 |
| service-deployment-rollback-decision-insufficient-rollback-evidence | started | - | 22:22 |
| service-deployment-rollback-decision-insufficient-rollback-evidence | ok | True | 22:24 |
| network-path-degradation-high-latency-hop | started | - | 23:40 |
| network-path-degradation-high-latency-hop | ok | True | 24:30 |
| service-kafka-rebalance-partition-skew | started | - | 24:30 |
| service-kafka-rebalance-partition-skew | ok | True | 24:33 |
| service-kafka-rebalance-rebalance-stall | started | - | 25:49 |
| service-kafka-rebalance-rebalance-stall | ok | True | 25:52 |
| service-queue-backlog-consumer-lag-consumer-lag-backlog | started | - | 25:52 |
| service-queue-backlog-consumer-lag-consumer-lag-backlog | ok | True | 25:54 |

## Wait Predicates

| Scenario | Kind | Status | Matched | Observed |
| --- | --- | --- | --- | --- |
| database-connection-exhaustion-connection-storm | - | started | - |  |
| database-connection-exhaustion-connection-storm | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "search"} |
| database-connection-exhaustion-connection-storm | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "search"} |
| database-connection-exhaustion-connection-storm | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "search"} |
| database-connection-exhaustion-connection-storm | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "search"} |
| database-connection-exhaustion-connection-storm | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "search"} |
| database-connection-exhaustion-connection-storm | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "search"} |
| database-connection-exhaustion-connection-storm | postgres_connection_count_min | observed | False | {"connection_count": 0.0, "database": "search"} |
| database-connection-exhaustion-connection-storm | postgres_connection_count_min | observed | True | {"connection_count": 64.0, "database": "search"} |
| database-connection-exhaustion-connection-storm | - | ok | - |  |
| service-certificate-rotation-readiness-expired | - | started | - |  |
| service-certificate-rotation-readiness-expired | tls_certificate_invalid | observed | True | {"days_remaining": -2, "error": "certificate_expired", "hostname_match": true, "issuer": "CN_sre-agent-test-ca", "not_after_epoch": "1777885043", "raw": "valid=false days_remaining=-2 subject=CN_expired.example.com issuer=CN_sre-agent-te... |
| service-certificate-rotation-readiness-expired | - | ok | - |  |
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
