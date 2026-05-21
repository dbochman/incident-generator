# Agent Adapter Contract

`schemas/incident-generator-agent-adapter.schema.json` defines the current v1 external-agent exchange for benchmark entrants that do not use this repo's internal eval commands. Checked examples are available at `harness/agent-adapter-contract-example.json`, `harness/agent-adapter-abstention-example.json`, and `harness/agent-adapter-mutation-gate-example.json`; `harness/agent-adapter-benchmark-set.yaml` groups those examples into a selected runner set.

V1 uses a redacted evidence bundle and remains the default compatibility path. The v2 contract shifts to a sandboxed investigation session where the agent starts from an alert and investigates through scoped tools or sandbox commands; the package runner supports this path for fixture-backed local subprocess adapters.

The exported v2 schema family is:

- `schemas/incident-generator-agent-investigation-session.schema.json`
- `schemas/incident-generator-agent-investigation-tool-request.schema.json`
- `schemas/incident-generator-agent-investigation-tool-result.schema.json`
- `schemas/incident-generator-agent-investigation-final-response.schema.json`
- `schemas/incident-generator-agent-investigation-transcript-event.schema.json`

Checked v2 examples are available at `harness/agent-adapter-investigation-session-example.json`, `harness/agent-adapter-investigation-tool-request-example.json`, `harness/agent-adapter-investigation-tool-result-example.json`, `harness/agent-adapter-investigation-final-response-example.json`, `harness/agent-adapter-investigation-transcript-event-example.json`, and `harness/agent-adapter-investigation-transcript-example.ndjson`.

The exchange has two envelopes:

| Section | Purpose |
| --- | --- |
| `request` | Runner-to-agent payload with benchmark id, case id, redacted evidence items, action policy, and required output sections. |
| `response` | Agent-to-runner payload with ranked hypotheses, evidence citations, next steps, proposed actions, abstention, uncertainty, unsafe actions avoided, artifacts, and latency. |

## Request Contract

These rules apply to v1 requests.

Requests use `schema_version: incident-generator.agent-adapter-request/v1` and `input_mode: redacted_evidence_bundle`. They intentionally hide internal scoring labels and expected answers:

- `internal_evidence_roles_visible: false`
- `expected_hypotheses_visible: false`
- `forbidden_hypotheses_visible: false`
- `redaction_required: true`

Evidence items expose stable `evidence_id` values that the response must cite, but they do not expose internal roles such as `causal`, `ambient`, `red_herring`, or `hostile`.

## V2 Investigation Sessions

The v2 input mode is `sandboxed_investigation_session`. Instead of `evidence_items`, the session-start payload contains:

- request, session, benchmark set, and case ids;
- initial alert with timestamp, service, symptom, severity, and redacted labels;
- target scope visible to the agent;
- tool catalog with stable typed inspection ids, `sandbox.exec` availability, provider names, required argument schemas, sensitivity flags, output contracts, and safe command previews when allowed;
- skill exposure metadata with treatment id, exposure mode, visible skill ids, router metadata, and skill hashes;
- investigation policy with max steps, max duration, output limits, allowed providers, denied providers, and sensitive-tool handling;
- action policy and visibility flags.

The session start must not contain expected hypotheses, forbidden hypotheses, internal evidence roles, hidden rubric fields, raw provider output, or preassembled evidence items.

Skill exposure is an explicit v2 treatment. Supported modes should be `none`, `catalog_index`, `routed_procedure`, `routed_full`, and `full_catalog`. The default skill-assisted treatment is `routed_procedure`; `none` remains the explicit no-skill baseline, and `routed_full` is opt-in for hypothesis-bearing skill packs. Skill packs may expose generic skill knowledge from `skills/**/*.yaml`, including inspection workflow, evidence requests, safety policy, and, in `routed_full`, generic hypothesis catalogs. They must not expose scenario expected hypotheses, forbidden hypotheses, evidence roles, fixture answers, hidden rubric fields, or tool results. Runner artifacts should retain `skill_exposure.mode`, visible skill ids, skill hashes, and `skill-pack.json` when skills are visible so comparison reports can measure whether skills improve investigation quality.

The first v2 transport should be line-oriented JSON over stdin/stdout:

1. The runner sends `session_start`.
2. The agent sends `tool_request` messages for advertised typed tools or `sandbox.exec`.
3. The runner validates and executes or replays each tool.
4. The runner sends `tool_result` messages with redacted summaries, provenance, artifact refs, and stable `evidence_id` values.
5. The agent sends one `final_response` that cites discovered evidence ids.
6. The runner validates, scores, and retains `investigation-transcript.ndjson`.

The first implementation should expose both provider-contract tools and `sandbox.exec`. Free-form commands must run inside a disposable scenario container, namespace, or fixture command emulator, not on the benchmark runner host. Bad commands, typos, timeouts, empty results, and false leads should be retained as valid transcript events. Sandbox-local mutations may be allowed only when the scenario can absorb and score them; host and real-provider mutations remain proposed actions behind policy gates.

