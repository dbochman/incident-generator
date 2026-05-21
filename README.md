# Incident Generator

Exported deterministic incident environment generator for agent evaluation and benchmarking.

This package is generated from the canonical `sre-incident-agent-skills` repo. Make source changes there and export this package with `tools/export_incident_generator_package.py`; the standalone repo should not be hand-edited. It provides:

- `scenarios/` contains 41 scenario packages across Kubernetes, Linux, service, database, and network domains, with combinatorial run support for multi-failure-mode incidents.
- `harness/` contains the local `kind` and Docker Compose Linux VM harnesses plus supporting target apps, including the low-footprint `ecommerce-lite` main-app baseline for production-like non-Linux benchmark scenarios and the `app-host-lite` Linux host baseline.
- `evals/` and `skills/` provide deterministic fixture and benchmark metadata referenced by the scenario packages.
- `schemas/` contains published contracts for scenario packages, artifact registry entries, temporal/recovery benchmark definitions, and benchmark result comparison payloads.
- `incident_generator/` contains the standalone Python runner for listing, validating, and generating environments.

Fixture mode is the default and uses checked-in evidence. Real mode starts the declared environment archetype, applies the scenario seed, waits for symptom predicates, exposes provider endpoints where applicable, and tears down after the run.

For copy-paste benchmark workflows, see [docs/standalone-examples.md](docs/standalone-examples.md). For the production readiness plan, see [docs/production-roadmap.md](docs/production-roadmap.md).

## Quick Start

```sh
python3 -m incident_generator list
python3 -m incident_generator catalog
python3 -m incident_generator validate
python3 -m incident_generator run \
  --scenario scenarios/linux/disk-full/capacity \
  --collection-mode fixture \
  --json
```

Use `--hold` only when you want to inspect a generated real environment manually. Interrupt the process to trigger teardown.

Repeat `--scenario` to generate a combinatorial incident from multiple failure modes:

```sh
python3 -m incident_generator run \
  --scenario scenarios/linux/disk-full/capacity \
  --scenario scenarios/linux/memory-oom/oom-kill \
  --collection-mode fixture \
  --json
```

Use `--combination` to run one or more explicit multi-scenario sets. Each value is a comma-separated set of scenario paths, and repeating the flag generates a batch. Explicit combination batches default to real mode unless `--collection-mode fixture` is set for a dry run:

```sh
python3 -m incident_generator run \
  --combination scenarios/linux/disk-full/capacity,scenarios/linux/memory-oom/oom-kill \
  --combination scenarios/service/http-5xx-spike/dependency,scenarios/service/latency-spike/downstream-db \
  --collection-mode real \
  --require-tools \
  --json
```

Use `--random-compatible-combinations` to generate a non-deterministic batch of same-archetype combinations from the catalog. Random compatible batches also default to real mode; use `--random-combination-size` to choose how many scenarios are in each generated combination, `--random-archetype` to restrict sampling to one or more live archetypes, and `--random-seed` when you need to replay a smoke batch. When the candidate pool is enumerable, `run` uses the same seeded selection as `plan` and `pair-preview`:

```sh
python3 -m incident_generator run \
  --random-compatible-combinations 3 \
  --random-combination-size 2 \
  --random-archetype linux-vm \
  --random-seed 20260505 \
  --collection-mode real \
  --require-tools \
  --json
```

Use `plan` with the same combination selectors to preview compatibility decisions before live startup. The JSON report lists selected random sets, rejected candidates, expected hypotheses, aggregate `resource_claims`, per-scenario incompatibility reasons, and shared target-state conflicts:

```sh
python3 -m incident_generator plan \
  --random-compatible-combinations 3 \
  --random-combination-size 2 \
  --random-archetype linux-vm \
  --random-seed 20260505 \
  --json
```

Use `triple-preview` to render the checked fixed-seed fixture-mode triple benchmark list without starting infrastructure:

```sh
python3 -m incident_generator triple-preview --json
```

Use `pair-preview` to render the checked fixed-seed, real-compatible `kind` pair list for the next warm-kind random-8 chunk without starting infrastructure:

```sh
python3 -m incident_generator pair-preview --json
```

Use `temporal-model` to render the checked cascading benchmark model with ordered phases, delayed symptoms, changing expected hypotheses, and forward causal links:

```sh
python3 -m incident_generator temporal-model --json
```

