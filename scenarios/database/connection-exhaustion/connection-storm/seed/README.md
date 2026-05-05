# database-connection-exhaustion connection-storm Seed

Seeds a search Postgres target with a bounded steady session floor for
Prometheus, then runs the pgbench harness in `churn` mode so
`database.pool_status` reports elevated `new_connections_per_sec` with zero
sustained waiters. The load generator pod is labelled `service=search-api` and
emits database connection-churn log lines for the `service.error_logs` adapter.
