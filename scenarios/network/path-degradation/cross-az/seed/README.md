# Network Path Degradation Scenario Seed

Seed checkout and upstream pods with labels matching `inject.yaml`. The symptom
predicate should wait until Prometheus and network probes observe sustained
packet loss.
