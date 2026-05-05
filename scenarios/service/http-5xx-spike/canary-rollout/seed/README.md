# Service HTTP 5xx Scenario Seed

Seed a canary deployment of `checkout-api` with a regression that returns 500s
for `/health` and emits structured exception logs tagged with
`deployment.version=2026.05.02-8`.
