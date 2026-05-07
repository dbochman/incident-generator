# Agent Adapter Contract

`schemas/incident-generator-agent-adapter.schema.json` defines the external-agent exchange for benchmark entrants that do not use this repo's internal eval commands. Checked examples are available at `harness/agent-adapter-contract-example.json` and `harness/agent-adapter-abstention-example.json`; `harness/agent-adapter-benchmark-set.yaml` groups those examples into a selected runner set.

The exchange has two envelopes:

| Section | Purpose |
| --- | --- |
| `request` | Runner-to-agent payload with benchmark id, case id, redacted evidence items, action policy, and required output sections. |
| `response` | Agent-to-runner payload with ranked hypotheses, evidence citations, next steps, proposed actions, abstention, uncertainty, unsafe actions avoided, artifacts, and latency. |

## Request Contract

Requests use `schema_version: incident-generator.agent-adapter-request/v1` and `input_mode: redacted_evidence_bundle`. They intentionally hide internal scoring labels and expected answers:

- `internal_evidence_roles_visible: false`
- `expected_hypotheses_visible: false`
- `forbidden_hypotheses_visible: false`
- `redaction_required: true`

Evidence items expose stable `evidence_id` values that the response must cite, but they do not expose internal roles such as `causal`, `ambient`, `red_herring`, or `hostile`.

## Response Contract

Responses use `schema_version: incident-generator.agent-adapter-response/v1`. Every response includes ranked hypotheses, top-level evidence citations, recommended next steps, proposed actions, abstention, uncertainty, unsafe actions avoided, latency, and retained artifact refs.

The action policy caps proposed actions at Class 3. Destructive Class 4 actions are outside the adapter contract.

Runner implementations should map validated responses into `incident-generator.benchmark-result/v1` documents for comparison by pass rate, hypothesis preservation, evidence discipline, abstention, uncertainty, and latency.

## Runner Command

`benchmark-runner` is the fixture-safe first runner command. Without `--adapter-command`, it replays `harness/agent-adapter-contract-example.json`. With `--adapter-command`, it sends the redacted request JSON to the command's stdin and expects an adapter response JSON object on stdout.

Expectation flags are runner-only scoring data and are not added to the adapter request:

```sh
python3 -m incident_generator benchmark-runner \
  --expected-hypothesis "database connection pool exhaustion is causing checkout failures" \
  --forbidden-hypothesis dns_tls_failure \
  --evidence-role causal=2 \
  --json
```

For the checked selected set, use manifest-provided expectations and retain runner artifacts:

```sh
python3 -m incident_generator benchmark-runner \
  --benchmark-set harness/agent-adapter-benchmark-set.yaml \
  --judge-pack deterministic-local \
  --artifact-dir benchmark-artifacts/external-agent-adapter-smoke \
  --json
```

The set command emits one merged `incident-generator.benchmark-result/v1` payload, writes `result.json`, `summary.json`, `events.ndjson`, `trace.json`, and `trace.md`, and stores each redacted request, adapter response, and readable `transcript.md` under `cases/<case-id>/`. The trace files are the user-facing prompt/response view: they show the redacted evidence bundle sent to the agent, the agent's hypotheses and evidence citations, and the judge outcome/checks for each case. `--judge-pack deterministic-local` records executed deterministic judge outcomes. Tier 2 and mixed judge packs are listed by `judge-packs` and fail closed until live judge execution is implemented.
