# R22 §1 — paid-preregistration consistency audit

Cross-checked: `reports/R22_PAID_EXECUTION_PLAN.md`, `configs/r22/paid_run_plan.json`,
`artifacts/r22/oracle_{smoke,dev,arm}_manifest.json`, PR #16 body, and the current continuation spec. No model calls.

## Inconsistencies found (v1) → resolved in v2
| # | Item | v1 (stale) | v2 (authoritative) |
| --- | --- | --- | --- |
| 1 | P1 runs | 12 × 2 = 24 | **12 × 7 = 84** (matches frozen `oracle_smoke_manifest.json`) |
| 2 | P2 cells | plan-body 411 / §8 320 | **40 × 7 = 280** (matches frozen `oracle_dev_manifest.json`) |
| 3 | dev task count | 53 | **40** (frozen oracle dev set) |
| 4 | primary contrast | O6 − O2 | **Q1 O5−O2 · Q2 O5−O4 · Q3 O6−O5** (Holm) |
| 5 | approval var | pre-requested `R22_MAIN_BUDGET_USD` | **P3 withheld** (power-blocked); main budget forbidden |
| 6 | reader | final return implied one reader directly | **frozen candidate ladder + [0.10,0.70] band selection** |

## Ground truth already frozen (consistent, unchanged)
- `oracle_smoke_manifest.json`: 12 pairs × 7 arms = **84** (P1).
- `oracle_dev_manifest.json`: 40 pairs × 7 arms = **280** (P2).
- Mixed grader: **PASS 12/12** gold, 12/12 no-patch unresolved, infra 0, completeness 24/24.
- Credential-free CI: **8/8 green**. Paid API calls: **0**. main `ce10ab4` / tag `v0.3.0-rc1` / seal `dd79f3d2` /
  oracle freeze `100d7caa` — unchanged.

## Resolution
A single authoritative **v2** plan is produced (`configs/r22/paid_run_plan_v2.json`,
`artifacts/r22/oracle_arm_manifest_v2.json`, `docs/R22_PAID_ORACLE_PREREGISTRATION_V2.md`,
`reports/R22_PAID_COST_PLAN_V2.md`, `artifacts/r22/paid_v2_freeze.json`). v1 files are **preserved** and marked
`SUPERSEDED FOR PAID EXECUTION BY R22 PAID V2`. Costs are recomputed programmatically
(`scripts/r22_recompute_paid_costs.py`) and locked by `tests/unit/test_r22_paid_plan_consistency.py`.
