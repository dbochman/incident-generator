# Production Roadmap

This document describes the path from the current standalone incident generator to a production-ready internal service or release artifact. "Production" here means a supported, repeatable, observable tool for generating deterministic incident environments in approved harnesses and staging-like accounts. It does not mean fault injection against customer or business-production systems by default.

## Current Baseline

The repository currently has these production-relevant foundations:

| Area | Current state | Evidence |
| --- | --- | --- |
| Source governance | Package source is generated from the canonical `sre-incident-agent-skills` repository; standalone repo updates should come from `tools/export_incident_generator_package.py`, not hand edits. | `CANONICAL_SOURCE.md`, `make incident-generator-export-check` in the canonical repo |
| CLI runner | Supports `list`, `catalog`, `validate`, `run`, `plan`, `noisy-fixture`, `noisy-smoke`, `noisy-partial-failures`, `pair-preview`, `triple-preview`, `temporal-model`, `recovery-benchmark`, `adversarial-combos`, `evidence-discipline-combos`, `conflicting-signal-combos`, `benchmark-runner`, `judge-packs`, `deterministic-replay-result`, `llm-smoke-result`, `noisy-live-result`, `benchmark-sets`, `result-comparison`, `training-curriculum`, `skill-drill-export`, `artifact-registry`, `release-manifest`, and `doctor`; `run` accepts repeated `--scenario`, explicit `--combination` sets, seeded archetype-scoped `--random-compatible-combinations`, and `--warm-kind` reuse for real-mode kind batches. | `incident_generator/cli.py` |
| Scenario catalog | 41 valid scenario packages across database, Kubernetes, Linux, network, and service domains. | `python3 -m incident_generator list --json` and `validate --json` |
| Combinatorial breadth | Current catalog supports 2,199,023,255,510 unordered fixture-mode combinations of two or more incidents, including 820 pairwise combinations. Real mode supports 94,371,857 same-archetype and shared-resource-safe combinations, including 499 pairwise combinations, across 32 `kind` and 9 `linux-vm` scenarios. Explicit and random batch flags default to real mode, with fixture mode available for previews; random batches can be constrained with `--random-archetype` and replayed with `--random-seed`. `pair-preview` preserves the checked seed `20260506` no-startup list of eight real-compatible `kind` pairs for the next warm-kind random-8 chunk, `triple-preview` preserves the checked fixed-seed fixture-mode benchmark list of eight selected triples from 84 candidates before live startup, `temporal-model` preserves the first ordered-phase cascading incident contract, and `recovery-benchmark` preserves the post-diagnosis dry-run recovery contract. The full compatible `linux-vm` pair pool has passed live (`23/23`), and a curated cross-domain `kind` pair smoke has passed cold and warm live runs (`4/4`). `--warm-kind` reduces kind batch setup time while preserving final cleanup verification. | Repeated `--scenario` runs, `--combination`, `--random-compatible-combinations`, `pair-preview`, `triple-preview`, `temporal-model`, `recovery-benchmark`, `--warm-kind`, `stand_up_combinatorial_incident_environment`, `tests/test_cli.py`, `tests/test_benchmark_previews.py`, `tests/test_temporal_benchmarks.py`, `tests/test_recovery_benchmarks.py`, `benchmark-artifacts/registry.json`, `docs/findings/combinatorial-test-2026-05-05.md` |
| Deterministic mode | Fixture mode is default and does not start infrastructure. | `stand_up_incident_environment(... collection_mode=fixture ...)` |
| Local live harnesses | `kind` and `linux-vm` dispatch paths exist with preflight checks and teardown. | `incident_generator/scenarios.py`, `incident_generator/scenario_runtime.py` |
| Cloud fidelity | EKS Terraform skeleton exists, but runner dispatch is not implemented. | `harness/archetypes/eks-staging/`, `eks-staging` blocked result |
| Provider contracts | Evidence command contracts, provider profiles, endpoint rewriting, input allowlists, and parser fixtures exist. | `incident_generator/provider_contracts.py`, `evals/real-evidence-cli-fixtures/` |
| Contract hardening | Scenario validation checks schema-like field types, supported wait predicates, archetype/predicate compatibility, and required fixture outputs. | `incident_generator/scenarios.py`, `tests/test_cli.py` |
| Catalog reporting | Catalog report groups scenarios by domain, archetype, evidence adapter, and live-readiness state. | `python3 -m incident_generator catalog --json` |
| Hygiene gates | Markdown link checking and fixture secret/prompt-injection hygiene checks are implemented. | `incident_generator/checks.py`, `evals/fixture-hygiene-allowlist.yaml` |
| CI and release gate | CI runs a release gate for syntax, fixture-only benchmark validation/listing, fixture smoke, docs links, fixture hygiene, tests, package build, and release manifest generation. | `.github/workflows/ci.yml`, `make fixture-benchmark-gate`, `make release-check` |
| Release manifest | Release manifest records package metadata, git SHA, scenario catalog hash, per-scenario hashes, benchmark set ids, alpha benchmark aliases, golden response seed refs, incorrect response seed refs, training curriculum ordering, skill drill export provenance, judge-pack selections, fixed seeds, supported host profiles, runtime assumptions, known limitations, schema version, and artifact checksums. | `python3 -m incident_generator release-manifest --json`, `docs/benchmark-release-manifest.md`, `docs/alpha-benchmark-sets.md`, `docs/golden-response-seeds.md`, `docs/incorrect-response-seeds.md`, `docs/training-curriculum.md`, `docs/skill-drill-export.md` |
| Live reproducibility | Live benchmark comparison is based on release hashes, alias membership, generated counts, failure classes, teardown state, and replay outcomes; wall-clock timing and sampled live measurements are allowed to drift within configured timeouts. | `docs/live-run-reproducibility.md` |
| Artifact registry | `artifact-registry add`, `backfill`, `check`, and `markdown` index retained benchmark runs by run id, benchmark set, seed, scenario ids, host profile, command, environment fingerprint, retained paths, hashes, state, and failure class. | `incident_generator/artifact_registry.py`, `schemas/incident-generator-artifact-registry.schema.json` |
| Benchmark result contract | `incident-generator.benchmark-result/v1` records generated cases, deterministic and LLM entrants, evidence discipline, abstention, uncertainty, false-attribution guards, judge outcomes, failure classes, artifact refs, and aggregates. | `schemas/incident-generator-benchmark-result.schema.json`, `harness/benchmark-result-schema-example.json`, `docs/benchmark-result-schema.md` |
| Deterministic replay result payloads | `deterministic-replay-result` converts validated-combo deterministic replay summaries into schema-valid benchmark-result payloads. | `incident_generator/deterministic_replay_results.py`, `harness/deterministic-replay-summary-example.json` |
| LLM smoke result payloads | `llm-smoke-result` converts recorded fixture/live benchmark-combo LLM smoke summaries into schema-valid benchmark-result payloads without rerunning providers or storing credential values. | `incident_generator/llm_smoke_results.py`, `harness/benchmark-combo-llm-smoke-fixture-summary.json`, `harness/benchmark-combo-llm-smoke-live-summary.json` |
| Noisy live result payloads | `noisy-live-result` converts retained noisy live artifact-registry entries into schema-valid benchmark-result payloads without rerunning live infrastructure; the checkout canary and database pool-exhaustion noisy live runs are both registered and replayable with the same payload shape. | `incident_generator/noisy_live_results.py`, `benchmark-artifacts/registry.json`, `harness/noisy-database-live-smoke.yaml`, `docs/noisy-database-live-smoke.md` |
| Benchmark result comparison | `result-comparison` renders Markdown tables across deterministic replay, fixture/live LLM, noisy live, and external adapter result payloads. | `incident_generator/result_comparison.py`, `docs/benchmark-result-comparison.md` |
| External agent adapter contract | `incident-generator.agent-adapter/v1` records redacted benchmark requests and structured external-agent responses without exposing internal evidence roles or expected answers. | `schemas/incident-generator-agent-adapter.schema.json`, `harness/agent-adapter-contract-example.json`, `harness/agent-adapter-abstention-example.json`, `harness/agent-adapter-mutation-gate-example.json`, `docs/agent-adapter-contract.md` |
| Judge pack selection | `judge-packs` lists checked deterministic, Tier 2 LLM, and mixed judge selections with separate-family requirements and fail-closed live-judge boundaries. | `harness/agent-adapter-judge-packs.yaml`, `docs/judge-pack-selection.md` |
| Benchmark runner | `benchmark-runner` replays one checked adapter exchange or a selected adapter benchmark-set manifest, can invoke a local adapter command with each redacted request on stdin, and emits one `incident-generator.benchmark-result/v1` payload with optional retained artifacts and deterministic judge-pack outcomes. It also supports fixture-safe v2 investigation sessions with `--input-mode investigation-session --adapter-protocol stdio-jsonl`, hidden runner-side evidence, typed tool replay, sandbox command emulation, and discovered-evidence-id scoring. | `incident_generator/benchmark_runner.py`, `python3 -m incident_generator benchmark-runner --benchmark-set --judge-pack deterministic-local --json` |
| Training authoring | Benchmark incidents can be converted into reviewed skill drills, supervised-response examples, and labeled incorrect-response examples with provenance, redaction, expected evidence, negative examples, curriculum ordering, and validation gates; `skill-drill-export` materializes the first positive and negative seed libraries into portable bundles. | `incident_generator/training_curriculum.py`, `incident_generator/skill_drill_export.py`, `docs/training-authoring-guide.md`, `docs/training-curriculum.md`, `docs/skill-drill-export.md`, `docs/golden-response-seeds.md`, `docs/incorrect-response-seeds.md`, `harness/training-curriculum-order.yaml`, `harness/golden-response-seeds.yaml`, `harness/incorrect-response-seeds.yaml` |
| Operator runbooks | Failed live cleanup and operator-run live smoke paths are documented. | `docs/runbooks/live-cleanup.md`, `harness/live-smoke.sh` |

