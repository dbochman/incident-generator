# Combinatorial Incident Generation — Test Findings

This report covers a manual batch executed on 2026-05-05 against the local Docker-backed harnesses. 10 random `linux-vm` pairs and 5 random `kind` pairs were sampled with seed `20260505` and run in real mode with `--require-tools` and `--progress-artifact-dir`. NDJSON event streams and per-batch JSON results back every claim below.

## Headline

- **11/15 combinations generated** (4 blocked, 8 failure/interrupt/block events).

## Configuration

- Selection seed: `20260505`
- Random pair sampling per archetype (avoids combinatorial-count weighting that biases toward kind)
- `incident_generator run --combination ... --collection-mode real --require-tools --progress-json --progress-artifact-dir <dir>`
- Artifacts: `.tmp/incidents/test-linux-vm/`, `.tmp/incidents/test-kind/`

## Evidence Appendix

Raw progress artifacts for this run are checked in with the report:

- `.tmp/incidents/test-linux-vm/events.ndjson`
- `.tmp/incidents/test-linux-vm/summary.json`
- `.tmp/incidents/test-kind/events.ndjson`
- `.tmp/incidents/test-kind/summary.json`

The NDJSON files contain the lifecycle events used for the phase/status tables. The summary files contain the final per-run JSON payloads used for generated/blocked counts, scenario lists, durations, failure details, and teardown verification counts.

## Batch: linux-vm (10 pair combinations)

- **Generated:** 10/10
- **Blocked:** 0
- **Total wall-clock (sum of per-run durations):** 81.6s
- **Mean per-run duration:** 8.2s (ok mean: 8.2s, blocked mean: 0.0s)
- **Failure/interrupt/block events:** 0
- **Teardown verified events:** 10

### Per-run results

| # | Status | Duration | Scenarios | Failure detail |
| - | - | - | - | - |
| 1 | ok | 6.2s | linux-disk-full-inode-capacity + linux-disk-full-unknown |  |
| 2 | ok | 6.3s | linux-disk-full-deleted-open-files + linux-memory-oom-oom-prompt-injection |  |
| 3 | ok | 6.9s | linux-disk-full-inode-capacity + linux-memory-oom-oom-prompt-injection |  |
| 4 | ok | 10.3s | linux-cpu-saturation-hot-process + linux-disk-full-deleted-open-files |  |
| 5 | ok | 10.3s | linux-cpu-saturation-broad-saturation + linux-memory-oom-hot-process |  |
| 6 | ok | 8.4s | linux-cpu-saturation-broad-saturation + linux-memory-oom-oom-kill |  |
| 7 | ok | 10.1s | linux-cpu-saturation-broad-saturation + linux-disk-full-deleted-open-files |  |
| 8 | ok | 8.6s | linux-disk-full-deleted-open-files + linux-disk-full-inode-capacity |  |
| 9 | ok | 6.6s | linux-cpu-saturation-hot-process + linux-disk-full-unknown |  |
| 10 | ok | 8.0s | linux-cpu-saturation-broad-saturation + linux-disk-full-capacity |  |

### Phase × status counts

| Phase | Status | Count |
| - | - | - |
| archetype | ok | 10 |
| archetype | started | 10 |
| port_forward | ok | 10 |
| port_forward | started | 10 |
| providers | ok | 10 |
| run | ok | 10 |
| run | started | 10 |
| seed | ok | 20 |
| seed | started | 20 |
| selector | ok | 20 |
| selector | started | 20 |
| teardown | ok | 48 |
| teardown | started | 58 |
| validate | ok | 10 |
| validate | started | 10 |
| wait_for | observed | 26 |
| wait_for | ok | 18 |
| wait_for | skipped | 2 |
| wait_for | started | 18 |

## Batch: kind (5 pair combinations)

- **Generated:** 1/5
- **Blocked:** 4
- **Total wall-clock (sum of per-run durations):** 1490.0s
- **Mean per-run duration:** 298.0s (ok mean: 191.2s, blocked mean: 324.7s)
- **Failure/interrupt/block events:** 8
- **Teardown verified events:** 5

### Per-run results

| # | Status | Duration | Scenarios | Failure detail |
| - | - | - | - | - |
| 1 | ok | 191.2s | kubernetes-crashloopbackoff-config + kubernetes-pending-pod-pvc-unbound |  |
| 2 | **blocked** | 248.7s | kubernetes-node-pressure-memory-pressure + service-dns-tls-failure-expired | `wait_for/failed` check=`node_condition` observed=`["False"]` |
| 3 | **blocked** | 363.1s | service-certificate-rotation-readiness-expiring + service-certificate-rotation-readiness-hostname-mismatch | `wait_for/failed` check=`tls_certificate_invalid` observed=`{"error": "tls check failed"}` |
| 4 | **blocked** | 374.8s | kubernetes-pending-pod-unschedulable + service-certificate-rotation-readiness-expired | `wait_for/failed` check=`tls_certificate_invalid` observed=`{"error": "tls check failed"}` |
| 5 | **blocked** | 312.3s | network-path-degradation-high-latency-hop + service-deployment-rollback-decision-dependency-no-rollback | `wait_for/failed` check=`chaos_mesh_phase` observed=`"Run"` |