Use `recovery-benchmark` to render checked post-diagnosis recovery cases with evidence references, Class 3 gates, and non-mutating dry-run recovery-plan boundaries:

```sh
python3 -m incident_generator recovery-benchmark --json
```

Use `adversarial-combos` to render checked fixture-mode prompt-injection combinations across Kubernetes event text, Linux journal output, and service logs:

```sh
python3 -m incident_generator adversarial-combos --json
```

Use `evidence-discipline-combos` to render checked fixture-mode missing-evidence, red-herring, abstention, and low-signal unknown combinations:

```sh
python3 -m incident_generator evidence-discipline-combos --json
```

Use `conflicting-signal-combos` to render checked fixture-mode deployment, dependency, rollback, and database conflict combinations with confidence ceilings:

```sh
python3 -m incident_generator conflicting-signal-combos --json
```

Use `confidence-calibration` to render the checked deterministic-vs-live confidence calibration snapshot:

```sh
python3 -m incident_generator confidence-calibration --json
```

Use `experience --mode tail` to replay retained benchmark artifacts as chronological terminal lines. It prefers v2 investigation transcripts, then benchmark traces, progress dashboards, benchmark results, and minimal event streams. It can write disposable `experience.json` and `timeline.ndjson` files:

```sh
python3 -m incident_generator experience \
  --artifact-dir .tmp/benchmark-runner-v2 \
  --mode tail \
  --output-dir .tmp/experience-tail \
  --generated-at 2026-05-06T00:00:00Z \
  --no-sleep
```

Use `experience --mode challenge --reveal-answers` to replay the investigation-visible tail, show the response questions, reveal the expected answers after Enter, generate the adapter-shaped response internally, and score it through the benchmark-result path:

```sh
python3 -m incident_generator experience \
  --artifact-dir .tmp/benchmark-runner-v2 \
  --mode challenge \
  --output-dir .tmp/manual-tail-challenge \
  --generated-at 2026-05-06T00:00:00Z \
  --no-sleep \
  --reveal-answers
```

From the repository root, `tools/run-interactive-tail-challenge.sh` generates fixture-safe v2 artifacts first, then starts paced tail playback, shows the questions, and waits for Enter before revealing the scored answer summary. The default pace is two seconds per tail line and can be overridden with `TAIL_PACE_SECONDS`.

Use `experience --mode follow` to watch an active progress artifact directory as `events.ndjson` grows. If the live event stream is absent but completed replay artifacts are present, it falls back to post-run terminal replay:

```sh
python3 -m incident_generator experience \
  --artifact-dir .tmp/incidents/20260506-kind-run \
  --mode follow \
  --output-dir .tmp/live-follow \
  --poll-interval-seconds 1
```

For real-mode `kind` batches, add `--warm-kind` to keep one cluster and ready observability stack across each run, while still tearing down per-scenario seeds and running a final cluster cleanup verification:

```sh
DOCKER_HOST=ssh://<ssh-host> \
SRE_AGENT_KIND_CREATE_TIMEOUT_SECONDS=600 \
SRE_AGENT_REMOTE_DOCKER_TIMEOUT_SECONDS=90 \
python3 -m incident_generator run \
  --random-compatible-combinations 4 \
  --random-combination-size 2 \
  --random-archetype kind \
  --random-seed 20260506 \
  --warm-kind \
  --require-tools \
  --json
```

`SRE_AGENT_KIND_CREATE_TIMEOUT_SECONDS` bounds cold `kind create` on Docker-over-SSH. When the cluster exists and `/etc/kubernetes/admin.conf` is readable, the harness can recover from a stuck remote create and continue with API readiness checks. `SRE_AGENT_REMOTE_DOCKER_TIMEOUT_SECONDS` bounds the remote Docker calls used to write the local tunneled kubeconfig.

```sh
python3 -m incident_generator doctor
python3 -m incident_generator run \
  --scenario scenarios/kubernetes/pending-pod/unschedulable \
  --collection-mode real \
  --variant k8s_version=1.29 \
  --require-tools \
  --progress \
  --hold
```

If a local live archetype is missing required tools, real mode falls back to fixture mode unless `--require-tools` is set.

## CLI Surface

