# R22 §2 — SWE-ContextBench public-data audit (no model calls)

## Pin + license
- HF dataset: `jiayuanz3/SWEContextBench` (public, gated=false) — **license: MIT**.
- GitHub eval repo: `jiayuanz3/SWEContextBench @ 31bb04155f52b184bf31b220e3cff0607ac9c953` — **NO LICENSE file**
  → the evaluation code is **not** vendored, copied, or modified (§2). Only the MIT dataset is used, with a
  clean-room adapter (`experiments/r22/benchmark_adapter.py`) that delegates grading to the official SWE-bench
  harness.
- Downloaded parquet sha256 (frozen in `artifacts/r22/benchmark_lock.json`):
  - `SWEContextBench_Experience.parquet` `384aa652…dfa7b9`
  - `SWEContextBench_Related.parquet` `890aaf0f…eca2ad`
  - `SWEContextBench_Relationship.parquet` `4bcbe816…43ce93`

## Row / structure audit
| Table | Rows | Notes |
| --- | ---: | --- |
| Experience (base / prior-experience pool) | 1,100 | standard SWE-bench columns |
| Related (target tasks) | 376 | same columns |
| Relationship (source↔target links) | 376 | `experience_instance_id` ↔ `related_instance_id` + PR/issue URLs |

- Built on SWE-Bench Lite + Multilingual + Verified; dataset card claims **51 repositories, 9 languages**.
- **Unique repository strings across base∪related: 57** (audit count; the 51 vs 57 gap is recorded as a
  discrepancy — likely repo-name variants; not resolved by renaming, reported as-is).
- **Duplicate base instance_ids: 93**; duplicate related instance_ids: 19 — recorded (deduped downstream by id).
- Field completeness (missing counts) recorded per column in `benchmark_lock.json` for `base_commit`,
  `environment_setup_commit` (Docker-image proxy), `FAIL_TO_PASS`, `PASS_TO_PASS`, `patch`, `test_patch`,
  `problem_statement`, `created_at`.

## Prohibitions honored
No target patch in any prompt; no target test patch in memory; no FAIL_TO_PASS/PASS_TO_PASS names to the model; no
gold context to the model; source and target never used as the same task. Grading is delegated to the official
SWE-bench grader; this repo never reimplements grading.

## Artifacts
`artifacts/r22/benchmark_lock.json`, `source_target_relationships.json`, `leakage_audit.json`.
