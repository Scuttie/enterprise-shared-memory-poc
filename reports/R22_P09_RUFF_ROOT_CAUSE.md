# R22-P0.9 §3/§4 — Ruff gold-fail root-cause (static forensics)

All answers below are from the **existing captured campaign evidence** (run 32863011986). No diagnostic execution
has run; questions that require the raw `cargo test` output inside the container are marked **PENDING §3.5 EXEC**.

## §3.1 Did the official patches apply? → `PATCH_APPLY_OK` (all cells)
From each cell's `run_instance.log` + `test_output.txt`:
- official **test patch applied** ("Applying test patch… ✓ Test patch applied successfully"; a few trailing-whitespace
  warnings, non-fatal);
- official **gold model patch applied** ("Applying model patch… ✓ Model patch applied successfully");
- eval.sh order is test-patch → model-patch → `cargo test`; no ensure-patch reordering (`Ensure patch: False`); no
  silent gold-patch sanitization (the applied patch sha matches the frozen case gold hash).
→ Not `TEST_PATCH_APPLY_FAIL`, not `GOLD_PATCH_APPLY_FAIL`, not `PATCH_ORDER_MISMATCH`, not `PATCH_SANITIZATION_DRIFT`.

## §3.2 Do the FAIL_TO_PASS identifiers exist? → **PENDING §3.5 EXEC**
- F2 (`ruff-16445`) lists **98** selectors of the form `rules::pyupgrade::tests::<name>` (e.g.
  `rules::pyupgrade::tests::future_annotations_pep_604_py310`). F1 (`ruff-15725`) lists **1** selector. POS
  (`ruff-15997`) lists 1 selector `rules::flake8_pie::tests::rules::rule_unnecessaryspread_path_new_pie800_py_expects`.
- Whether these files/test-functions exist and are collected **after** the official test patch requires inspecting
  the container's compiled test set — not present in the captured evidence. Cannot yet distinguish `SELECTOR_EXACT` /
  `SELECTOR_NORMALIZATION_REQUIRED` / `SELECTOR_NOT_PRESENT` / `TEST_FILE_NOT_CREATED`.

## §3.3 What command collected tests? → identical bare `cargo test` for all three
Exact `eval.sh` (byte-frozen; sha in the forensic manifest), same for F1, F2, and POS:
```bash
#!/bin/bash
set -euxo pipefail
cd /testbed
if [ -f /test.patch ]; then git apply /test.patch || echo "Test patch already applied or failed"; fi
git apply /patch.diff
source $HOME/.cargo/env && cargo test
```
There is **no test-name filter** — the evaluator runs all tests and parses stdout to match the case selectors.
Because the failing targets and the passing control run the **identical** official command, **`R1` (our adapter
invocation) is EXCLUDED**.

## §3.4 Was "0 tests" collection or parsing? → **PENDING §3.5 EXEC** (D and E ruled out)
`run_instance.log` shows "Collected 0 test results" **both before and after** the model patch, **and** the
evaluator's "fix-first fallback re-running on base image (no patches applied) → also 0 results". The parsed
`tests_status` then lists every FAIL_TO_PASS selector as a *failure* (0 passed) — so our `tests_executed=true` flag
only means "the evaluator emitted a tests_status", **not** that tests actually ran.
- **E `TEST_PATCH_MISSING`: ruled out** (test patch applied, §3.1).
- **D `FILTER_MISMATCH`: ruled out** (bare `cargo test`, no name filter).
- Remaining candidates — `TRUE_ZERO_COLLECTION` (A), `PARSER_ZERO_ONLY` (B), `PRE_COLLECTION_FAILURE` (C, e.g. a
  compile failure so `cargo test` produced no parseable results) — cannot be separated without the **raw `cargo test`
  stdout/return code**, which the captured evidence does not contain (only the evaluator's parsed summary was saved).

## §3.5 Is the official gold valid? → **PENDING §3.5 EXEC**
Requires running, on the unmodified official image/case: apply test patch + gold patch, run the exact `cargo test`,
plus a diagnostic **unfiltered** collection (forensic evidence only, not an official score) to see whether the
intended tests collect and whether gold passes them. Not run (execution not approved).

## §4 — Primary root-cause class per failed target
| target | primary class | excluded (with evidence) | live candidates (need §3.5) |
|---|---|---|---|
| astral-sh__ruff-15725 | **R8_UNKNOWN** | R1 (identical official `cargo test` to passing control) | R3, R4, R5, R6, R7 |
| astral-sh__ruff-16445 | **R8_UNKNOWN** | R1 (identical official `cargo test` to passing control) | R3, R4, R5, R6, R7 |

Per §4, `R8_UNKNOWN` is assigned because **none** of R2–R7's evidence requirements can be met from static evidence
(each needs the raw in-container `cargo test` output). What is established: **patches apply**, the **command is the
pinned official one** (R1 excluded), the image **digest is verified** (12/12 in the campaign), and the failure is a
**0-collection at the evaluator level that already occurs on the pristine base image** — independent of the gold
patch and of selector count (F1 has a single selector). The single diagnostic that discriminates R3/R4/R5/R6/R7 is
the §3.5 raw `cargo test` collection, which is gated on `EXEC_APPROVED_R22_P09`.

Deliberately **not** concluded: "upstream defect". Per §4, upstream is not assigned merely because the file came
from upstream; the specific upstream class (R5 parser / R6 gold-invalid) is unproven until §3.5.
