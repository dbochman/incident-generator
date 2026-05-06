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
- `supported_host_profiles`: local and Docker-over-SSH resource ceilings for `linux-vm/local`, `kind/local`, and `kind/warm-batch`.
- `runtime_assumptions`: required real-mode tools, fixture-mode Docker independence, kind cluster shape, Linux VM Compose limits, observability limits, add-on limits, and timeout defaults.
- `known_limitations`: current benchmark boundaries, including blocked `eks-staging`, operator-run live matrix execution, fixture-only cross-archetype combinations, blocked live LLM execution without credentials, and the lack of a direct result-schema emitting runner command.

Scenario hashes cover every file under each scenario directory. Source hashes cover checked benchmark definitions such as `harness/random-pair-fixture-preview.yaml`, `harness/triple-benchmark-fixture-preview.yaml`, noisy/adversarial/evidence-discipline/conflicting-signal fixture plans, temporal and recovery benchmark plans, and selected fixture inventories. Artifact hashes remain under the top-level `artifacts` section.

For retained live runs, pair this manifest with the artifact registry. The manifest identifies the release inputs and supported host envelope; the registry records run-specific host fingerprints, commands, retained files, pass/fail state, and failure classes.
