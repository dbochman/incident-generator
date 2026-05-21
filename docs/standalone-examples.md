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

## CrisisMode Compatibility Workflow

This path validates the incident-generator side of CrisisMode compatibility without live infrastructure. The local shim proves the adapter contract and benchmark gate; point `--adapter-command` at a real CrisisMode command to score its response shape, plan shape, benchmark results, and family coverage through the same report.

```sh
RUN_ROOT=benchmark-artifacts/crisismode-compatibility
rm -rf "$RUN_ROOT"
mkdir -p "$RUN_ROOT"

python3 -m incident_generator crisismode-compatibility \
  --strict \
  --json > "$RUN_ROOT/report.json"

python3 -m incident_generator crisismode-compatibility \
  --adapter-command "corepack pnpm@10.30.3 --dir ../crisismode exec tsx src/cli/index.ts bundle respond -" \
  --json > "$RUN_ROOT/real-command-report.json"

python3 -m incident_generator benchmark-runner \
  --benchmark-set harness/crisismode-compatibility-benchmark-set.yaml \
  --adapter-command "python3 -m incident_generator crisismode-adapter" \
  --judge-pack deterministic-local \
  --artifact-dir "$RUN_ROOT/benchmark" \
  --json > "$RUN_ROOT/result.json"

python3 -m incident_generator benchmark-runner \
  --benchmark-set harness/agent-adapter-benchmark-set.yaml \
  --input-mode investigation-session \
  --adapter-protocol stdio-jsonl \
  --adapter-command "python3 -m incident_generator crisismode-adapter --stdio-jsonl" \
  --judge-pack deterministic-local \
  --artifact-dir "$RUN_ROOT/v2-smoke" \
  --json > "$RUN_ROOT/v2-result.json"
```

When a sibling CrisisMode checkout is available, add `--crisismode-repo ../crisismode` to `crisismode-compatibility` to include built-in agent-family discovery in the strict gate. See [crisismode-support.md](crisismode-support.md) for the current coverage, limits, and next integration work.

## Terminal Experience Workflow

This path exercises the terminal replay, manual challenge, and follow surfaces without Docker, kind, provider credentials, or a browser.

```sh
RUN_ROOT=benchmark-artifacts/terminal-experience
rm -rf "$RUN_ROOT"
mkdir -p "$RUN_ROOT"

python3 -m incident_generator benchmark-runner \
  --benchmark-set harness/agent-adapter-benchmark-set.yaml \
  --input-mode investigation-session \
  --adapter-protocol stdio-jsonl \
  --skill-exposure routed-procedure \
  --artifact-dir "$RUN_ROOT/benchmark-runner-v2" \
  --json > "$RUN_ROOT/benchmark-result.json"

python3 -m incident_generator experience \
  --artifact-dir "$RUN_ROOT/benchmark-runner-v2" \
  --mode tail \
  --output-dir "$RUN_ROOT/tail" \
  --no-sleep

python3 -m incident_generator experience \
  --artifact-dir "$RUN_ROOT/benchmark-runner-v2" \
  --mode challenge \
  --output-dir "$RUN_ROOT/challenge" \
  --no-sleep
```

To watch a real appended progress stream without live infrastructure, start follow in one terminal:

```sh
python3 -m incident_generator experience \
  --artifact-dir "$RUN_ROOT/progress" \
  --mode follow \
  --output-dir "$RUN_ROOT/follow" \
  --poll-interval-seconds 1
```

Then run a fixture writer in another terminal:

```sh
python3 -m incident_generator run \
  --scenario scenarios/service/http-5xx-spike/canary-rollout \
  --collection-mode fixture \
  --progress-json \
  --progress-artifact-dir "$RUN_ROOT/progress" \
  --incident-session-id terminal-experience-fixture \
  --json
```

Follow mode prints new `events.ndjson` lines as they are appended and updates `$RUN_ROOT/follow/experience.json` plus `$RUN_ROOT/follow/timeline.ndjson`. The browser/static HTML export is intentionally not part of this workflow.

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
