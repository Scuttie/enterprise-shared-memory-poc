# R20 — R19 Freeze Audit

Before any R20 model call, R19 (including R19-SMALL) is permanently frozen. R20 is a NEW experiment ID and uses
ONLY tasks untouched by R1–R19. The R19 60-task set is DEVELOPMENT_OBSERVED for R20 — used for power planning and
implementation verification, NEVER in the R20 primary confirmatory inference.

## Locked artifacts (newline-normalized sha256 — `artifacts/r20/r19_lock.json`)
Frozen: `docs/P6_UTILITY_ROUTER_PREREG.md`, `artifacts/p6/task_manifest.json`, `router_policy.json`,
`governance_thresholds.json`, `reports/R19_SMALL_RESULT.md`, `configs/p6/r19_small_targets.json`,
`prompt_manifest.json`, `analysis_manifest.json`, `source_bank_manifest.json`, the five R19 arm injection files
(memory_A1..A5), `scripts/r19_build_arms.py`, `r19_analysis.py`, `r14_swebench_agent.py`.

- R19-SMALL 60 target ids hash: `275e381e…`
- lock content_hash: `9acbaa51…`

`ci-r20-freeze` re-verifies these hashes; any mutation of an R19/R1–R18 artifact is a hard stop (§19).

## R20 non-interference guarantees
- R20 writes only under `artifacts/r20/`, `configs/r20/`, `docs/R20_*`, `reports/R20_*`, `scripts/r20_*`,
  new arm outputs under `artifacts/r20/arms_out/`.
- The R19 60 ids are excluded from the R20 confirmatory population by construction (computed in R20-2).
- No R19 result is reinterpreted; R20 reports its own six labels.
