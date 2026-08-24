# R22 §3 (G0) — mixed official-grader per-instance routing

The frozen 12-task smoke draws from three official SWE-bench subsets. Each instance is routed to **its own**
subset dataset (no single `--dataset_name` for all). No eval code is vendored; official images are built/pulled by
the harness. `artifacts/r22/grader_instance_routes.json`, `grader_image_manifest.json`.

## Routing result (all 12 routed, 0 unrouted)
| Subset | Count | Instances (language) |
| --- | ---: | --- |
| SWE-bench Verified | 1 | sympy (py) |
| SWE-bench Lite | 2 | astropy, seaborn (py) |
| SWE-bench Multilingual | 9 | caddy·prometheus (go), lucene·gson (java), rubocop (ruby), tokio·axum·ruff (rust), php-cs-fixer (php) |

Official datasets loaded (revisions frozen in the route manifest):
`princeton-nlp/SWE-bench_Verified` (500), `princeton-nlp/SWE-bench_Lite` (300),
`swe-bench/SWE-bench_Multilingual` (300).

## Execution design (`ci-r22-grader-smoke.yml`)
- **Sharded matrix**: 1 instance per job × {gold, no-patch} = 24 evaluations, `fail-fast:false`, resumable
  (per-`(instance,condition)` result JSON).
- **Docker preflight**: `docker info` + `df -h /`; `docker system prune` between conditions for disk hygiene.
- **Per-subset routing**: `scripts/r22_grader_run.py` invokes the official `swebench==5.0.2`
  `run_evaluation --dataset_name <subset> --instance_ids <iid>`.
- **Gate** (`--verify-sharded`): gold resolved 12/12, no-patch unresolved 12/12, completeness 24/24, infra
  failures 0, official tests modified 0.

## Honesty note
9 of 12 instances are **SWE-bench Multilingual** (go/java/ruby/rust/php). Grading these requires the Multilingual
per-language images + harness support and substantial disk/time on the runner. This is attempted on the
GitHub-hosted runner; if it cannot complete there, the exact per-task status is recorded and the endpoint is
`R22_MIXED_GRADER_TECHNICAL_BLOCK` — **not** narrowed to Verified-only (a Verified-only diagnostic, if run, uses a
different artifact name and does not satisfy the mixed gate).
