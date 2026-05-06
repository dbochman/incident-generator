# Production Roadmap

This document describes the path from the current standalone incident generator to a production-ready internal service or release artifact. "Production" here means a supported, repeatable, observable tool for generating deterministic incident environments in approved harnesses and staging-like accounts. It does not mean fault injection against customer or business-production systems by default.

## Current Baseline

The repository currently has these production-relevant foundations:

| Area | Current state | Evidence |
| --- | --- | --- |
| Source governance | Package source is generated from the canonical `sre-incident-agent-skills` repository; standalone repo updates should come from `tools/export_incident_generator_package.py`, not hand edits. | `CANONICAL_SOURCE.md`, `make incident-generator-export-check` in the canonical repo |
| CLI runner | Supports `list`, `validate`, `run`, and `doctor`; `run` accepts repeated `--scenario`, explicit `--combination` sets, seeded archetype-scoped `--random-compatible-combinations`, and `--warm-kind` reuse for real-mode kind batches. | `incident_generator/cli.py` |
| Scenario catalog | 41 valid scenario packages across database, Kubernetes, Linux, network, and service domains. | `python3 -m incident_generator list --json` and `validate --json` |
| Combinatorial breadth | Current catalog supports 2,199,023,255,510 unordered fixture-mode combinations of two or more incidents, including 820 pairwise combinations. Real mode supports 2,147,483,665 same-archetype and shared-resource-safe combinations, including 516 pairwise combinations, across 32 `kind` and 9 `linux-vm` scenarios. Explicit and random batch flags default to real mode, with fixture mode available for previews; random batches can be constrained with `--random-archetype` and replayed with `--random-seed`. The full compatible `linux-vm` pair pool has passed live (`23/23`), and a curated cross-domain `kind` pair smoke has passed live (`4/4`). `--warm-kind` reduces kind batch setup time while preserving final cleanup verification. | Repeated `--scenario` runs, `--combination`, `--random-compatible-combinations`, `--warm-kind`, `stand_up_combinatorial_incident_environment`, `tests/test_cli.py`, `.tmp/incidents/20260505-linux-vm-pairs-safe/`, `.tmp/incidents/20260505-kind-curated-pairs/` |
| Deterministic mode | Fixture mode is default and does not start infrastructure. | `stand_up_incident_environment(... collection_mode=fixture ...)` |
| Local live harnesses | `kind` and `linux-vm` dispatch paths exist with preflight checks and teardown. | `incident_generator/scenarios.py`, `incident_generator/scenario_runtime.py` |
| Cloud fidelity | EKS Terraform skeleton exists, but runner dispatch is not implemented. | `harness/archetypes/eks-staging/`, `eks-staging` blocked result |
| Provider contracts | Evidence command contracts, provider profiles, endpoint rewriting, input allowlists, and parser fixtures exist. | `incident_generator/provider_contracts.py`, `evals/real-evidence-cli-fixtures/` |
| Contract hardening | Scenario validation checks schema-like field types, supported wait predicates, archetype/predicate compatibility, and required fixture outputs. | `incident_generator/scenarios.py`, `tests/test_cli.py` |
| Catalog reporting | Catalog report groups scenarios by domain, archetype, evidence adapter, and live-readiness state. | `python3 -m incident_generator catalog --json` |
| Hygiene gates | Markdown link checking and fixture secret/prompt-injection hygiene checks are implemented. | `incident_generator/checks.py`, `evals/fixture-hygiene-allowlist.yaml` |
| CI and release gate | CI runs a release gate for syntax, validation, catalog, fixture smoke, docs links, fixture hygiene, tests, package build, and release manifest generation. | `.github/workflows/ci.yml`, `make release-check` |
| Release manifest | Release manifest records package metadata, git SHA, scenario catalog hash, schema version, and artifact checksums. | `python3 -m incident_generator release-manifest --json` |
| Operator runbooks | Failed live cleanup and operator-run live smoke paths are documented. | `docs/runbooks/live-cleanup.md`, `harness/live-smoke.sh` |

Known gaps before production:

- The package is versioned as `0.1.0` and is not published.
- `eks-staging` runner dispatch and seed execution are explicitly blocked.
- Representative real-mode live matrix execution is not automated in CI.
- Real-mode combinatorial runs are intentionally constrained to one `environment_archetype` and non-overlapping, non-conflicting `resource_claims`; cross-archetype combinations are fixture-only until multi-harness orchestration is designed.
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

- Representative `kind` and `linux-vm` scenarios pass `--collection-mode real --require-tools` repeatedly on a clean host; the full compatible `linux-vm` pair pool has passed live (`23/23` on 2026-05-05), and the curated cross-domain `kind` pair smoke has passed live (`4/4` on 2026-05-05).
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
- Generate a release manifest with git SHA, package version, scenario catalog hash, schema version, and artifact checksums.
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
- A release manifest records package version, git SHA, scenario catalog hash, schema version, and artifact checksums.
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
