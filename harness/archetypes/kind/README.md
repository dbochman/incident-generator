# kind Archetype

This archetype is a runnable local real-environment target. It creates a
three-node kind cluster, writes an isolated kubeconfig under `.tmp/`, and
delegates observability installation to `harness/observability/install.sh`.

The fixture-backed scenario mode remains the default for deterministic tests.
Live kind execution should run through the standalone runner:

```sh
python3 -m incident_generator doctor
python3 -m incident_generator run \
  --scenario scenarios/kubernetes/pending-pod/unschedulable \
  --collection-mode real \
  --require-tools
```

The runner sets `SRE_AGENT_KIND_KUBECONFIG`, starts provider port-forwards where
needed, waits for the scenario predicates in `expect.yaml`, and calls teardown
when the run exits. Use `--hold` only for manual inspection.