Known gaps before production:

- The package is versioned as `0.1.0` and is not published.
- `eks-staging` runner dispatch and seed execution are explicitly blocked.
- Representative real-mode live matrix execution is not automated in CI.
- Real-mode combinatorial runs are intentionally constrained to one `environment_archetype` and non-overlapping, non-conflicting `resource_claims`; cross-archetype combinations are fixture-only until multi-harness orchestration is designed.
- `benchmark-runner` selected-set orchestration is fixture-safe and local-subprocess only; Tier 2 and mixed judge packs fail closed until live judge execution is implemented.
- There is no SBOM, vulnerability scan, or signed artifact process.
- Operational ownership, incident response, audit retention, and deprecation policy are not yet documented.

## Production Principles

- Keep fixture mode deterministic and credential-free. It remains the default path for CI and local development.
- Treat live mode as a controlled harness feature. Require explicit operator intent for real infrastructure, and keep `--require-tools` available for hard failures instead of silent fallback.
- Prefer isolated, short-lived environments. Every live run must have scoped names, tags, teardown, and a leak check.
- Separate evidence collection from mutation. Inspection adapters should remain read-only; scenario seeds and cleanup hooks are the only planned mutation points.
- Promote by gates, not by dates. Each phase exits only when its acceptance checks pass repeatedly.

