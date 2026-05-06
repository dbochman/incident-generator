# Cascading Temporal Incident Model

`harness/cascading-temporal-incident-model.yaml` defines the first temporal benchmark model. It represents ordered phases, delayed symptoms, changing expected hypotheses, and forward causal links for a checkout deploy regression that propagates into database backpressure and latency.

Render the standalone report:

```sh
python3 -m incident_generator temporal-model --json
```

The report validates phase order, unique phase ids, selected scenario ids, expected-hypothesis add/remove transitions, delayed symptom timing, and causal links that point forward in time. It is a fixture-mode authoring contract and does not start Docker, `kind`, or the Linux VM harness.
