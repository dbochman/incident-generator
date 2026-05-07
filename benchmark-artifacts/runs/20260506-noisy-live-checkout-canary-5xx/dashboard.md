# Incident Generator Progress Dashboard

Status: `ok`
Failure class: `none`
Elapsed: `01:39`

## Phase Timing

| Phase | Status | Events | First | Last | Duration | Last message |
| --- | --- | ---: | --- | --- | --- | --- |
| `run` | `ok` | 2 | `00:00` | `01:39` | `01:39` | incident generation complete |
| `validate` | `ok` | 2 | `00:00` | `00:00` | `00:00` | scenario contract is valid |
| `archetype` | `ok` | 2 | `00:00` | `00:51` | `00:51` | kind ready |
| `seed` | `ok` | 2 | `00:51` | `01:18` | `00:27` | scenario seed applied |
| `port_forward` | `ok` | 2 | `01:18` | `01:24` | `00:05` | provider port-forwards ready |
| `providers` | `ok` | 1 | `01:24` | `01:24` | `00:00` | provider endpoints available |
| `wait_for` | `ok` | 4 | `01:24` | `01:25` | `00:00` | all wait predicates matched |
| `selector` | `ok` | 2 | `01:25` | `01:25` | `00:00` | selectors resolved |
| `hold` | `ok` | 2 | `01:25` | `01:30` | `00:05` | hold complete |
| `teardown` | `ok` | 9 | `01:30` | `01:39` | `00:08` | teardown verified |

## Runtime State

- archetype: `kind`
- cluster: `sre-agent-phase-a`
- docker_host: `ssh://JYW4HTC26N`
- kubeconfig_path: `/home/dbochman/repos/sre-incident-agent-skills/.tmp/kubeconfig-kind-3lo22zyh`

### Containers

| Name | Image | Status |
| --- | --- | --- |
| sre-agent-phase-a-control-plane | kindest/node:v1.35.0 | Up 15 minutes |
| sre-agent-phase-a-worker2 | kindest/node:v1.35.0 | Up 15 minutes |
| sre-agent-phase-a-worker | kindest/node:v1.35.0 | Up 15 minutes |

### Images

No entries yet.

## Seed Checkpoints

| Scenario | Status | Applied | Elapsed |
| --- | --- | --- | --- |
| service-http-5xx-spike-canary-rollout | started | - | 00:51 |
| service-http-5xx-spike-canary-rollout | ok | True | 01:18 |

## Wait Predicates

| Scenario | Kind | Status | Matched | Observed |
| --- | --- | --- | --- | --- |
| service-http-5xx-spike-canary-rollout | - | started | - |  |
| service-http-5xx-spike-canary-rollout | pod_condition | observed | True | ["True"] |
| service-http-5xx-spike-canary-rollout | http_endpoint_status | observed | True | "503" |
| service-http-5xx-spike-canary-rollout | - | ok | - |  |

## Teardown

| Phase | Step | Scenario | Status | Failures |
| --- | --- | --- | --- | --- |
| teardown | - | - | started |  |
| teardown | port_forward_stop | - | started |  |
| teardown | port_forward_stop | - | ok |  |
| teardown | seed_teardown | service-http-5xx-spike-canary-rollout | started |  |
| teardown | seed_teardown | service-http-5xx-spike-canary-rollout | ok |  |
| teardown | archetype_teardown | - | started |  |
| teardown | archetype_teardown | - | ok |  |
| teardown | teardown_verifier | - | started |  |
| teardown | teardown_verifier | - | ok |  |
| teardown | result | service-http-5xx-spike-canary-rollout | ok |  |
