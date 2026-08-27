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

## Observation — the UNGRADEABLE_GOLD label clusters by language
The 9 UNGRADEABLE_GOLD among ORIGINAL_P2 are the rust/php/ruby targets: `astral-sh__ruff-15725/-16445` (rust);
`laravel__framework-52660`, `php-cs-fixer__php-cs-fixer-8027/-8058/-8398` (php);
`rubocop__rubocop-13096/-13299/-13623` (ruby). Python/Java targets grade normally. This is a **per-label
observation** over the completed 53 cells — **not** a proven "the multilingual path is defective" claim: only ruff
is being diagnosed at the selector level (P0.9.2 §4); php/ruby were not separately diagnosed. Note the gradeable
pool **retains** other Multilingual targets (Java/Go/Rust), so this is not a Python-only story.

## Ruff — corrected claim boundary (§1)
The executed diagnostic (`ruff_diagnostic_results.json`) established, for both failed ruff targets: compile **OK**,
base_commit **matches**, **509–592 tests collect and run** directly via the byte-identical `cargo test`.
**TRUE_ZERO_COLLECTION is excluded; the adapter, image digest, base commit, and patch application are valid.**
The auto-classifier's `R6_UPSTREAM_GOLD_INVALID` is **overridden** (it keyed on the full-suite exit code, which the
**resolved** positive control also shows). However, **the precise failure is UNRESOLVED** until the intended
FAIL_TO_PASS selectors are scored directly under the official gold patch (P0.9.2 §4). Current class:
**`R8_UNKNOWN`** for both. **No R2/R5/R6 claim is made yet.** Excluded with evidence: R1, R4, R7, TRUE_ZERO.

## R22A viability (NOT sealed)
40 GRADEABLE targets are **achievable** (31 gradeable originals + 9 gradeable reserves; 12 gradeable reserves
available). The 9 removed originals are rust/php/ruby; replacements draw from gradeable reserves per the frozen
deterministic rule, giving a **Python-heavy official-gradeable subset that still retains Multilingual (Java/Go/Rust)
targets** — not a Python/Java-only benchmark. R22A is **not sealed** here: the audit is incomplete (2 python
reserves pending, P0.9.2 resume) and the exact composition is reported once complete. Generation code + regression
tests are ready (`scripts/r22a_build_manifests.py`).

## Recommended next step (user decision)
1. Resume the 2 sympy reserves with a longer timeout to **complete the audit** (they are python → almost certainly
   GRADEABLE → 45 total; does not change the multilingual finding), then
2. decide whether a **Python/Java-only** R22A (dropping the systematically-ungradeable multilingual targets) is the
   intended instrument, or whether the multilingual selector/parser defect should first be resolved upstream.

Preserved: original R22 (`R22_SCB_GRADER_GATE_FAIL`), seals, `grader_smoke.json`. No merge/tag/release; no reader
selection / P1 / P2 / P3.
