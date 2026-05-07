# Live Run Reproducibility

This note defines what must remain stable, what may vary, and how to judge timing drift when rerunning live `incident-generator` benchmark aliases.

## Stable Release Boundary

Use `python3 -m incident_generator release-manifest --json` and `python3 -m incident_generator benchmark-sets --json` as the compatibility boundary for a benchmark release.

These values must stay stable for `alpha-2026-05-06` unless a new release alias is published:

- benchmark alias membership, item counts, fixed seeds, host profiles, and source manifests in `benchmark_release.benchmark_set_aliases`;
- scenario tree hashes in `benchmark_release.scenario_hashes`;
- benchmark set source hashes for checked preview plans, retained-summary inputs, judge packs, and selected adapter manifests;
- training seed, curriculum, and skill-drill source hashes when a benchmark release also publishes training material;
- artifact-registry hashes for a specific retained run id.

A new live rerun should not be expected to match old `result.json`, `events.ndjson`, `summary.json`, or dashboard hashes byte-for-byte. Those hashes are immutability checks for one retained run, not cross-run equality checks.

## Expected Variance

Live runs may legitimately change these fields across reruns:

- wall-clock timestamps, `created_at` values, progress event timing, and `duration_ms`;
- incident session ids, absolute artifact paths, temporary kubeconfig paths, process ids, and port-forward details;
- Docker container/image inspection snapshots, pod scheduling order, Kubernetes event ordering, and Prometheus scrape timing;
- observed HTTP latency, packet-loss samples, queue lag samples, database connection counts, and other live measurements that are sampled after seed application;
- live provider latency and judge timing for explicitly operator-run LLM snapshots.

Do not use exact timing equality as a pass condition. Treat timing as an operational signal layered on top of generated counts, failure classes, teardown state, and replay outcomes.

## Timing Drift Policy

The 2026-05-06 Docker-over-SSH `kind/warm-batch` runs provide calibration, not hard assertions:

- curated warm `kind` pairs: `4/4` generated, final elapsed about `1,339,012ms`; first cold `kind ready` checkpoint about `680,143ms`; later warm readiness checkpoints about `30s`;
- random warm `kind` 8 pairs: `8/8` generated, final elapsed about `1,589,894ms`; first cold readiness about `652,865ms`; later warm readiness checkpoints about `57s`;
- random warm `kind` 16 pairs: `16/16` generated, final elapsed about `2,883,025ms`; first cold readiness about `649,679ms`;
- compatible `linux-vm` pair sweep: `23/23` generated, final elapsed about `4,892,644ms`.

A rerun is reproducible when:

- the selected benchmark set id, alias, fixed seed, and generated item count match the release manifest;
- `blocked`, failed, and error counts stay at zero for the previously green live set;
- `failure_class` remains `none` for generated cases;
- teardown verification passes after every case and final retained-cluster cleanup passes for warm `kind` batches;
- deterministic replay or result comparison preserves expected hypotheses and expected abstention or uncertainty behavior.

Investigate a rerun when:

- cold startup exceeds configured timeouts or warm checkpoints return to cold-start scale after the first case;
- generated counts, selected scenario ids, or compatibility decisions change under the same alias and seed;
- selector, wait predicate, provider, teardown, or cleanup failures appear;
- deterministic replay misses an expected hypothesis or introduces a forbidden one;
- artifact-registry hashes drift for an existing retained run id.

## Compare Procedure

For fixture-safe release checks:

```sh
python3 -m incident_generator validate --json
python3 -m incident_generator catalog --json
python3 -m incident_generator benchmark-sets --json
```

For a live rerun, retain fresh artifacts under a new run id:

```sh
mkdir -p benchmark-artifacts/kind-random8-rerun
DOCKER_HOST=ssh://<ssh-host> \
SRE_AGENT_KIND_CREATE_TIMEOUT_SECONDS=600 \
SRE_AGENT_REMOTE_DOCKER_TIMEOUT_SECONDS=90 \
SRE_AGENT_KIND_WAIT=240s \
SRE_AGENT_KIND_API_WAIT_SECONDS=240 \
python3 -m incident_generator run \
  --random-compatible-combinations 8 \
  --random-combination-size 2 \
  --random-archetype kind \
  --random-seed 20260506 \
  --collection-mode real \
  --require-tools \
  --warm-kind \
  --progress-json \
  --progress-artifact-dir benchmark-artifacts/kind-random8-rerun \
  --incident-session-id kind-random8-rerun \
  --json > benchmark-artifacts/kind-random8-rerun/result.json
```

Then record and check the retained run:

```sh
python3 -m incident_generator artifact-registry add \
  --registry benchmark-artifacts/registry.json \
  --artifact-dir benchmark-artifacts/kind-random8-rerun \
  --benchmark-set-id kind-random8-warm-20260506 \
  --run-id kind-random8-rerun \
  --seed 20260506 \
  --host-profile kind/warm-batch \
  --docker-host-kind ssh \
  --docker-host ssh://<ssh-host> \
  --command "python3 -m incident_generator run --random-compatible-combinations 8 --random-archetype kind --random-seed 20260506 --warm-kind --json" \
  --json

python3 -m incident_generator artifact-registry check \
  --registry benchmark-artifacts/registry.json \
  --json
```

Use [benchmark-release-manifest.md](benchmark-release-manifest.md) for release hash boundaries and [alpha-benchmark-sets.md](alpha-benchmark-sets.md) for alias compatibility promises.