| Command | Purpose |
| --- | --- |
| `python3 -m incident_generator list` | List scenario packages and their default variants. |
| `python3 -m incident_generator catalog` | Report scenario coverage by domain, archetype, evidence adapter, and live-readiness state. |
| `python3 -m incident_generator validate` | Validate scenario package structure, fixtures, executable hooks, and benchmark assets. |
| `python3 -m incident_generator plan` | Preview explicit or random combinatorial compatibility decisions without starting infrastructure. |
| `python3 -m incident_generator run` | Generate one fixture-backed or real incident environment; use repeated `--scenario`, `--combination`, or `--random-compatible-combinations` for combined incidents. |
| `python3 -m incident_generator noisy-fixture` | Render a deterministic noisy fixture manifest from checked fixture evidence, production-noise sources, and internal signal roles. |
| `python3 -m incident_generator noisy-smoke` | Render a deterministic noisy smoke report, defaulting to the checkout vertical smoke plan; pass `--smoke harness/noisy-database-live-smoke.yaml` for the database noisy-live smoke gate. |
| `python3 -m incident_generator noisy-partial-failures` | Render a deterministic noisy partial-failure pack report with false-attribution guards. |
| `python3 -m incident_generator pair-preview` | Render the fixed-seed real-compatible kind pair preview for the next warm-kind random-8 chunk. |
| `python3 -m incident_generator triple-preview` | Render the fixed-seed fixture-mode triple benchmark preview. |
| `python3 -m incident_generator temporal-model` | Render the ordered-phase cascading incident benchmark model. |
| `python3 -m incident_generator recovery-benchmark` | Render post-diagnosis recovery benchmark cases with safe dry-run gates and evidence-reference preservation. |
| `python3 -m incident_generator adversarial-combos` | Render fixture-mode prompt-injection benchmark combinations with forbidden-output guards. |
| `python3 -m incident_generator evidence-discipline-combos` | Render fixture-mode missing-evidence and red-herring benchmark combinations with abstention guards. |
| `python3 -m incident_generator conflicting-signal-combos` | Render fixture-mode conflicting-signal benchmark combinations with confidence-ceiling guards. |
| `python3 -m incident_generator confidence-calibration` | Render deterministic and recorded live LLM confidence observations against evidence-quality policy. |
| `python3 -m incident_generator benchmark-runner` | Run or replay one external adapter exchange, including fixture or read-only provider v2 investigation sessions, and emit `incident-generator.benchmark-result/v1`. |
| `python3 -m incident_generator experience` | Replay retained incident artifacts as a stream-specific terminal tail, a numbered manual challenge, or an appended-event live follow. |
| `python3 -m incident_generator judge-packs` | List checked deterministic, Tier 2 LLM, and mixed judge-pack selections for benchmark results. |
| `python3 -m incident_generator deterministic-replay-result` | Convert deterministic validated-combo replay summaries into `incident-generator.benchmark-result/v1`. |
| `python3 -m incident_generator llm-smoke-result` | Convert recorded fixture/live benchmark-combo LLM smoke summaries into `incident-generator.benchmark-result/v1` without rerunning providers. |
| `python3 -m incident_generator noisy-live-result` | Convert retained noisy live artifact-registry entries into `incident-generator.benchmark-result/v1` without rerunning live infrastructure. |
| `python3 -m incident_generator benchmark-sets` | List checked benchmark sets and aliases for fixture-only CI gates without Docker. |
| `python3 -m incident_generator result-comparison` | Render a Markdown comparison view across benchmark-result payload entrants. |
| `python3 -m incident_generator training-curriculum` | Validate and summarize the checked beginner/intermediate/advanced training drill ordering. |
| `python3 -m incident_generator skill-drill-export` | Export portable training bundles from reviewed golden and incorrect response seed libraries. |
| `python3 -m incident_generator doctor` | Report local tool availability for real modes. |
| `python3 -m incident_generator docs-check` | Check repository Markdown links. |
| `python3 -m incident_generator fixture-hygiene` | Scan fixture files for unallowlisted secrets and prompt-injection spillover. |
| `python3 -m incident_generator release-manifest` | Generate a release manifest with catalog, artifact, scenario, benchmark set, and resource-ceiling hashes/metadata. |
| `python3 -m incident_generator artifact-registry add` | Append a retained benchmark run to an artifact registry with hashes, host profile, state, and failure class. |
| `python3 -m incident_generator artifact-registry backfill` | Validate and write manifest-backed historical registry entries after a clean dry-run. |
| `python3 -m incident_generator artifact-registry check` | Validate registry metadata, retained paths, hashes, and redaction. |
| `python3 -m incident_generator artifact-registry markdown` | Render or check a Markdown view of benchmark registry entries. |

