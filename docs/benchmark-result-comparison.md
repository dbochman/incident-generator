# Benchmark Result Comparison

`python3 -m incident_generator result-comparison` renders a deterministic Markdown view from one or more `incident-generator.benchmark-result/v1` payloads.

By default, the command builds the checked local inputs without live providers:

- deterministic validated-combo replay from `harness/deterministic-replay-summary-example.json`;
- fixture and recorded live LLM smoke results from `harness/benchmark-combo-llm-smoke-fixture-summary.json` and `harness/benchmark-combo-llm-smoke-live-summary.json`;
- noisy live artifact replay from `benchmark-artifacts/registry.json` and the retained `20260506-noisy-live-checkout-canary-5xx` run;
- external adapter smoke results from `harness/agent-adapter-benchmark-set.yaml` with `deterministic-local` judging.

```sh
python3 -m incident_generator result-comparison \
  --created-at 2026-05-06T00:00:00Z \
  --output docs/benchmark-result-comparison.md
```

Pass explicit payloads with repeated `--result` when comparing retained runs:

```sh
python3 -m incident_generator result-comparison \
  --result benchmark-artifacts/deterministic/result.json \
  --result benchmark-artifacts/live-llm/result.json \
  --result benchmark-artifacts/external-agent/result.json
```

The entrant table compares result count, pass rate, hypothesis preservation, required abstention quality, required uncertainty quality, false-attribution guards, judge execution and pass state, latency, and artifact links. Use `--check-output` in release gates to fail on Markdown drift.
