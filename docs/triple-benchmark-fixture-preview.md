# Triple Benchmark Fixture Preview

`harness/triple-benchmark-fixture-preview.yaml` defines a fixed-seed fixture-mode triple preview for benchmark planning before live startup.

Render the standalone report:

```sh
python3 -m incident_generator triple-preview --json
```

The report evaluates the configured nine-scenario pool, selects eight deterministic triples with `seed: 20260506`, and preserves each selected combination id, scenario ids, compatibility decision, relative scenario paths, expected hypothesis set, resource-claim summary, and target-state conflict count. It runs entirely in fixture mode, so it does not start Docker, `kind`, or the Linux VM harness.
