# Edge Gateway Baseline Mapping

The exported benchmark package includes a `kind/ecommerce-lite/edge-gateway` profile for DNS, TLS, and certificate scenarios.

The ecommerce-lite chart renders `edge-gateway-profile.yaml` with hostnames, edge and gateway services, DNS retry settings, normal TLS handshakes, certificate probes, gateway request mix, and unrelated low-rate edge errors. The five edge scenarios also carry `workload_profile` and `incident_injection` metadata so replay and noisy fixture renderers can distinguish causal DNS/TLS evidence from ambient edge noise.

The causal live mechanisms remain the existing harnesses: `harness/tls-target`, `harness/dns-probe`, and `harness/coredns-overrides`.