## Roadmap

### Phase 0: Documentation and Baseline Hygiene

Goal: make the current system understandable, runnable, and auditable by a new maintainer.

Deliverables:

- Root README explains the CLI, scenario anatomy, harnesses, local gates, and production roadmap link.
- Production roadmap defines scope, phases, gates, known gaps, and risks.
- Harness READMEs clearly state whether an archetype is runnable, planned, or blocked.
- Scenario authoring rules are consolidated and agree with `validate_scenario_package`.

Exit gate:

- `make validate`, `make smoke`, and `make test` pass locally.
- A maintainer can run one fixture scenario and understand why real mode may fall back to fixture mode.

### Phase 1: Contract Hardening

Goal: make scenario packages and fixtures stable enough for automated review.

Deliverables:

- Add a versioned JSON Schema or equivalent validator for `ScenarioPackage`.
- Extend validation to cover `expect.yaml` wait predicate shape, supported predicate kinds, unsupported archetype/predicate combinations, and fixture output references.
- Add a scenario catalog report grouped by domain, archetype, evidence adapters, and live-readiness state.
- Add a fixture hygiene scanner for credentials, production hostnames, raw personal data, and prompt-injection spillover into expected outputs.
- Document compatibility expectations for `apiVersion: sre-agent-scenario/v1alpha1`.

Exit gate:

- All 41 scenarios pass strict schema validation.
- A malformed scenario fixture, missing wait predicate, unsafe input, and non-executable hook each fail with clear diagnostics.
- Fixture hygiene scanner has regression tests and a documented allowlist process for intentionally fake secrets.

### Phase 2: Local Real-Mode Reliability

Goal: make `kind` and `linux-vm` live execution reliable enough for repeated operator and CI-like use on approved hosts.

