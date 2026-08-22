# R20 Task Audit

Confirmatory population computed programmatically:
`held_out_memory_eligible (308) − R19_small_60 (60) = 248` untouched tasks
(`artifacts/r20/task_manifest.json`, sha256 `bb401907…`).

- Every task is an official SWE-bench Verified instance, untouched by R1–R19.
- Existing memory-eligibility rule unchanged (≥1 earlier same-repo source).
- No difficulty filter, no repository filter, no outcome-based exclusion.
- Repository-clustered analysis (multiple tasks per repo).
- The R19 60 ids are excluded (DEVELOPMENT_OBSERVED); `ci-r20-freeze` asserts overlap = 0.
