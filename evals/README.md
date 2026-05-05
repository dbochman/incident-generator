# Evaluations

The eval tree contains fixture evidence, expected outputs, rubrics, and integration fixtures for the agent prototype. The default suite is deterministic and credential-free.

## Main Gate

```sh
make eval
```

`make eval` currently runs:

- skill validation against `skills/**/*.yaml`;
- the full unittest suite;
- the manifest-backed skill eval suite;
- composed incident correlation checks;
- recovery-plan dry-run/execution checks and generated-doc drift checks;
- code-change dry-run, replay export, and contract checks;
- fast-path action CLI checks;
- real-evidence CLI fixture checks and provider coverage;
- fixture-backed LLM smoke docs;
- adversarial fixture inventory and adversarial LLM smoke docs;
- fixture-backed supervisor and Cursor bridge sandbox smoke docs.

## Layout

- [manifest.yaml](manifest.yaml): skill eval manifest and latency budgets.
- [rubrics/](rubrics/): Tier 1 deterministic and Tier 2 judge rubric definitions.
- [fixtures/](fixtures/): Kubernetes CrashLoopBackOff fixtures.
- [pending-fixtures/](pending-fixtures/): Kubernetes Pending Pod fixtures, including prompt-injection coverage.
- [node-pressure-fixtures/](node-pressure-fixtures/): Kubernetes node-pressure fixtures.
- [linux-disk-fixtures/](linux-disk-fixtures/), [linux-cpu-fixtures/](linux-cpu-fixtures/), [linux-memory-fixtures/](linux-memory-fixtures/): Linux host fixtures.
- [http-5xx-fixtures/](http-5xx-fixtures/), [latency-fixtures/](latency-fixtures/), [dns-tls-fixtures/](dns-tls-fixtures/), [certificate-rotation-fixtures/](certificate-rotation-fixtures/): service-edge fixtures.
- [queue-backlog-fixtures/](queue-backlog-fixtures/) and [kafka-rebalance-fixtures/](kafka-rebalance-fixtures/): async processing fixtures.
- [deployment-rollback-fixtures/](deployment-rollback-fixtures/), [db-connection-fixtures/](db-connection-fixtures/), [network-path-fixtures/](network-path-fixtures/): rollback, database, and network fixtures.
- [composed-incident-fixtures/](composed-incident-fixtures/): multi-skill incident composition cases.
- [recovery-plan-fixtures/](recovery-plan-fixtures/): Class 3 recovery-plan validation, dry-run, execution, audit, and precondition cases.
- [code-change-fixtures/](code-change-fixtures/): code-change dry-run, handoff, replay, CI, merge readiness, rollback, and approval surface cases.
- [fast-path-cli-fixtures/](fast-path-cli-fixtures/): Class 0-2 fast-path action CLI cases.
- [real-evidence-cli-fixtures/](real-evidence-cli-fixtures/): real-provider command preview/execution parser fixtures.
- [llm-smoke-fixtures/](llm-smoke-fixtures/): fixture-backed model and judge responses.
- [cursor-bridge-smoke-fixtures/](cursor-bridge-smoke-fixtures/): fixture-backed Cursor bridge smoke contract.
- [hands-off-control-fixtures/](hands-off-control-fixtures/): kill-switch and circuit-breaker inputs.
- [root-cause-synthesis-fixtures/](root-cause-synthesis-fixtures/): cross-skill synthesis cases.

## Live Checks

Live checks are operator-run only. They require credentials, explicit live flags, and are intentionally absent from the default eval gate.

```sh
make configure-llm-env
. /tmp/sre-agent-llm.env
make linux-disk-llm-smoke-live-tier2
make adversarial-llm-smoke-live-tier2
make supervisor-approval-smoke-live

make configure-cursor-env
. /tmp/sre-agent-cursor.env
make cursor-bridge-sandbox-smoke-live
```

## Fixture Hygiene

- Use realistic but scrubbed command output.
- Keep hostile prompt-injection text inside fixture evidence only; expected outputs should assert forbidden tokens stay absent.
- Do not include credentials, customer data, production hostnames, raw request payloads, or personal data.
- Add regression coverage for both competence and restraint when introducing a new fixture.
