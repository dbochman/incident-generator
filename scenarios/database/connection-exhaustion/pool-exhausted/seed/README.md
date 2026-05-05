# Database Connection Exhaustion Scenario Seed

Seed a checkout workload with 30 held sessions against a 31-connection Postgres
target and a higher configured client count. The symptom predicate waits for
the live backend floor, while `database.pool_status` derives non-zero waiters
from the configured demand above observed active sessions.
