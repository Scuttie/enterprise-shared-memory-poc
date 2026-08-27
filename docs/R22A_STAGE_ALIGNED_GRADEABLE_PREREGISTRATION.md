# REALBENCH-R22A — Stage-aligned gradeable, V1 — Preregistration

**Experiment ID:** `REALBENCH_R22A_STAGE_ALIGNED_GRADEABLE_V1`. Does **not** mutate R22 (`R22_SCB_GRADER_GATE_FAIL`,
frozen). Sealed from the **completed** P0.9.2 gradeability audit (55/55 terminal) by the committed deterministic
generator (`scripts/r22a_build_manifests.py`, `scripts/r22a_seal.py`) — no manual preference introduced after seeing
outcomes.

## Selection (deterministic, outcome-blind rule; frozen before results were read)
- Start from the original 40 P2 targets; **retain every GRADEABLE original** (31); **drop the 9 ungradeable**
  (`astral-sh__ruff-15725/-16445`, `laravel__framework-52660`, `php-cs-fixer__php-cs-fixer-8027/-8058/-8398`,
  `rubocop__rubocop-13096/-13299/-13623`).
- Back-fill 9 vacancies from **GRADEABLE DEV_RESERVE** only, priority: same-language → same-subset →
  repository/temporal → `sha256(EXPERIMENT_ID|target_id)`. Reserves used: `tokio-rs__tokio-3679` (rust) + 8 sympy
  (`sympy-19235/-19484/-19976/-21203/-21309/-27868/-7229/-9384`). No held-out-main borrowed.
- Dual-pair sources frozen (`artifacts/r22_p09/dual_pair_source_selection.json`).

## Sealed manifests (`artifacts/r22a/`, `configs/r22a/experiment_lock.json`)
| item | value |
|---|---|
| P2 targets / cells | **40 / 280** (all 40 GRADEABLE) |
| P1 targets / cells | **12 / 84** (all 12 GRADEABLE) |
| P2 `manifest_sha256` | `b1a7dac56aa9b519…` |
| P1 `manifest_sha256` | `bdab5e0ea6f393bf…` |
| source/target overlap | 0 |
| `source_user == target_user` | 0 |
| O2 fixed points | 0 |
| target patch/test leakage | 0 |

**P2 composition (40):** python 31, java 3, go 4, rust 2. Subsets: Verified 17, Lite 14, Multilingual 9.
**P1 (12):** lucene (java), ruff-15997 (rust), astropy ×5, caddy ×2 (go), sympy-9384, tokio-3679 (rust).

## P1 credential-free discrimination (verified FROM the completed audit)
All 12 P1 targets are GRADEABLE in the audit ⇒ **gold resolved 12/12, noop resolved 0/12**, patch applied 24/24,
tests executed 24/24, image digest 12/12, infra 0, result completeness 24/24. (The P1 targets are a subset of the 55
audited targets; no separate P1 run was needed.)

## Estimand
"Memory effect on the **pre-model, official-grader-gradeable SWE-ContextBench development subset**" — Python-heavy,
retaining Multilingual (Java/Go/Rust). It does **not** represent all SWE-ContextBench languages; php/ruby and the 2
timed-out sympy reserves are outside the gradeable instrument. Contrasts kept: **Q1 = O5−O2, Q2 = O5−O4,
Q3 = O6−O5**. **P3 confirmatory main: NOT RUN / POWER BLOCKED.**

Reader selection is **not** started automatically (separate approval).
