# kind Archetype

This archetype is the first Phase A real-environment target. It creates a
three-node kind cluster, writes an isolated kubeconfig under `.tmp/`, and
delegates observability installation to `harness/observability/install.sh`.

The fixture-backed scenario mode remains the default for deterministic tests.
Live kind execution should run through `tools/run_scenario.py` once real
archetype dispatch lands.