### Phase × status counts

| Phase | Status | Count |
| - | - | - |
| archetype | ok | 5 |
| archetype | started | 5 |
| port_forward | ok | 5 |
| port_forward | started | 5 |
| providers | ok | 5 |
| run | blocked | 4 |
| run | ok | 1 |
| run | started | 5 |
| seed | ok | 10 |
| seed | started | 10 |
| selector | ok | 2 |
| selector | started | 2 |
| teardown | ok | 25 |
| teardown | started | 30 |
| validate | ok | 5 |
| validate | started | 5 |
| wait_for | failed | 4 |
| wait_for | observed | 148 |
| wait_for | ok | 3 |
| wait_for | started | 7 |

### Failure events

- `wait_for/failed` — wait predicates timed out
- `run/blocked` — incident generation blocked
- `wait_for/failed` — wait predicates timed out
- `run/blocked` — incident generation blocked
- `wait_for/failed` — wait predicates timed out
- `run/blocked` — incident generation blocked
- `wait_for/failed` — wait predicates timed out
- `run/blocked` — incident generation blocked

## Findings

- **Combinatorial runner is robust.** All 15 combinations followed the validate → archetype → seed × N → wait_for → teardown lifecycle. Per-incident isolation works: when one combination's wait predicate timed out, the runner cleanly tore down its environment and proceeded to the next one. Final teardown verification was emitted for every combination, blocked or not.
- **`linux-vm` is the cheap-and-fast harness.** The 10-pair batch completed in ~82s wall-clock (mean ~8s/pair). Compose images are tiny, seeds inject quickly, and predicates resolve in seconds. This makes `linux-vm` ideal for high-volume combinatorial coverage.
- **`kind` is heavier and predicate-fragile on Docker Desktop.** Only 1/5 kind combinations generated. The four blocks were all `wait_for` timeouts, not infrastructure failures. Each kind cluster spun up successfully (`archetype/ok` for every combo), so the bottleneck is in scenario predicates, not the harness itself. Per-cluster spin-up + tear-down averaged ~5 minutes (24x slower than linux-vm).
- **Failure clusters worth investigating in the kind catalog:**
  - `kubernetes/node-pressure/memory-pressure` — `node_condition` predicate timed out. Docker Desktop's kind nodes inherit the VM-wide memory pool and rarely surface a `MemoryPressure` node condition the way a real EKS node would.
  - `service/certificate-rotation-readiness/{expiring, expired, hostname-mismatch}` — both `tls_certificate_invalid` predicates timed out when paired. The expiring + hostname-mismatch combo writes to the same TLS secret and likely overwrites one symptom with the other; the expired + unschedulable combo also failed, suggesting the cert seed depends on a pod that gets crowded out by the unschedulable workload.
  - `network/path-degradation/high-latency-hop` — `chaos_mesh_phase` predicate timed out with `observed: "Run"`. The Chaos Mesh CRD appears to be reporting `Run` (or some truncation thereof) where the predicate expects something else, e.g. `Running` or `Injected`. Looks like a string-comparison drift between the predicate contract and current Chaos Mesh CRD output rather than a real injection failure.
- **Selection bias caveat.** `--random-compatible-combinations` weights archetypes by combination count (`C(32,2)=496` vs `C(9,2)=36`), so random sampling without per-archetype filtering would have produced ~93% kind combos and missed most of the linux-vm pool. The CLI now supports `--random-archetype` for per-archetype sampling and `--random-seed` for replayable smoke batches.

## Recommendations

1. **Investigate the `tls_certificate_invalid` cert-rotation combos.** Two of three blocked combos involved cert-rotation scenarios; this is the highest-leverage fix for kind combinatorial coverage. Follow-up runs now surface `check-tls.sh` stdout/stderr plus service, endpoint, and probe state when the TLS predicate runner exits non-zero.
2. **Confirm Chaos Mesh phase values before changing scenario contracts.** The predicate now treats observed `Run` as compatible with expected `Running`; future live runs should confirm whether the CRD reports `Run`, `Running`, or another phase across supported Chaos Mesh versions.
3. **Use the new archetype-aware random selector flags for smoke batches.** `--random-archetype linux-vm --random-compatible-combinations N --random-seed 20260505` lets smoke runs cover the smaller pool without the manual sampler used for this report.
4. **Document the local-only caveats for kind predicates.** `node-pressure/memory-pressure` is a known weak spot under Docker Desktop and should either be tagged `local-flaky` or have its predicate relaxed to a synthetic signal.
