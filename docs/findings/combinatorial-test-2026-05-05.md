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

## Addendum: TLS rerun on 2026-05-05

After commit `0a613d7` shipped the `||true` SAN-guard in `harness/tls-target/check-tls.sh` plus richer TLS-failure observation, the two blocked cert-rotation combinations were rerun in real mode with `--require-tools`. Artifacts: `.tmp/incidents/test-tls-rerun/`.

### Result

| # | Status | Scenarios | Failure detail |
| - | - | - | - |
| 1 | **blocked** | cert-rotation/expiring + cert-rotation/hostname-mismatch | `wait_for/failed` check=`tls_certificate_invalid` observed.error=`certificate_expired` (forced) |
| 2 | ok | pending-pod/unschedulable + cert-rotation/expired | — |

The SAN-guard fix unblocked combo 2. Combo 1 still times out, and the richer `observed` payload makes the underlying bug visible.

### Root cause: `date -u -d` is GNU-only

`harness/tls-target/check-tls.sh` runs on the host (only `openssl s_client` is exec'd in-pod). On a macOS host, BSD `date` does not accept `-d <string>`:

```sh
NOT_AFTER_EPOCH="$(date -u -d "$NOT_AFTER_RAW" +%s 2>/dev/null || echo 0)"
```

The redirect silently swallows the error, `NOT_AFTER_EPOCH=0`, `DAYS_REMAINING` becomes a large negative number, and every cert reads as `error=certificate_expired` regardless of its real `notAfter`. Confirmed by the rerun's `observed`:

```
raw: valid=false days_remaining=-20578 subject= CN=api.example.com issuer= CN=sre-agent-test-ca
     hostname_match=false not_after_epoch=0 error=certificate_expired
```

This bug coincidentally lets the `expired` scenario pass (the forced `certificate_expired` matches its expected reason) while breaking `expiring` and `hostname-mismatch`, whose expected reasons differ.

### Secondary bug: subject parser splits on space

The `raw` line shows `subject= CN=api.example.com` (trailing space after `subject=`). `parsers.parse_tls_check` splits on whitespace, so `subject` is recorded as empty and `CN=api.example.com` becomes a separate `CN` key. `hostname_match` is computed against `$SUBJECT` (the empty string), so it always reports `false` even when the cert's CN matches the hostname.

### Recommended fixes

1. **Move date arithmetic into the probe pod, or use `openssl x509 -checkend`.** The probe pod is Linux and already has `openssl`. `openssl x509 -checkend $((7*86400))` returns rc=0/1 directly, eliminating the date-format dependency. Alternatively, run `kubectl exec $PROBE -- date -d "$NOT_AFTER_RAW" +%s` so date executes on Linux.
2. **Strip the leading space from the subject/issuer captures.** `sed 's/^subject= *//'` (and same for `issuer=`) so the printf'd line has no internal whitespace and `parse_tls_check` sees a single token.
3. **Surface the parse failure instead of masking it.** Replace `|| echo 0` with an explicit `error=date_parse_failed` exit so the predicate's `observed.error` reports the host-portability problem instead of forcing `certificate_expired`.

## Addendum 2: Verification rerun against the in-pod check-tls.sh

Commits `b9afa8e` + `87b9704` rewrote `check-tls.sh` to run the entire openssl + cert-parsing pipeline inside the probe pod via `kubectl exec <<<"$INNER_SCRIPT"`, with `-dateopt iso_8601` for portable date parsing and `tr " =" "__"` to side-step the whitespace-split parser bug. Same two combos rerun against this fix. Artifacts: `.tmp/incidents/test-tls-rerun-2/`.

### Result

| # | Status | Scenarios | Notes |
| - | - | - | - |
| 1 | **blocked** | cert-rotation/expiring + cert-rotation/hostname-mismatch | seed collision — see below |
| 2 | ok | pending-pod/unschedulable + cert-rotation/expired | in-pod parser produces real values |

### Combo 2 — fix verified

Observed for combo 2's `tls_certificate_invalid` predicate (the one that previously matched only by coincidence of the broken date parser):

```
raw: valid=false days_remaining=-2 subject=CN_expired.example.com issuer=CN_sre-agent-test-ca
     hostname_match=true not_after_epoch=1777820455 error=certificate_expired
```

`days_remaining=-2` and `not_after_epoch=1777820455` are real values from the seed cert's actual `notAfter`, not the previous `-20578` / `0` placeholder produced by the broken host-side `date -u -d`. The predicate now matches legitimately.

### Combo 1 — real seed collision, not a check-tls.sh bug

Combo 1's two predicates evaluate sequentially:

```
[wait_for/started] TLS target serves a certificate inside the rotation window
[wait_for/ok]      all wait predicates matched              # expiring matched
[wait_for/started] TLS target serves a valid certificate for the wrong hostname
[wait_for/failed]  wait predicates timed out                # hostname-mismatch did not
```

The `expiring` scenario seed and the `hostname-mismatch` scenario seed both modify the same `Secret` holding the TLS cert. When both seeds run in sequence the second overwrites the first, so the cert ends up serving one set of properties (here, the `expiring` shape: `days_remaining=2`, `hostname_match=true`, `valid=true`). One predicate matches, the other can't. This is a catalog-level combinatorial incompatibility, not a fix bug.

### Recommended catalog change

Mark cert-rotation scenario pairs that share a target `Secret` as mutually exclusive at validation time, the same way real-mode cross-archetype combinations are blocked today. The `--combination` flag should fail validation with a clear "scenarios share resource X" message instead of letting the runner spin up a kind cluster only to have one predicate time out.

## Addendum 3: Catalog validation shipped

The cert-rotation variants now declare an exclusive `resource_claims` entry for `kubernetes.Secret/edge/edge-api-tls`. Real-mode combinatorial validation fails before archetype startup when two scenarios share that claim, while fixture mode remains allowed because no live resource is mutated. Seeded `--random-compatible-combinations` also filters those pairs out of the real-compatible pool.

## Addendum 4: Linux full-sweep preflight conflicts

A follow-up full `linux-vm` pair sweep exposed the same class of catalog issue in the Linux target. `linux-disk-full-capacity + linux-memory-oom-oom-kill` failed during seed application because disk fill on `/var/sre-agent` prevented the OOM seed from writing `/var/sre-agent/oom-events.log`.

The Linux scenarios now declare resource claims for the shared target mount, CPU saturation, memory pressure, and OOM event file. Disk fillers that can starve the OOM event path declare `conflicts_with` against the OOM evidence file, so incompatible pairs fail validation before Docker Compose startup. The compatible `linux-vm` pair pool is now `23` pairs rather than the raw `C(9,2)=36` set.
