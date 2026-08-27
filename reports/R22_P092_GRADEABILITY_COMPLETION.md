# R22-P0.9.2 §5 — Gradeability audit COMPLETION

Combines the frozen **53** P0.9.1 target results (byte-for-byte, not re-run) with the **2** P0.9.2 resume results
(`artifacts/r22_p092/dev55_gradeability_results_complete.json`). **Audit complete = True** — all 55 targets carry a
terminal label; no INFRA_FAILURE, no UNKNOWN.

## Resume outcome (run 33050922491)
Both frozen missing targets hit the **fixed 180-min timeout again** (`RESUME_RC=124`, 07:44→10:44): gold completed
for `sympy-20959` (F2P 6/6) but the gold+noop pair exceeds 180 min, so no full result. Per §3 both are labelled
**`UNGRADEABLE_TOOLCHAIN` / `PERSISTENT_TIMEOUT_180M`** — an instrument-execution classification, not a model
failure. No third attempt.

## Completed 55-target labels
| label | count |
|---|---|
| GRADEABLE | 43 |
| UNGRADEABLE_GOLD | 10 |
| UNGRADEABLE_TOOLCHAIN | 2 |
| (INFRA_FAILURE / UNKNOWN / SELECTOR / CASE_IMAGE) | 0 |

| pool | GRADEABLE | UNGRADEABLE_GOLD | UNGRADEABLE_TOOLCHAIN |
|---|---|---|---|
| ORIGINAL_P2 (40) | **31** | 9 | 0 |
| DEV_RESERVE (15) | 12 | 1 | 2 |

**Gradeable composition (43): python 34, go 4, java 3, rust 2** — Python-heavy but **retains Multilingual**
(Go/Java/Rust). Subsets: Verified 19, Lite 15, Multilingual 9.

## The 10 UNGRADEABLE_GOLD — corrected characterization
The 9 ORIGINAL_P2 gold-fails are rust/php/ruby. For **ruff (rust)** the P0.9.2 selector-level diagnostic proves the
label is caused by **`R5_UPSTREAM_PARSER_BUG`**: the intended tests pass under the official gold (1/1, 98/98) but the
evaluator's parser miscounts them. The php/ruby gold-fails were **not** separately diagnosed at the selector level,
so their exact cause is not claimed (the UNGRADEABLE_GOLD label there is an official-grader outcome, whatever its
internal cause). Either way these targets are **unusable for a memory experiment** because the official grader
cannot score reader patches on them.

Evidence: `artifacts/r22_p092/dev55_gradeability_results_complete.json`,
`artifacts/r22_p092/dev55_gradeability_evidence_manifest.json`, `artifacts/r22_p092/SHA256SUMS`. The P0.9.1
campaign artifacts are preserved unchanged.
