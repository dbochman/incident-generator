# Benchmark Release Manifest

`python3 -m incident_generator release-manifest --json` now emits benchmark provenance in addition to package and artifact hashes. The benchmark section is `benchmark_release` with schema version `incident-generator.benchmark-release/v1`.

Use it when cutting or comparing benchmark releases:

```sh
python3 -m incident_generator release-manifest \
  --artifact-dir dist \
  --output dist/release-manifest.json \
  --json
```

The manifest records:

- `scenario_hashes`: one sha256 tree hash per scenario package, with path, domain, archetype, and live-readiness state.
- `benchmark_sets`: stable set ids, modes, item counts, fixed seeds when present, host profiles, source paths, and source hashes for checked benchmark definitions.
- `benchmark_set_aliases`: stable alpha aliases from `harness/alpha-benchmark-sets.yaml`, including grouped benchmark set ids, item counts, fixed seeds, supported host profiles, source hashes, and compatibility guarantees.
- `training_seed_library`: golden response seed ids from `harness/golden-response-seeds.yaml`, with benchmark alias and set refs, source hashes, learner-visible evidence refs, expected hypotheses, validation commands, and response text hashes.
- `incorrect_response_library`: labeled training-negative example ids from `harness/incorrect-response-seeds.yaml`, with paired golden seed ids, failure modes, source hashes, learner-visible evidence refs, expected failure checks, validation commands, and response/correction text hashes.
- `training_drill_export`: the portable skill drill export command, source refs, bundle file list, 11 reviewed bundles, six linked incorrect-response examples, and validation commands.
- `training_curriculum`: beginner/intermediate/advanced ordering from `harness/training-curriculum-order.yaml`, with domain grouping, prerequisites, paired negatives, learning objectives, and source hashes.
- `judge_packs`: checked deterministic, Tier 2 LLM, and mixed judge-pack selections plus the source manifest hash.
- `supported_host_profiles`: local and Docker-over-SSH resource ceilings for `linux-vm/local`, `kind/local`, and `kind/warm-batch`.
- `runtime_assumptions`: required real-mode tools, fixture-mode Docker independence, kind cluster shape, Linux VM Compose limits, observability limits, add-on limits, and timeout defaults.
- `known_limitations`: current benchmark boundaries, including blocked `eks-staging`, operator-run live matrix execution, fixture-only cross-archetype combinations, live LLM execution credential requirements, and fail-closed Tier 2/mixed judge packs until live judge execution exists.

Scenario hashes cover every file under each scenario directory. Source hashes cover checked benchmark definitions such as `harness/alpha-benchmark-sets.yaml`, `harness/golden-response-seeds.yaml`, `harness/incorrect-response-seeds.yaml`, `harness/training-curriculum-order.yaml`, `harness/random-pair-fixture-preview.yaml`, `harness/triple-benchmark-fixture-preview.yaml`, noisy/adversarial/evidence-discipline/conflicting-signal fixture plans, confidence calibration reports, temporal and recovery benchmark plans, deterministic replay summary examples, fixture/live LLM smoke summaries, selected adapter benchmark-set manifests, judge-pack manifests, and selected fixture inventories. Artifact hashes remain under the top-level `artifacts` section.

For retained live runs, pair this manifest with the artifact registry. The manifest identifies the release inputs and supported host envelope; the registry records run-specific host fingerprints, commands, retained files, pass/fail state, and failure classes.

The alpha aliases are documented in [alpha-benchmark-sets.md](alpha-benchmark-sets.md). They are compatibility promises for `alpha-2026-05-06`: do not change alias membership in place after publication; add a new alias version for broader or changed coverage. Live rerun comparison is documented in [live-run-reproducibility.md](live-run-reproducibility.md). Golden response seeds are documented in [golden-response-seeds.md](golden-response-seeds.md), incorrect response seeds are documented in [incorrect-response-seeds.md](incorrect-response-seeds.md), curriculum ordering is documented in [training-curriculum.md](training-curriculum.md), and portable bundle generation is documented in [skill-drill-export.md](skill-drill-export.md). Both seed libraries should move forward by adding new ids or new release aliases, not by silently changing reviewed training examples.

For Docker-free CI checks, `python3 -m incident_generator benchmark-sets --json` emits the benchmark set and alias portion directly with schema `incident-generator.benchmark-set-listing/v1`. The standalone `make fixture-benchmark-gate` target combines scenario validation, catalog listing, and benchmark-set listing without starting live infrastructure.
