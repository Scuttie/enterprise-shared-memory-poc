# R22A — Gradeability audit + selection pre-registration

New experiment ID: **`REALBENCH_R22A_STAGE_ALIGNED_GRADEABLE_V1`** (does not reuse R22; the original R22 remains
`R22_SCB_GRADER_GATE_FAIL`, frozen).

## Status: BLOCKED pending the gated gradeability execution
R22A construction (§9) requires the development-pool gradeability **results**, which require running the official
evaluator on the dev targets — gated on `EXEC_APPROVED_R22_P09` (not granted; model/paid = 0). Therefore **no R22A
manifest is sealed yet**. What is frozen now:
- `artifacts/r22_p09/dev55_gradeability_manifest.json` — the metadata freeze of the dev pool (case/image/gold/noop
  hashes, language, subset, ORIGINAL_P2 vs DEV_RESERVE), gradeability label `UNAUDITED`.
- The gated instrument (`ci-r22-p09-gradeability.yml` + `scripts/r22_p09_gradeability.py` + `r22_p09_aggregate.py`).

## Development-pool reconciliation (§7)
The v2 development partition is **58 pairs**, which resolve to **55 unique targets** = **40 ORIGINAL_P2 + 15
DEV_RESERVE**. Three targets (`astropy__astropy-15082`, `sympy__sympy-12426`, `sympy__sympy-12427`) appear in two
pairs each (different sources), so 58 pairs − 3 = 55 distinct targets. Gradeability is a **per-target** property, so
the audit set is **55 targets / 110 cells**, not 58/116. No target was dropped. Cases 55/55, images 55/55
linux-amd64, present. Language mix: python 36, java 3, rust 5, go 4, php 4, ruby 3.

## Pre-registered R22A selection algorithm (fixed BEFORE reading any gradeability outcome)
Recorded now so selection is deterministic and outcome-blind once the audit exists.

### P2 (§9.1) — 40 targets
1. Start from the original 40 P2 targets.
2. Remove only those classified **not GRADEABLE** by the pre-model official-gold/noop audit.
3. Fill each vacancy from the **15 DEV_RESERVE** targets, reserve priority fixed as:
   (a) same language as the removed target; (b) same benchmark subset; (c) preserve repository-cluster disjointness;
   (d) preserve source→target temporal validity; (e) among remaining, sort by
   `sha256("REALBENCH_R22A_STAGE_ALIGNED_GRADEABLE_V1|" + target_id)` ascending. No manual preference. No held-out
   main target borrowed.
4. Required post-conditions: P2 = 40, all 40 GRADEABLE, source/target overlap 0, target duplication 0, O2 fixed
   points 0, `source_user != target_user`, target patch/test leakage 0.
5. If fewer than 40 gradeable dev candidates remain → **`R22_BENCHMARK_INSTRUMENT_NOT_VIABLE`** (do not shrink N).

### P1 smoke (§9.2) — 12 targets
- Keep the 10 gradeable frozen P1 targets. Replace the 2 failed Ruff targets by the same reserve rule (same
  language → same subset → deterministic hash). Predeclared fallback if no same-language reserve exists: same subset,
  else any gradeable reserve by the deterministic hash. New P1 must pass 12/12 gold, 0/12 noop, infra 0.

### New freezes to be created on a passing audit (§9.3)
`configs/r22a/experiment_lock.json`, `artifacts/r22a/{p1_smoke_manifest,oracle_dev_manifest,oracle_arm_manifest,
task_selection_audit,freeze}.json`, `docs/R22A_STAGE_ALIGNED_GRADEABLE_PREREGISTRATION.md`. Recompute target hashes,
source assignments, derangement, token budgets, cost hard caps, repository clustering, effective N, P2 exploratory
power. Keep Q1=O5−O2, Q2=O5−O4, Q3=O6−O5. **P3 confirmatory main remains NOT RUN / POWER BLOCKED.**

Until the gated audit runs, none of the above is executed and no reader selection is started.