Implementation defaults: use `stdio-jsonl`, use `routed_procedure` as the default skill-assisted exposure, use `none` for the paired no-skill baseline, include `sandbox.exec` in schemas and fixture examples, route fixture `sandbox.exec` through a command emulator, block sandbox-local mutations until mutation-scored scenarios exist, and never run `sandbox.exec` on the benchmark runner host or an unscoped real-provider context. Internal agent investigation mode and real read-only provider execution are later work.

## Response Contract

Responses use `schema_version: incident-generator.agent-adapter-response/v1`. Every response includes ranked hypotheses, top-level evidence citations, recommended next steps, proposed actions, abstention, uncertainty, unsafe actions avoided, latency, and retained artifact refs.

The action policy caps proposed actions at Class 3. Destructive Class 4 actions are outside the adapter contract.

Runner implementations should map validated responses into `incident-generator.benchmark-result/v1` documents for comparison by pass rate, hypothesis preservation, evidence discipline, abstention, uncertainty, mutation-gated action safety, and latency.

## Runner Command

`benchmark-runner` is the fixture-safe first runner command. In the default v1 mode, without `--adapter-command`, it replays `harness/agent-adapter-contract-example.json`. With `--adapter-command`, it sends the redacted request JSON to the command's stdin and expects an adapter response JSON object on stdout.

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

For a fixture-safe CrisisMode compatibility smoke run, keep the shim in this package and point
`--adapter-command` at the local adapter command:

```sh
python3 -m incident_generator benchmark-runner \
  --benchmark-set harness/agent-adapter-benchmark-set.yaml \
  --adapter-command "python3 -m incident_generator crisismode-adapter" \
  --judge-pack deterministic-local \
  --json
```

For the broader checked CrisisMode compatibility report, use:

```sh
python3 -m incident_generator crisismode-compatibility --json
```

That report runs `harness/crisismode-compatibility-benchmark-set.yaml`, validates the generated
adapter responses against the local response contract surface, and summarizes coverage across
the built-in CrisisMode recovery families covered by the checked set: PostgreSQL replication,
PostgreSQL connection exhaustion, Redis memory pressure, queue backlog, Kafka consumer lag,
etcd consensus instability, Ceph storage degradation, Flink checkpoint failure, deploy rollback,
config drift, Kubernetes crash-loop, AI provider failover, DB migration recovery, DNS, TLS,
disk, backup verification, AWS S3, AWS DynamoDB, AWS RDS, and ambiguous-evidence abstention
cases. Add `--crisismode-repo ../crisismode --strict` to discover the sibling CrisisMode
checkout's built-in agents and return nonzero if benchmark scoring, checked-schema validation,
plan-shape validation, or agent-family coverage fails. Add `--adapter-command ...` to score a
real CrisisMode adapter command through the same report; route metadata is read from local shim
fields or CrisisMode's real router metadata and normalized to the compatibility family names.
See [crisismode-support.md](crisismode-support.md) for the current progress summary, validation
commands, ownership boundary, and next integration work.

The set command emits one merged `incident-generator.benchmark-result/v1` payload, writes `result.json`, `summary.json`, `events.ndjson`, `trace.json`, and `trace.md`, and stores each redacted request, adapter response, and readable `transcript.md` under `cases/<case-id>/`. The trace files are the user-facing prompt/response view: they show the redacted evidence bundle sent to the agent, the agent's hypotheses and evidence citations, and the judge outcome/checks for each case. `--judge-pack deterministic-local` records executed deterministic judge outcomes. Tier 2 and mixed judge packs are listed by `judge-packs` and fail closed until live judge execution is implemented.

For v2 fixture investigations, add:

```sh
python3 -m incident_generator benchmark-runner \
  --benchmark-set harness/agent-adapter-benchmark-set.yaml \
  --input-mode investigation-session \
  --adapter-protocol stdio-jsonl \
  --adapter-command "python3 -m incident_generator crisismode-adapter --stdio-jsonl" \
  --skill-exposure routed-procedure \
  --artifact-dir benchmark-artifacts/external-agent-investigation-smoke \
  --json
```

The v2 runner writes one `session_start` JSON line to the adapter, accepts `tool_request` lines for advertised tools, returns fixture-backed `tool_result` lines, and scores the final response against evidence ids discovered during the session. Add `--execute-real-provider-tools --provider-profile <profile>` to execute advertised typed tools through read-only provider contracts instead of fixture replay. Real-provider sessions render commands from checked contracts with validated primitive args, execute without a shell, block sensitive tools unless `--allow-sensitive-tools` is set, and record return code, timeout, parser status, redaction status, and provider provenance in retained tool results. `sandbox.exec` does not run on the benchmark runner host. Per-case artifacts include `session-start.json`, `investigation-transcript.ndjson`, `tool-results/<tool-call-id>.json`, `response.json`, and `transcript.md`.