`run` supports operator progress output for real-mode inspection:

- `--progress` emits a human-readable lifecycle timeline to stderr.
- `--progress-json` emits newline-delimited JSON progress events to stderr.
- `--progress-artifact-dir <dir>` writes `events.ndjson`, `summary.json`, `dashboard.json`, and `dashboard.md`; when omitted with progress enabled, artifacts go under `.tmp/incidents/<incident-session-id>/`.

Progress events cover validation, archetype startup, seed application, provider port-forwards, wait predicate observations, selector resolution, holds, teardown, and cleanup verification. The dashboard artifacts are updated during the run and summarize phase timing, live container/image state where Docker inspection is available, seed checkpoints, wait predicates, and teardown status. Final `--json` output remains on stdout so automation can parse it separately from progress.

Run results include `failure_class` and `failure_classification` fields. `none` means no classified failure was observed; `adapter_runtime_issue` covers retriable Docker, kind, compose, tool, port-forward, or cleanup failures; `seed_predicate_runtime_issue` covers scenario seed, wait predicate, and selector failures; `resource_collision` covers incompatible combinatorial target state; and `agent_hypothesis_regression` is reserved for replay layers that detect missing expected hypotheses.

Use `artifact-registry add` after retaining `result.json`, `events.ndjson`, and `summary.json` for a benchmark run. The command computes sha256 hashes, redacts sensitive `--env KEY=VALUE` values, derives scenario ids, combination size, state, and failure class from `result.json`, and appends a `incident-generator.artifact-registry/v1` entry:

```sh
python3 -m incident_generator artifact-registry add \
  --registry benchmark-artifacts/registry.json \
  --artifact-dir .tmp/incidents/20260506-kind-random8 \
  --benchmark-set-id kind-random8-20260506 \
  --run-id 20260506-kind-random8 \
  --seed 20260506 \
  --host-profile kind/warm-batch \
  --docker-host-kind ssh \
  --docker-host ssh://<ssh-host> \
  --command "python3 -m incident_generator run --random-compatible-combinations 8 --random-seed 20260506 --warm-kind --json" \
  --env SRE_AGENT_KIND_CREATE_TIMEOUT_SECONDS=600 \
  --json
```

For new checked historical batches, run the manifest-backed dry-run before writing. The 2026-05-06 registry is already committed, so re-running that manifest against `benchmark-artifacts/registry.json` will correctly report duplicate run ids; use `artifact-registry check` for the committed state, or point `--registry` at a temporary path to smoke-test the manifest.

```sh
python3 -m incident_generator artifact-registry backfill \
  --manifest harness/artifact-registry-backfill-20260506.yaml \
  --registry benchmark-artifacts/registry.json \
  --dry-run \
  --json
```

Then gate the registry and generated operator view:

```sh
python3 -m incident_generator artifact-registry check \
  --registry benchmark-artifacts/registry.json \
  --json

python3 -m incident_generator artifact-registry markdown \
  --registry benchmark-artifacts/registry.json \
  --output benchmark-artifacts/registry.md

python3 -m incident_generator artifact-registry markdown \
  --registry benchmark-artifacts/registry.json \
  --check-output benchmark-artifacts/registry.md
```

## Benchmark Workflow

Use fixture previews first when defining a benchmark set:

```sh
python3 -m incident_generator pair-preview --json
python3 -m incident_generator triple-preview --json
python3 -m incident_generator adversarial-combos --json
python3 -m incident_generator evidence-discipline-combos --json
python3 -m incident_generator conflicting-signal-combos --json
python3 -m incident_generator temporal-model --json
python3 -m incident_generator recovery-benchmark --json
```

For a retained real run, write progress artifacts and keep stdout separately as `result.json`:

```sh
mkdir -p benchmark-artifacts/kind-random8
DOCKER_HOST=ssh://<ssh-host> \
SRE_AGENT_KIND_CREATE_TIMEOUT_SECONDS=600 \
python3 -m incident_generator run \
  --random-compatible-combinations 8 \
  --random-combination-size 2 \
  --random-archetype kind \
  --random-seed 20260506 \
  --warm-kind \
  --require-tools \
  --progress-artifact-dir benchmark-artifacts/kind-random8 \
  --json > benchmark-artifacts/kind-random8/result.json
```

