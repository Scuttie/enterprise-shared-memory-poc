# R22A — Gradeability audit + selection audit (SEALED)

New experiment `REALBENCH_R22A_STAGE_ALIGNED_GRADEABLE_V1`; R22 remains `R22_SCB_GRADER_GATE_FAIL` (frozen).
The P0.9.2 audit is **complete** (55/55 terminal labels) and R22A is **sealed**. See
`docs/R22A_STAGE_ALIGNED_GRADEABLE_PREREGISTRATION.md` for the full preregistration.

## Audit completion (P0.9.2)
58 pairs → 55 unique targets (40 ORIGINAL_P2 + 15 DEV_RESERVE). Labels: **43 GRADEABLE, 10 UNGRADEABLE_GOLD,
2 UNGRADEABLE_TOOLCHAIN** (the 2 sympy reserves persistently timed out at 180 min). No INFRA/UNKNOWN.
`R22_P092_GRADEABILITY_COMPLETION.md` has the breakdown.

## Selection (deterministic, outcome-blind)
- 31 GRADEABLE originals retained; 9 ungradeable originals (rust/php/ruby) removed.
- 9 vacancies filled from GRADEABLE DEV_RESERVE by the frozen priority (same-language → same-subset → repo/temporal
  → `sha256(EXPERIMENT_ID|target_id)`): `tokio-rs__tokio-3679` + 8 sympy.
- Dual-pair sources frozen.

## Sealed R22A (all post-conditions pass)
- **P2: 40 targets / 280 cells**, all 40 GRADEABLE; source/target overlap 0, `source_user==target_user` 0, O2 fixed
  points 0, leakage 0. `manifest_sha256 b1a7dac5…`.
- **P1: 12 targets / 84 cells**, all 12 GRADEABLE ⇒ gold 12/12, noop 0/12 (from the audit). `manifest_sha256 bdab5e0e…`.
- Composition (P2): python 31, java 3, go 4, rust 2 — **Python-heavy, retains Multilingual (Java/Go/Rust)**; NOT a
  Python-only benchmark.

## Ruff finding informing the removals
The removed ruff targets are `R5_UPSTREAM_PARSER_BUG` (the official gold is valid — the evaluator's parser
miscounts; `ruff_root_cause_v2.json`). They are excluded because the **official grader cannot score** reader patches
on them, which is disqualifying for a memory experiment regardless of gold validity.

## Endpoint
`R22A_GRADEABLE_MANIFEST_READY_FOR_READER_SELECTION`. Reader selection is a **separate** approval; P3 confirmatory
main remains NOT RUN / POWER BLOCKED. model/paid calls = 0.
