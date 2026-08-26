# R22-P0.9.1 — Audit + diagnostic results

**Run 32922333871** (commit `c9b32df`, EXEC_APPROVED_R22_P09). Credential-free: no secret, no model, official images
by frozen digest, **paid API = 0**.

## Endpoint: `R22_P09_GRADEABILITY_AUDIT_INCOMPLETE`
The fail-closed aggregate exited nonzero: **53/55 targets graded, 2 missing**. The 2 missing
(`sympy__sympy-20959`, `sympy__sympy-21758`, both DEV_RESERVE, python) **timed out** — each shard hit the 90-min
`timeout` (started 05:02, killed 06:32, exit 124). This is an **infrastructure/resource limit** (their gold+noop
in-container suites exceed 90 min), not a scientific outcome; per §7 they are resumable under the same target key
with a longer timeout.

## Gradeability landscape (53 graded)
| label | count |
|---|---|
| GRADEABLE | 43 |
| UNGRADEABLE_GOLD | 10 |
| UNGRADEABLE_SELECTOR / CASE_IMAGE / TOOLCHAIN / INFRA_FAILURE / UNKNOWN | 0 |

| pool | GRADEABLE | UNGRADEABLE_GOLD | not tested |
|---|---|---|---|
| ORIGINAL_P2 (40) | **31** | 9 | 0 |
| DEV_RESERVE (15) | 12 | 1 | 2 (timeout) |

Discrimination held throughout: noop resolved 0/55, image digest verified on every graded target, 0 infra failures
among the 53. The 10 UNGRADEABLE_GOLD are targets whose **official gold patch does not resolve under the official
evaluator**.

## Systematic finding — the gold-fail is a MULTILINGUAL cluster
The 9 UNGRADEABLE_GOLD among ORIGINAL_P2 are **exactly the rust/php/ruby multilingual targets**:
`astral-sh__ruff-15725`, `astral-sh__ruff-16445` (rust); `laravel__framework-52660`,
`php-cs-fixer__php-cs-fixer-8027/-8058/-8398` (php); `rubocop__rubocop-13096/-13299/-13623` (ruby). Every
Python/Java target grades normally. So the defect is concentrated in the **multilingual selector/parser path of the
official evaluator**, not in isolated instances.

## Ruff root cause (executed diagnostic, `ruff_diagnostic_results.json`)
For both failed ruff targets the diagnostic (same official image, same patches, byte-identical `cargo test`):
compile **OK**, base_commit **matches**, and **509–592 tests collect and run directly**. This **excludes** R1
(command matches), R4 (base drift), R7 (toolchain), and true-zero-collection. The official evaluator's
"Collected 0 test results" is therefore a **selector/parser matching artifact** (the FAIL_TO_PASS selector names are
not matched in the cargo output), i.e. **R2/R5 territory — not our adapter and not confirmed gold-invalid**. The
auto-classifier's `R6_UPSTREAM_GOLD_INVALID` is **overridden**: it keys on the full-suite exit code (rc 101), which
the **resolved** positive control (`ruff-15997`) also shows, so it does not distinguish gold validity. Rigorous
class: **`R8_UNKNOWN`, narrowed to {R2_CASE_SELECTOR_BUG, R5_UPSTREAM_PARSER_BUG}**. The decisive per-selector
pass/fail was not captured (diagnostic `selector_mapping` empty) — the one remaining diagnostic.

## R22A viability (NOT sealed)
40 GRADEABLE targets are **achievable** (31 gradeable originals + 9 gradeable reserves; 12 gradeable reserves
available). **But** the 9 removed originals are rust/php/ruby, and the multilingual targets are systematically
ungradeable — so any gradeable R22A would be **Python/Java-dominated**, materially changing the benchmark's
language coverage. R22A is therefore **not sealed**: the audit is incomplete (2 python reserves pending) and the
Python/Java-only composition is a design decision for the user, not an automatic fill. R22A generation code +
regression tests are ready (`scripts/r22a_build_manifests.py`).

## Recommended next step (user decision)
1. Resume the 2 sympy reserves with a longer timeout to **complete the audit** (they are python → almost certainly
   GRADEABLE → 45 total; does not change the multilingual finding), then
2. decide whether a **Python/Java-only** R22A (dropping the systematically-ungradeable multilingual targets) is the
   intended instrument, or whether the multilingual selector/parser defect should first be resolved upstream.

Preserved: original R22 (`R22_SCB_GRADER_GATE_FAIL`), seals, `grader_smoke.json`. No merge/tag/release; no reader
selection / P1 / P2 / P3.