Register retained artifacts with `artifact-registry add`, then compare deterministic replay, live LLM, noisy live artifact replay, or external entrants with `schemas/incident-generator-benchmark-result.schema.json`. The checked example `harness/benchmark-result-schema-example.json` shows how to record generated cases, entrant metadata, matched and missing hypotheses, evidence-discipline outcomes, abstention, uncertainty, false-attribution guards, separate-family judge results, and aggregate counts. `deterministic-replay-result` converts validated-combo replay summaries such as `harness/deterministic-replay-summary-example.json` into the result schema. `llm-smoke-result` converts `harness/benchmark-combo-llm-smoke-fixture-summary.json` and `harness/benchmark-combo-llm-smoke-live-summary.json` into the result schema without rerunning providers or storing credential values. `noisy-live-result` converts retained noisy live artifact-registry entries into the result schema by verifying registry hashes, the live run result, the noisy smoke report, loadgen metadata, cleanup summary, expected hypotheses, abstention expectations, and evidence-role counts without restarting kind. External entrants can use `schemas/incident-generator-agent-adapter.schema.json`, `harness/agent-adapter-contract-example.json`, and `harness/agent-adapter-benchmark-set.yaml` for default v1 redacted evidence requests and structured response handoffs. `benchmark-runner` replays one checked exchange with runner-only expectation flags, runs `--benchmark-set` to merge selected adapter cases including a fixture-safe mutation-gate case, or runs v2 sessions with `--input-mode investigation-session --adapter-protocol stdio-jsonl --skill-exposure ...`; add `--execute-real-provider-tools --provider-profile <profile>` to execute checked read-only provider contracts, and `--allow-sensitive-tools` only when sensitive adapters are policy-approved. v2 artifacts retain session start, investigation transcript, per-tool results, final response, trace, and transcript files. `crisismode-compatibility` runs the checked CrisisMode support gate for the local shim and optional sibling CrisisMode agent-family discovery; `docs/crisismode-support.md` tracks the current progress, limits, and next integration work. `result-comparison` renders Markdown comparison tables from checked defaults or repeated `--result` payloads. `benchmark-sets` lists all checked benchmark set ids and aliases without Docker, and `make fixture-benchmark-gate` runs `validate`, `catalog`, and `benchmark-sets` as the CI-safe benchmark listing gate. `harness/alpha-benchmark-sets.yaml` publishes stable alpha aliases for public benchmark groups, `docs/live-run-reproducibility.md` defines what may drift in live reruns, `docs/standalone-examples.md` provides copy-paste benchmark workflows, `harness/golden-response-seeds.yaml` publishes the first reviewed evidence-cited supervised responses for training drills, `harness/incorrect-response-seeds.yaml` publishes labeled training negatives for common response failure modes, and `harness/training-curriculum-order.yaml` orders those drills by difficulty and domain. `--judge-pack deterministic-local` records executed deterministic judge outcomes; Tier 2 and mixed judge packs are selected metadata and fail closed until live judge execution is implemented. Mutation-gate scoring records `action_safety` and `action_policy_pass` for dry-run Class 3 proposals that cite visible evidence and require human approval. `--artifact-dir` retains `result.json`, `summary.json`, `events.ndjson`, `trace.json`, `trace.md`, per-case request/response or session/response files, and per-case `transcript.md` views. Progress artifact directories also update `dashboard.md` with a `Live Look` section for recent phase events, runtime state, wait-predicate observations, seed checkpoints, and teardown status. See [docs/standalone-examples.md](docs/standalone-examples.md), [docs/benchmark-result-schema.md](docs/benchmark-result-schema.md), [docs/benchmark-result-comparison.md](docs/benchmark-result-comparison.md), [docs/noisy-database-live-smoke.md](docs/noisy-database-live-smoke.md), [docs/alpha-benchmark-sets.md](docs/alpha-benchmark-sets.md), [docs/live-run-reproducibility.md](docs/live-run-reproducibility.md), [docs/golden-response-seeds.md](docs/golden-response-seeds.md), [docs/incorrect-response-seeds.md](docs/incorrect-response-seeds.md), [docs/training-curriculum.md](docs/training-curriculum.md), [docs/agent-adapter-contract.md](docs/agent-adapter-contract.md), [docs/crisismode-support.md](docs/crisismode-support.md), and [docs/judge-pack-selection.md](docs/judge-pack-selection.md).

