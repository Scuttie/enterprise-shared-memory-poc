# R23-B0 — Benchmark / grader / scaffold audit (three distinct pinned objects)

## Benchmark — SWE-bench Verified (`artifacts/r23/benchmark_lock.json`)
| field | value |
|---|---|
| dataset | `SWE-bench/SWE-bench_Verified` |
| revision sha | `78f471bf655a3137b2e8a75af1501690ec009ec3` (same enriched revision R22 pinned; re-verified independently) |
| split / rows | test / **500** (500 unique instance_ids) |
| parquet | `data/test-00000-of-00001.parquet`, sha256 `030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25` |
| schema | base_commit, created_at, difficulty, environment_setup_commit, eval_type, **image**, instance_id, log_parser, repo, version, patch, test_patch, eval_script, problem_statement, hints_text, FAIL_TO_PASS, PASS_TO_PASS |

Per-instance gold/test/F2P/P2P sha256 + image name recorded for all 500 (`per_instance_hash_index`). The enriched
rows carry the `image`/`eval_script`/`log_parser`/`eval_type` fields the swebench harness needs (as R22 established).

## Grader — swebench harness (`artifacts/r23/grader_lock.json`)
`swebench==5.0.2` (PyPI, **MIT**), `python -m swebench.harness.run_evaluation --dataset_name SWE-bench/SWE-bench_Verified
--instance_ids <id> --predictions_path <preds> --run_id <id>`. Prediction = `{instance_id, model_name_or_path,
model_patch}`; report = `resolved_ids/unresolved_ids` + per-instance `{resolved, tests_status, patch_applied}`. This
is the mainline swebench harness (NOT the `swebench_memory` fork used for SWE-ContextBench in R22). Re-verify before
paid.

## Agent scaffold — Mini-SWE-Agent (`artifacts/r23/agent_scaffold_lock.json`)
`github.com/SWE-agent/mini-swe-agent` @ `25941c89cfbc91eb40b3f8756348c91d9977d57e` (main, **MIT**). System-prompt /
tool-schema / patch-parser / step-cap / timeout hashes are pinned when the repo is cloned at this commit in R23-R0.

**The benchmark revision, harness version, and scaffold commit are three separate pinned objects** and are not
assumed equal.