Deliverables:

- Define a representative live matrix for Kubernetes, Linux, service, database, and network scenarios.
- Record required tool versions for `docker`, Docker Compose v2, `kind`, `kubectl`, `helm`, and `curl`.
- Add preflight checks for disk space, port conflicts, Docker daemon state, Kubernetes context isolation, and stale `.tmp/` artifacts.
- Add teardown verification for kind clusters, Compose projects, volumes, port-forward processes, and temporary kubeconfigs.
- Add structured run output that includes phase timings, selected variants, active provider endpoints, fallback reason, and cleanup status.
- Add real-mode tests with mocked subprocess boundaries plus operator-run live smoke scripts.

Exit gate:

- Representative `kind` and `linux-vm` scenarios pass `--collection-mode real --require-tools` repeatedly on a clean host; the full compatible `linux-vm` pair pool has passed live (`23/23` on 2026-05-05), and the curated cross-domain `kind` pair smoke has passed cold (`4/4` on 2026-05-05) and warm (`4/4` on 2026-05-06) live runs.
- Failed seed, wait timeout, selector failure, port-forward failure, and interrupt paths all run cleanup and report actionable blocking reasons.
- Live runs leave no kind cluster, Compose project, named volume, port-forward process, or temporary kubeconfig behind.

### Phase 3: Evidence Adapter and Parser Productionization

Goal: make evidence collection contracts safe, parseable, and observable for real provider use.

Deliverables:

- Promote provider contracts from metadata to an executable adapter layer with timeouts, redaction, structured errors, and preview mode.
- Add parser tests for every required evidence adapter in the scenario catalog.
- Add per-adapter safety allowlists for inputs, commands, environment variables, output size, and redaction.
- Document provider profile resolution, endpoint rewriting, and local port-forward behavior.
- Add traceable evidence manifests that map scenario inputs to collected outputs without storing secrets.

Exit gate:

- Every adapter required by the scenario catalog has success, non-zero, timeout, and preview fixtures.
- Adapter execution cannot run with missing allowlists, unresolved templates, oversized input, or unredacted known secret patterns.
- Evidence manifests are deterministic in fixture mode and complete in real mode.

### Phase 4: Staging Cloud Fidelity

Goal: support cloud-like staging without widening blast radius.

Deliverables:

- Implement `eks-staging` dispatch with Terraform create-run-destroy flow, explicit state location, and run-scoped tags.
- Add AWS account guardrails: sandbox-only credentials, budgets, IAM least privilege, region allowlist, and cluster name ownership checks.
- Add CloudWatch, Prometheus, Loki, Tempo, and fake PagerDuty integration checks for cloud runs.
- Add network egress controls, namespace isolation, and cleanup verification.
- Document operator runbooks for provisioning, running, destroying, and recovering from partial failure.

Exit gate:

- `eks-staging` refuses to run without sandbox account confirmation, run ID, budget tag, and destroy plan.
- One representative Kubernetes, service, and database scenario completes in EKS staging with evidence captured and teardown verified.
- A failed Terraform apply, failed seed, failed wait, and failed destroy each produce a recovery path and audit record.

### Phase 5: Release, CI, and Operations

Goal: make the project supportable as an internal production tool.

Deliverables:

- Add CI for lint, unit tests, strict scenario validation, fixture smoke, docs link checks, and package build.
- Publish an internal package or container image with pinned dependencies and changelog entries.
- Generate a release manifest with git SHA, package version, scenario catalog hash, per-scenario hashes, benchmark set ids, fixed seeds, resource ceilings, known limitations, schema version, and artifact checksums.
- Add SBOM generation and dependency vulnerability scanning.
- Add operational docs for ownership, support hours, escalation, rollback, deprecation, and incident response.
- Add observability for run counts, failure categories, cleanup failures, live fallback events, adapter latencies, and scenario duration.

Exit gate:

- Every release candidate has green CI, signed artifacts, a release manifest, and a documented rollback path.
- Operators have a runbook for failed live runs and stale resource cleanup.
- Production support ownership is explicit before broader adoption.

### Phase 6: Controlled Production Adoption

Goal: allow approved teams to use the generator in production-adjacent workflows without unbounded risk.

Deliverables:

