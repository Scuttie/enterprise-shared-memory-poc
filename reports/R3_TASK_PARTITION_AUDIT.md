# R3 §5 — DS-1000 Frozen Task Partition Audit

Deterministic, near-duplicate-safe partition of the official 1000-task DS-1000 universe. No model calls; bound to
the pinned dataset (`data_file_sha256 = e8c6daa9…`). Builder `experiments/actionable_memory_r3/partition.py`,
runner `scripts/r3_build_partition.py`, artifact `artifacts/actionable_memory_r3/task_partition.json`.
**split_hash = `e16bfb852f7395cb`**, seed 20260815.

## Realised split sizes (targets in parens)
| split | size | target |
|---|---|---|
| SOURCE_POOL | **200** | 200 (≥150 required) |
| RETRIEVAL_DEV | 79 | 80 |
| REPRESENTATION_DISCOVERY | **120** | 120 |
| INSTRUMENT_CALIBRATION | **100** | 100 |
| CONFIRMATORY_MAIN | **451** | 450 (≥400 required) |
| RESERVE | 50 | 50 |
| **total** | **1000** | 1000 |

MAIN = 451 ≥ 450 → the confirmatory main uses the frozen 450 (§17). SOURCE = 200 ≥ 150.

## Near-duplicate rule (stronger than a Jaccard threshold)
DS-1000 contains **perturbation families**: Surface / Semantic / Difficult-Rewrite variants share a
`(library, perturbation_origin_id)` with their Origin task and are near-duplicates *by construction*
(453 families, sizes 1–7). The frozen rule assigns **each whole family atomically to one split**, so no family
member ever crosses a split boundary. Audit: **family_span_violations = 0** → source∩target near-duplicate
leakage = 0 by design, not by a tuned threshold.

## Hard requirements (§5) — all satisfied
- source ∩ target = 0, and discovery/calibration/main mutually disjoint (verified: 1000 unique ids across the 6
  disjoint sets).
- near-duplicate pairs removed under one frozen rule (atomic family assignment; 0 span violations).
- **function/signature collision:** the dominant reference wrapper names (`g` ×290, `solve` ×14, …) are the
  DS-1000 *harness convention* (solutions are wrapped in a small named function), not per-task identity — the
  same benign shared-harness situation noted in R2. No task-identifying signature leaks across splits because
  families are atomic.
- **target-solution leakage = 0 / hidden-test leakage = 0:** enforced structurally — memory is built only from
  SOURCE_POOL families, and the canonical object (§7) carries no target values/names/tests
  (`assert_no_target_leakage`); target `code_context`/`reference_code` never enter a target prompt.

## Library stratification (every split covers all 7 libraries proportionally)
CONFIRMATORY_MAIN per-library: Pandas 131, Numpy 99, Matplotlib 70, Sklearn 52, Scipy 48, Pytorch 31,
Tensorflow 20. SOURCE_POOL: Pandas 58, Numpy 44, Matplotlib 31, Sklearn 23, Scipy 21, Pytorch 14, Tensorflow 9.
REPRESENTATION_DISCOVERY: Pandas 35, Numpy 26, Matplotlib 19, Sklearn 14, Scipy 13, Pytorch 8, Tensorflow 5.
(Full per-split library tables in `task_partition.json`.) Proportional coverage supports the §16 G3
dynamic-range strata and §17 main library breakdown.

## Deterministic adjustment rule (recorded before calls, §5)
Because families are atomic (sizes 1–7), exact per-split integer targets are not always hit. Rule: within each
library, order families by origin id, seeded-shuffle (seed 20260815), then assign largest-family-first to the
split with the greatest remaining per-library quota deficit, in the fixed priority order
MAIN→SOURCE→DISCOVERY→CALIB→DEV→RESERVE. This keeps MAIN≥400 and SOURCE≥150 while preserving family atomicity
and library proportions. The rule is frozen in code; re-running reproduces `split_hash e16bfb852f7395cb`.
