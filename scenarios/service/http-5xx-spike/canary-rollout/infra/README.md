# Service HTTP 5xx Scenario Infra

The deterministic path uses `http-5xx-deploy-correlated`. The live Phase A path
should deploy a checkout sample service to kind, expose a health endpoint, and
wire logs, SLO burn, deployment metadata, traces, and fake PagerDuty events into
the harness-local observability profile.
