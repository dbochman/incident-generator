# Alpha Benchmark Sets

`harness/alpha-benchmark-sets.yaml` publishes stable alpha aliases for dated benchmark set ids. `python3 -m incident_generator release-manifest --json` includes them at `benchmark_release.benchmark_set_aliases`, and `python3 -m incident_generator benchmark-sets --json` lists the benchmark sets and aliases without Docker.

| Alias | Items | Fixed seed | Host profiles |
| --- | ---: | --- | --- |
| `alpha-individual` | 41 scenarios | none | `linux-vm/local`, `kind/local` |
| `alpha-curated-combos` | 27 pairs | none | `linux-vm/local`, `kind/warm-batch`, `docker-over-ssh` |
| `alpha-random-kind-8` | 8 pairs | `20260506` | `kind/warm-batch`, `docker-over-ssh` |
| `alpha-random-kind-16` | 16 pairs | `20260506` | `kind/warm-batch`, `docker-over-ssh` |
| `alpha-agent-comparison` | 10 result cases | `20260506` | fixture-safe or recorded snapshots |
| `robustness-prompt-injection` | 6 robustness cases | `20260506` | fixture-safe |
| `robustness-evidence-discipline` | 17 robustness cases | `20260506` | fixture-safe plus recorded live snapshots |

Compatibility is source-hash based: aliases keep fixed membership for `alpha-2026-05-06`, and later benchmark additions should publish new aliases instead of changing these rows in place. Warm-kind aliases require serial execution on the supported `kind/warm-batch` host profile; fixture-only aliases do not require Docker or provider credentials. Live reruns should follow [live-run-reproducibility.md](live-run-reproducibility.md), where timings may drift but release hashes, generated counts, teardown state, and replay outcomes must remain comparable.

Run `make fixture-benchmark-gate` in the standalone package to execute the CI-safe gate: scenario validation, catalog listing, and benchmark-set listing. The gate is fixture-only and must not start Docker, kind, or live providers.
