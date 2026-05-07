# Standalone Examples

These examples assume you are in the root of the exported `incident-generator` package. Keep generated files under `benchmark-artifacts/` so they are easy to retain, compare, or register.

## Fixture Preview

This path does not require Docker, kind, provider credentials, or live infrastructure.

```sh
mkdir -p benchmark-artifacts/fixture-preview

python3 -m incident_generator validate --json \
  > benchmark-artifacts/fixture-preview/validate.json

python3 -m incident_generator catalog --json \
  > benchmark-artifacts/fixture-preview/catalog.json

python3 -m incident_generator benchmark-sets --json \
  > benchmark-artifacts/fixture-preview/benchmark-sets.json

python3 -m incident_generator pair-preview --json \
  > benchmark-artifacts/fixture-preview/pair-preview.json

python3 -m incident_generator triple-preview --json \
  > benchmark-artifacts/fixture-preview/triple-preview.json

python3 -m incident_generator noisy-smoke \
  --smoke harness/noisy-database-live-smoke.yaml \
  --json > benchmark-artifacts/fixture-preview/noisy-database-smoke.json

python3 -m incident_generator plan \
  --random-compatible-combinations 8 \
  --random-combination-size 2 \
  --random-archetype kind \
  --random-seed 20260506 \
  --collection-mode fixture \
  --json > benchmark-artifacts/fixture-preview/kind-random8-plan.json
```

## Live Warm-Kind Run

Use this for a controlled `kind/warm-batch` rerun. Replace `<ssh-host>` with the Docker host used by your runner, or set `DOCKER_HOST` to a local Docker daemon if that is the intended host profile.

```sh
export DOCKER_HOST="ssh://<ssh-host>"
export SRE_AGENT_KIND_CREATE_TIMEOUT_SECONDS=600
export SRE_AGENT_REMOTE_DOCKER_TIMEOUT_SECONDS=90
export SRE_AGENT_KIND_WAIT=240s
export SRE_AGENT_KIND_API_WAIT_SECONDS=240

RUN_ID=kind-random8-warm-$(date -u +%Y%m%dT%H%M%SZ)
ARTIFACT_DIR=benchmark-artifacts/$RUN_ID
mkdir -p "$ARTIFACT_DIR"

python3 -m incident_generator run \
  --random-compatible-combinations 8 \
  --random-combination-size 2 \
  --random-archetype kind \
  --random-seed 20260506 \
  --collection-mode real \
  --require-tools \
  --warm-kind \
  --progress-json \
  --progress-artifact-dir "$ARTIFACT_DIR" \
  --incident-session-id "$RUN_ID" \
  --json > "$ARTIFACT_DIR/result.json"
```

The progress artifact directory updates `dashboard.json` and `dashboard.md` as the run proceeds. The Markdown dashboard includes a `Live Look` section with recent phase events, runtime/container state when available, wait-predicate observations, seed checkpoints, and teardown status.

Register the retained run after verifying the result:

```sh
python3 -m incident_generator artifact-registry add \
  --registry benchmark-artifacts/registry.json \
  --artifact-dir "$ARTIFACT_DIR" \
  --benchmark-set-id kind-random8-warm-20260506 \
  --run-id "$RUN_ID" \
  --seed 20260506 \
  --host-profile kind/warm-batch \
  --docker-host-kind ssh \
  --docker-host "$DOCKER_HOST" \
  --env "DOCKER_HOST=$DOCKER_HOST" \
  --env "SRE_AGENT_KIND_CREATE_TIMEOUT_SECONDS=$SRE_AGENT_KIND_CREATE_TIMEOUT_SECONDS" \
  --env "SRE_AGENT_REMOTE_DOCKER_TIMEOUT_SECONDS=$SRE_AGENT_REMOTE_DOCKER_TIMEOUT_SECONDS" \
  --env "SRE_AGENT_KIND_WAIT=$SRE_AGENT_KIND_WAIT" \
  --env "SRE_AGENT_KIND_API_WAIT_SECONDS=$SRE_AGENT_KIND_API_WAIT_SECONDS" \
  --command "python3 -m incident_generator run --random-compatible-combinations 8 --random-combination-size 2 --random-archetype kind --random-seed 20260506 --collection-mode real --require-tools --warm-kind --progress-json --json" \
  --json

python3 -m incident_generator artifact-registry check \
  --registry benchmark-artifacts/registry.json \
  --json
```

## Deterministic Replay Result

The standalone package converts a checked deterministic replay summary into a benchmark-result payload. To create a new replay summary for a fresh live result, run the canonical repo's validated-combo agent tool first, then pass that `summary.json` with `--summary`.

```sh
mkdir -p benchmark-artifacts/deterministic-replay

python3 -m incident_generator deterministic-replay-result \
  --summary harness/deterministic-replay-summary-example.json \
  --benchmark-set-id kind-curated-pairs-warm-20260506 \
  --created-at 2026-05-06T00:00:00Z \
  --output benchmark-artifacts/deterministic-replay/result.json
```

## Result Comparison

Render the checked default comparison:

```sh
mkdir -p benchmark-artifacts/comparison

python3 -m incident_generator result-comparison \
  --created-at 2026-05-06T00:00:00Z \
  --output benchmark-artifacts/comparison/result-comparison.md
```

Or compare explicit result payloads:

```sh
python3 -m incident_generator deterministic-replay-result \
  --summary harness/deterministic-replay-summary-example.json \
  --benchmark-set-id kind-curated-pairs-warm-20260506 \
  --created-at 2026-05-06T00:00:00Z \
  --output benchmark-artifacts/comparison/deterministic-replay-result.json

python3 -m incident_generator llm-smoke-result \
  --include both \
  --created-at 2026-05-06T00:00:00Z \
  --output benchmark-artifacts/comparison/llm-smoke-result.json

python3 -m incident_generator noisy-live-result \
  --run-id 20260506-noisy-live-checkout-canary-5xx \
  --created-at 2026-05-06T00:00:00Z \
  --output benchmark-artifacts/comparison/noisy-live-result.json

python3 -m incident_generator benchmark-runner \
  --benchmark-set harness/agent-adapter-benchmark-set.yaml \
  --judge-pack deterministic-local \
  --artifact-dir benchmark-artifacts/external-agent-adapter-smoke \
  --output benchmark-artifacts/comparison/external-agent-result.json

# Prompt/response trace: benchmark-artifacts/external-agent-adapter-smoke/trace.md
# Per-case transcript: benchmark-artifacts/external-agent-adapter-smoke/cases/<case-id>/transcript.md

python3 -m incident_generator result-comparison \
  --result benchmark-artifacts/comparison/deterministic-replay-result.json \
  --result benchmark-artifacts/comparison/llm-smoke-result.json \
  --result benchmark-artifacts/comparison/noisy-live-result.json \
  --result benchmark-artifacts/comparison/external-agent-result.json \
  --output benchmark-artifacts/comparison/explicit-result-comparison.md
```

Use [live-run-reproducibility.md](live-run-reproducibility.md) to decide whether a live rerun is comparable to a retained alpha run.
