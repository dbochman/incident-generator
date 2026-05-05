# Skills

Skill YAML files define incident-specific evidence requests, hypotheses, actions, output requirements, and safety policy. All current skills are fixture-backed and pass the eval suite in prompt mode.

## Catalog

Kubernetes:

- [crashloopbackoff.yaml](kubernetes/crashloopbackoff.yaml)
- [pending-pod.yaml](kubernetes/pending-pod.yaml)
- [node-pressure.yaml](kubernetes/node-pressure.yaml)

Linux:

- [disk-full.yaml](linux/disk-full.yaml)
- [cpu-saturation.yaml](linux/cpu-saturation.yaml)
- [memory-oom.yaml](linux/memory-oom.yaml)

Service:

- [http-5xx-spike.yaml](service/http-5xx-spike.yaml)
- [latency-spike.yaml](service/latency-spike.yaml)
- [dns-tls-failure.yaml](service/dns-tls-failure.yaml)
- [certificate-rotation-readiness.yaml](service/certificate-rotation-readiness.yaml)
- [queue-backlog-consumer-lag.yaml](service/queue-backlog-consumer-lag.yaml)
- [kafka-rebalance.yaml](service/kafka-rebalance.yaml)
- [deployment-rollback-decision.yaml](service/deployment-rollback-decision.yaml)

Database:

- [connection-exhaustion.yaml](database/connection-exhaustion.yaml)

Network:

- [path-degradation.yaml](network/path-degradation.yaml)

## Run A Skill

```sh
make disk-brief
python3 tools/run_skill.py --skill skills/linux/disk-full.yaml --fixture evals/linux-disk-fixtures/linux-disk-capacity --mode prompt --pretty
```

Run all skill evals through the main gate:

```sh
make validate
make eval
```

## Authoring Notes

- Keep inspection evidence read-only.
- Put state-changing options in `actions`, not `inspect.commands`.
- Include explicit `unsafe_actions_avoided` expectations in fixtures.
- Add or update the rubric under `evals/rubrics/` for every eval-pass skill.
- Use `tools/scaffold_skill.py --require-live` only as an authoring-time helper; generated artifacts still need human review and the normal eval gates.
