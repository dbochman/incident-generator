# Incident Generator Progress Dashboard

Status: `ok`
Failure class: `none`
Elapsed: `01:33`

## Phase Timing

| Phase | Status | Events | First | Last | Duration | Last message |
| --- | --- | ---: | --- | --- | --- | --- |
| `run` | `ok` | 2 | `00:00` | `01:33` | `01:33` | incident generation complete |
| `validate` | `ok` | 2 | `00:00` | `00:00` | `00:00` | scenario contract is valid |
| `archetype` | `ok` | 2 | `00:00` | `00:54` | `00:53` | kind ready |
| `seed` | `ok` | 2 | `00:54` | `01:12` | `00:18` | scenario seed applied |
| `port_forward` | `ok` | 2 | `01:12` | `01:19` | `00:06` | provider port-forwards ready |
| `providers` | `ok` | 1 | `01:19` | `01:19` | `00:00` | provider endpoints available |
| `wait_for` | `ok` | 3 | `01:19` | `01:19` | `00:00` | all wait predicates matched |
| `selector` | `ok` | 2 | `01:19` | `01:19` | `00:00` | selectors resolved |
| `hold` | `ok` | 2 | `01:19` | `01:24` | `00:05` | hold complete |
| `teardown` | `ok` | 9 | `01:24` | `01:33` | `00:08` | teardown verified |

## Runtime State

- archetype: `kind`
- cluster: `sre-agent-phase-a`
- docker_host: `ssh://JYW4HTC26N`
- kubeconfig_path: `/home/dbochman/repos/sre-incident-agent-skills/.tmp/kubeconfig-kind-e_1tc70t`

### Containers

| Name | Image | Status |
| --- | --- | --- |
| sre-agent-phase-a-control-plane | kindest/node:v1.35.0 | Up 13 minutes |
| sre-agent-phase-a-worker | kindest/node:v1.35.0 | Up 13 minutes |
| sre-agent-phase-a-worker2 | kindest/node:v1.35.0 | Up 13 minutes |

### Images

No entries yet.

## Seed Checkpoints

| Scenario | Status | Applied | Elapsed |
| --- | --- | --- | --- |
| database-connection-exhaustion-pool-exhausted | started | - | 00:54 |
| database-connection-exhaustion-pool-exhausted | ok | True | 01:12 |

## Wait Predicates

| Scenario | Kind | Status | Matched | Observed |
| --- | --- | --- | --- | --- |
| database-connection-exhaustion-pool-exhausted | - | started | - |  |
| database-connection-exhaustion-pool-exhausted | postgres_connection_count_min | observed | True | {"connection_count": 72.0, "database": "checkout"} |
| database-connection-exhaustion-pool-exhausted | - | ok | - |  |

## Teardown

| Phase | Step | Scenario | Status | Failures |
| --- | --- | --- | --- | --- |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | database-connection-exhaustion-pool-exhausted | started |  |
| teardown | seed_teardown | database-connection-exhaustion-pool-exhausted | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | result | database-connection-exhaustion-pool-exhausted | ok |  |