- Define approved use cases: CI fixture benchmarking, local harness evaluation, shared staging drills, and synthetic production namespace drills.
- Add policy gates for live execution: environment allowlist, destructive-action denylist, approval record, change window, and budget controls.
- Add audit logging for operator identity, command, scenario, variants, target environment, evidence artifacts, and cleanup result.
- Add compatibility tests for supported platform versions and deprecation windows.
- Add documentation for tenant onboarding, quota, retention, and data handling.

Exit gate:

- Production-labeled use is limited to approved synthetic targets or staging-like environments.
- Every live run has an approval record, audit artifact, cleanup verification, and owner acknowledgement.
- Rollback and disable paths have been tested and documented.

## Release Gates

Before any production-labeled release, verify:

- `python3 -m incident_generator validate --json` reports all scenarios valid.
- `make smoke` completes a deterministic fixture run.
- `make test` passes.
- Strict schema validation and fixture hygiene checks pass.
- Representative live matrix passes with `--require-tools` on approved hosts.
- Package build, SBOM, vulnerability scan, and artifact signing pass.
- Docs link check passes for README, roadmap, harness docs, and scenario authoring docs.
- A release manifest records package version, git SHA, scenario catalog hash, per-scenario hashes, benchmark set ids, fixed seeds, resource ceilings, known limitations, schema version, and artifact checksums.
- Benchmark result schema examples remain valid JSON and are documented for downstream comparison tooling.
- Rollback, cleanup, and support runbooks are current.

## Operational Readiness Checklist

Safety:

- Fixture mode remains default.
- Real mode requires explicit `--collection-mode real`.
- `--require-tools` is used in release and live verification gates.
- Live targets are allowlisted by environment, account, namespace, and run ID.
- Scenario seeds and cleanup hooks are reviewed before promotion.

Reliability:

- Live runs are idempotent where possible.
- Cleanup runs on normal completion, blocking result, timeout, and interrupt.
- Teardown verification catches leaked clusters, Compose projects, volumes, ports, and temporary files.
- Operator-run live checks have documented retry and recovery behavior.

Security:

- No production credentials are committed or required for fixture mode.
- Live credentials are scoped to sandbox or approved staging resources.
- Evidence outputs are redacted before persistence.
- Input allowlists cover every command-rendered variable.
- Generated artifacts have retention and access controls.

Observability:

- Runs emit structured phase timings and failure categories.
- Adapter execution records timeout, non-zero exit, parser failure, and redaction events.
- Cleanup failures page or notify the owning team before resources age out.
- Metrics distinguish fixture, local real, staging, and approved production-adjacent runs.

Operations:

- Each release has an owner, changelog, release manifest, and rollback path.
- On-call docs include common failure modes and cleanup commands.
- Scenario deprecations include replacement guidance and minimum notice.
- Compatibility is tracked for supported Python, Docker, Kubernetes, Helm, and cloud provider versions.

## Risk Register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Live scenario leaks infrastructure | Cost, port conflicts, noisy test hosts | Run-scoped names, teardown verification, cleanup runbook, stale resource sweeper |
| Fixture and real behavior diverge | False confidence in agent evaluation | Representative live matrix, adapter parity tests, scenario catalog live-readiness status |
| Unsafe evidence command input | Command injection or data exposure | Input allowlists, unresolved-template checks, preview mode, parser contract tests |
| Secrets in fixtures or logs | Credential exposure | Hygiene scanner, redaction, fake-secret allowlist, retention controls |
| Cloud staging over-permissioned | Excess blast radius | Sandbox-only IAM, budget alerts, region/account allowlist, destroy-first recovery docs |
| Production use before gates pass | Operational incident | Environment allowlist, approval workflow, disabled-by-default live production policy |

## Implemented Near-Term Backlog

The first near-term roadmap slice is implemented:

1. Strict scenario and `expect.yaml` validation.
2. CI release gate for validation, fixture smoke, docs link checks, fixture hygiene, tests, and package build.
3. Scenario catalog report with domain, archetype, evidence adapter, variants, and live-readiness.
4. Teardown verification for kind and linux-vm live runs.
5. Docs link checking and fixture hygiene scanning.
6. Mocked `eks-staging` blocked-dispatch tests before real Terraform execution.

## Next Backlog

1. Add SBOM generation and dependency vulnerability scanning.
2. Implement mocked Terraform planning boundaries for `eks-staging` before adding live AWS execution.
3. Add signed artifact generation once the internal release destination is chosen.
4. Add release artifact retention and access-control documentation.