```sh
python3 -m incident_generator benchmark-runner \
  --expected-hypothesis "database connection pool exhaustion is causing checkout failures" \
  --adapter-command "./run_external_agent_adapter" \
  --json

python3 -m incident_generator benchmark-runner \
  --benchmark-set harness/agent-adapter-benchmark-set.yaml \
  --judge-pack deterministic-local \
  --artifact-dir benchmark-artifacts/external-agent-adapter-smoke \
  --json

python3 -m incident_generator deterministic-replay-result \
  --summary harness/deterministic-replay-summary-example.json \
  --benchmark-set-id kind-curated-pairs-warm-20260506 \
  --json

python3 -m incident_generator llm-smoke-result \
  --include both \
  --json

python3 -m incident_generator noisy-smoke \
  --smoke harness/noisy-database-live-smoke.yaml \
  --json

python3 -m incident_generator noisy-live-result \
  --run-id 20260506-noisy-live-checkout-canary-5xx \
  --json

python3 -m incident_generator result-comparison \
  --created-at 2026-05-06T00:00:00Z \
  --json

python3 -m incident_generator skill-drill-export \
  --output-dir dist/training-drills \
  --created-at 2026-05-06T00:00:00Z \
  --json
```

Cut release provenance with `release-manifest`:

```sh
python3 -m incident_generator release-manifest \
  --artifact-dir dist \
  --output dist/release-manifest.json \
  --json
```

The `benchmark_release` section records per-scenario sha256 tree hashes, stable benchmark set ids, alpha benchmark-set aliases, golden response seed refs, incorrect response seed refs, training curriculum ordering, skill drill export provenance, checked judge packs, fixed seeds, checked source hashes, supported Docker/kind host profiles, runtime assumptions, timeout defaults, and known limitations. See [docs/benchmark-release-manifest.md](docs/benchmark-release-manifest.md), [docs/alpha-benchmark-sets.md](docs/alpha-benchmark-sets.md), [docs/live-run-reproducibility.md](docs/live-run-reproducibility.md), [docs/golden-response-seeds.md](docs/golden-response-seeds.md), [docs/incorrect-response-seeds.md](docs/incorrect-response-seeds.md), [docs/training-curriculum.md](docs/training-curriculum.md), and [docs/skill-drill-export.md](docs/skill-drill-export.md).

Turn benchmark incidents into reusable skill drills with [docs/training-authoring-guide.md](docs/training-authoring-guide.md), [docs/training-curriculum.md](docs/training-curriculum.md), and `skill-drill-export`. The command writes `provenance.json`, learner-facing `drill.md`, reviewer-facing `expected-evidence.yaml`, `supervised-response.md`, linked `incorrect-responses.yaml`, and top-level `curriculum.json` files under `dist/training-drills` by default. The first checked positive seed library is [docs/golden-response-seeds.md](docs/golden-response-seeds.md), backed by `harness/golden-response-seeds.yaml`; the first checked negative seed library is [docs/incorrect-response-seeds.md](docs/incorrect-response-seeds.md), backed by `harness/incorrect-response-seeds.yaml`.

Combinatorial runs bundle multiple scenario contracts into one incident result. Fixture-mode combinations can span domains and archetypes because no infrastructure is started. Real-mode combinations require all selected scenarios to share the same `environment_archetype` and avoid overlapping or declared-conflicting `resource_claims`, so the runner can bring up one harness, apply each seed, check each symptom, and tear everything down once. `plan` reports those decisions without starting Docker, kind, or the Linux VM harness, including each candidate's expected hypotheses, aggregate resource claims, per-scenario incompatibility reasons, and target-state conflicts. `pair-preview` renders the checked seed `20260506` no-startup preview of eight real-compatible `kind` pairs selected from 476 eligible pairs, preserving resource claims for the next warm-kind random-8 chunk. `run --random-compatible-combinations 8 --random-archetype kind --random-seed 20260506` reuses the current audited enumerable selection; retained 2026-05-06 warm-kind random-8 artifacts remain green under the pre-audit pool. `triple-preview` renders the checked seed `20260506` fixture-mode benchmark preview, preserving eight selected triples from 84 candidates with scenario ids, compatibility decisions, and expected hypothesis sets. `temporal-model` renders the checked cascading model for phase order, delayed symptoms, hypothesis add/remove transitions, and forward causality. `recovery-benchmark` renders the checked post-diagnosis recovery cases for evidence-reference preservation, Class 3 gates, and non-mutating dry-run recovery plans. `adversarial-combos` renders prompt-injection combinations across scheduler events, Linux journal output, and service logs while preserving forbidden-output guard metadata for replay checks. `evidence-discipline-combos` renders missing-evidence, red-herring, abstention, and low-signal unknown combinations while preserving expected hypotheses, forbidden-hypothesis guards, and action-abstention expectations for replay checks. `conflicting-signal-combos` renders deploy-vs-dependency, rollback-vs-dependency, and latency-vs-database conflict combinations while preserving competing hypotheses, confidence ceilings, investigation terms, and no-premature-action guards for replay checks. `confidence-calibration` renders deterministic and recorded live LLM confidence observations against the checked evidence-quality policy. `--combination` and `--random-compatible-combinations` default to real mode because they are intended for live incident generation; pass `--collection-mode fixture` to preview deterministic fixture-mode triples or larger sets without starting infrastructure. Use repeated `--random-archetype` values to focus random batches on smaller archetype pools without writing a manual sampler. Use `--warm-kind` only for real-mode `kind` batches; intermediate teardown keeps the cluster but removes run-local kubeconfigs, and the batch records a final cleanup result under `warm_kind.cleanup`. The curated 4-pair cross-domain `kind` batch passed both cold and warm live runs; the 2026-05-06 warm rerun generated `4/4` with final retained-cluster cleanup verified.

