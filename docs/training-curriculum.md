# Training Curriculum

`harness/training-curriculum-order.yaml` orders the reviewed alpha drill bundles by difficulty and domain.

Run:

```bash
python3 -m incident_generator training-curriculum --json
```

The curriculum uses schema `incident-generator.training-curriculum/v1` and covers all 11 checked golden response seeds exactly once:

- Beginner: Linux disk byte and inode capacity, Kubernetes insufficient CPU, network high-latency path, and DNS NXDOMAIN drills.
- Intermediate: Kubernetes PVC-unbound scheduling, checkout deploy-correlated 5xx, database pool exhaustion, and Linux OOM kill drills.
- Advanced: prompt-injection evidence discipline and low-signal unknown/abstention drills.

Each entry includes the golden seed id, domain, difficulty, global order, scenario ids, learning objective, prerequisite seeds, and paired negative examples. `release-manifest` publishes the same ordering under `benchmark_release.training_curriculum`, and `skill-drill-export` writes a portable `curriculum.json` next to `manifest.json`.
