# Database Connection Exhaustion Scenario Seed

Seed a checkout workload with too many concurrent connections for the configured
pool limit. The symptom predicate should wait for pool utilization above 95%
with non-zero waiters.