With the current 41-scenario catalog, unique combinations are counted as unordered sets of two or more distinct scenarios:

| Mode | Supported combinations | Pairwise combinations | Constraint |
| --- | ---: | ---: | --- |
| Fixture | 2,199,023,255,510 | 820 | Any catalog scenarios can be combined. |
| Real | 94,371,857 | 499 | Scenarios must share one live archetype and cannot share exclusive or declared-conflicting live resources. |

The real-mode total comes from 32 `kind` scenarios and 9 `linux-vm` scenarios after excluding warm-kind CoreDNS overrides, checkout deployment metadata, node-pressure label, queue messaging-evidence collisions, certificate/TLS target collisions, and Linux target-resource collisions across disk fillers, CPU saturators, memory-pressure variants, and OOM event files. Cross-archetype combinations still work in fixture mode and are blocked in real mode with an explicit compatibility reason.

The `Makefile` wraps the local development gates:

```sh
make list
make catalog
make validate
make smoke
make doctor
make docs-check
make fixture-hygiene
make lint
make test
make package
make release-manifest
make release-check
```

## Scenario Package Anatomy

Each scenario directory contains a `scenario.yaml` contract plus supporting assets:

- `scenario.yaml`: metadata, target skill, fixture path, environment archetype, inputs, required evidence adapters, expected hypotheses and actions, forbidden actions, success criteria, latency budget, variants, and optional cross-incident metadata.
- `expect.yaml`: wait predicates and expected behavior used by real-mode symptom checks.
- `infra/`: scenario-specific environment notes.
- `seed/`: manifests or scripts that create the incident state.
- `inject.sh` and `cleanup.sh`: executable hooks required by validation.

`scenario.yaml` can also include optional benchmark workload metadata. `workload_profile` records the workload id, main service, warm-up seconds, load-generator seed, RPS/concurrency, traffic mix, dependency fanout, retry behavior, and noise profile. `incident_injection` records the causal injection kind, `starts_after_warmup`, causal signal sources, and the expected hypothesis to preserve. Existing scenarios do not need these fields, but validation rejects malformed workload metadata when present.

The runner currently supports the `fixture`, `kind`, and `linux-vm` archetypes. The `eks-staging` Terraform skeleton exists under `harness/archetypes/eks-staging/`, but runner dispatch for that archetype is intentionally not implemented yet.

## Live Harnesses

`kind` scenarios use an isolated kubeconfig under `.tmp/`, install local observability components, apply the scenario seed, start port-forwards for provider endpoints, wait for configured predicates, and tear down the cluster.

`linux-vm` scenarios use Docker Compose to run a target Linux container plus local Prometheus and Tempo services. The target starts the bounded `app-host-lite` worker baseline before incident injection, scenario seeds are copied into the target container before execution, and cleanup removes the Compose project and volumes.

Before using real mode, run:

```sh
python3 -m incident_generator doctor
```

Real mode is for controlled harnesses and staging-like environments. Do not point scenario seeds at production infrastructure without completing the production gates in [docs/production-roadmap.md](docs/production-roadmap.md).

Real-mode JSON results include `teardown_failures` and `context.teardown` when live infrastructure was attempted, so operators can verify whether cleanup completed.

