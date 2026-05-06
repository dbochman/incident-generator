# Recovery After Diagnosis Benchmark

`recovery-benchmark` renders the checked fixture-mode benchmark for the
post-diagnosis handoff into safe recovery planning.

```sh
python3 -m incident_generator recovery-benchmark --json
```

The benchmark starts after diagnosis, preserves initial scenario action
abstention, and checks that Class 3 recovery actions remain dry-run-only with
domain supervisor, generalist supervisor, and human-confirmation gates. The
checked cases cover a shell rollback preview and a code-change draft-PR preview,
both with required evidence references and state preservation.
