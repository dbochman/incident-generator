# Noisy Partial-Failure Pack

`harness/noisy-partial-failure-pack.yaml` defines fixture-mode variants for partial seed success, missing symptom wait evidence, degraded-but-not-down symptoms, and unrelated red-herring noise.

Render the package report with:

```sh
python3 -m incident_generator noisy-partial-failures --json
```

The report validates expected hypotheses, forbidden false-attribution guards, internal `ambient` and `red_herring` role coverage, and hidden source/role metadata.