The `harness/ecommerce-lite/apply.sh` helper installs the shared `kind` baseline for future noisy benchmark slices: storefront, gateway, checkout/search/profile/edge APIs, Postgres background load, async-role pods, deploy metadata, ServiceMonitors, and a checked traffic profile. It is not required for existing clean scenario runs unless a scenario explicitly opts into that workload profile. See [docs/ecommerce-lite-baseline.md](docs/ecommerce-lite-baseline.md).

The `harness/ecommerce-lite/loadgen-preview.py` and `harness/ecommerce-lite/apply-loadgen.sh` helpers provide deterministic request previews and optional sustained live traffic against ecommerce-lite before incident injection. See [docs/ecommerce-lite-load-generator.md](docs/ecommerce-lite-load-generator.md).

The `harness/production-noise-source-catalog.yaml` file enumerates non-causal production-like signal sources for noisy benchmark runs, including benign HTTP errors, retries, slow normal requests, queue/database/platform/edge/Linux noise, and deploy metadata. See [docs/production-noise-source-catalog.md](docs/production-noise-source-catalog.md).

The `harness/evidence-signal-role-taxonomy.yaml` file defines internal `causal`, `contextual`, `ambient`, `red_herring`, and `hostile` evidence labels for noisy renderers, rubrics, and benchmark summaries. See [docs/evidence-signal-role-taxonomy.md](docs/evidence-signal-role-taxonomy.md).

The `incident_generator noisy-fixture` command renders deterministic noisy fixture manifests from checked fixture outputs, production-noise source IDs, and internal signal roles. See [docs/noisy-fixture-renderer.md](docs/noisy-fixture-renderer.md).

The `incident_generator noisy-smoke` command renders the first checkout-api noisy vertical smoke report across HTTP 5xx, latency, database, Kubernetes, and network scenarios. It can also render the database-domain live setup gate with `--smoke harness/noisy-database-live-smoke.yaml`. See [docs/noisy-checkout-vertical-smoke.md](docs/noisy-checkout-vertical-smoke.md) and [docs/noisy-database-live-smoke.md](docs/noisy-database-live-smoke.md).

The `incident_generator noisy-partial-failures` command renders the fixture-mode partial-failure pack for tolerated setup gaps, missing wait evidence, degraded-but-not-down symptoms, and unrelated red-herring noise. See [docs/noisy-partial-failure-pack.md](docs/noisy-partial-failure-pack.md).

The ecommerce-lite chart also renders an `edgeGatewayProfile` for DNS/TLS/certificate benchmark slices. It maps `edge-api` and `api-gateway` traffic, DNS retries, normal TLS handshakes, certificate probes, and unrelated edge errors to the five edge scenarios' workload metadata. See [docs/edge-gateway-baseline-mapping.md](docs/edge-gateway-baseline-mapping.md).

The `linux-target` container starts the shared `app-host-lite` baseline for Linux benchmark slices: a healthchecked worker, heartbeat, rotated logs, journald-shaped entries, temp churn, small disk writes, low CPU/memory pressure, and benign service noise. See [docs/app-host-lite-baseline.md](docs/app-host-lite-baseline.md).

For failed cleanup, use [docs/runbooks/live-cleanup.md](docs/runbooks/live-cleanup.md). For approved operator-run live smoke checks, use `make live-smoke PYTHON=/path/to/python3.10-or-newer`.

## Development Notes

Run the deterministic gates before changing scenario contracts, runner behavior, or fixture paths:

```sh
make validate
make smoke
make docs-check
make fixture-hygiene
make lint
make test
```

Use `make release-check` before cutting an internal release candidate. It runs syntax checks, strict scenario validation, catalog reporting, fixture smoke, docs link checks, fixture hygiene, unit tests, a wheel build, and release manifest generation. Set `PYTHON=/path/to/python3.10-or-newer` if the system `python3` is older than the package requirement.

When adding a scenario:

1. Add the `scenario.yaml`, `expect.yaml`, `infra/`, `seed/`, `inject.sh`, and `cleanup.sh` files.
2. Link a fixture directory with `fixture.yaml` and `outputs/`.
3. Link the skill under test and required evidence adapters.
4. Add or update the relevant eval fixture and rubric metadata.
5. Run `python3 -m incident_generator validate --scenario <scenario-dir>`.

## Repository Status

This project is hosted as a public GitHub repository. The Python package is not published.
