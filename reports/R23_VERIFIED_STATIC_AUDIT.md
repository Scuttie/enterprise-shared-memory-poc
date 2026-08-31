# R23-B0 — Static audit of the 500-instance Verified universe

Credential-free (parquet only). `artifacts/r23/verified_static_audit.json` (per-instance),
`artifacts/r23/repository_alias_map.json`, `artifacts/r23/timestamp_cache.json`.

| item | value |
|---|---|
| rows | **500** (500 unique instance_ids) |
| repositories | **12** — django 231, sympy 75, sphinx 44, matplotlib 34, scikit-learn 32, astropy 22, + 6 more |
| language | python (all 500) |
| duplicate classes | DISTINCT 500 · EXACT_DUPLICATE_ROW 0 · SAME_INSTANCE_DIFF_VERSION 0 · REPOSITORY_ALIAS 0 · RELATION_DUPLICATE 0 |
| issue_created_at known | **500 / 500** |
| fix_pr_merge_at / fix_first_commit / issue_close known | **0 / 500** |

Per instance: repo, base_commit, environment_setup_commit, version, difficulty, issue_created_at, gold/test/F2P/P2P
sha256, FAIL_TO_PASS/PASS_TO_PASS counts, changed_paths, gold/test patch line counts, image name, eval_type,
log_parser. No task removed for sharing a repository.

## Honest timestamp gap (load-bearing for R23-X)
The enriched parquet contains **`created_at` (issue creation) only**; it has **no fix-PR-merge / fix-commit / issue-
close timestamps**. Per the spec these are marked **UNKNOWN** (no guessing from commit ordering; unknown timestamps
do not silently pass). Consequently the R23-X chronological eligibility graph confirms **0 edges** at B0 — the
source-availability side is unresolved. Resolving it needs a **batched unauthenticated GitHub-API fetch** of fix-PR
merge timestamps (credential-free, no secret), planned as R23-B0.1 before the R23-X pool is fixed. django's 231/500
dominance is recorded for repository clustering / design-effect.
