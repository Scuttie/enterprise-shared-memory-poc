# R22-P0.9.1 — Execution-package closure

Pre-execution status (before the sentinel is created): **`R22_P09_STATIC_FORENSICS_COMPLETE_EXECUTION_PACKAGE_PENDING`**.

P0.9 static forensics stand. This milestone closes the execution-package defects so the P0.9 campaign can run
exactly once, credential-free (model/paid API = 0, no secret).

## Package fixes (all credential-free, tested)
1. **§2 One-time sentinel trigger** — `ci-r22-p09-gradeability.yml` gains a path-filtered `push` trigger on the
   **new** path `artifacts/r22_p09/EXEC_APPROVED_R22_P09` (content exactly `EXEC_APPROVED_R22_P09`); the gate accepts
   the dispatch input **or** that sentinel. It never touches `artifacts/r22/EXEC_APPROVED` (the 12-target SCB smoke
   sentinel). Regression tests: only the exact P0.9 path triggers; wrong content refuses; no secret read.
2. **§3 Ruff diagnostic** — a `ruff-forensics` job runs `scripts/r22_p09_ruff_forensics.py` on the 3 frozen ruff
   targets: raw `cargo test` + unfiltered collection + selector→name mapping + a separate parser pass, then a
   R1–R8 class per failed target. Updates `ruff_root_cause.json` / reports after the run.
3. **§4 Dual-pair source freeze** — `artifacts/r22_p09/dual_pair_source_selection.json` records, for
   `astropy__astropy-15082`, `sympy__sympy-12426`, `sympy__sympy-12427`, the competing sources (the 3 "extra pairs"
   are exact duplicates → one related source each), temporal validity, the deterministic selection hash, and the
   reason — frozen **before** any gradeability outcome.
4. **§5 Complete raw evidence** — every cell persists run_instance.log, test_output.txt, report.json,
   summary_report.json, stdout.log, stderr.log, dataset.json, prediction.json, plus patch/expected+observed digest;
   the evidence manifest records relpath + bytes + sha256 (not booleans); the aggregate exits nonzero on any missing
   required file. Negative tests per category.
5. **§6 One image pull per target** — `grade()` gains `keep_instance_image` (GOLD passes
   `--no-remove-instance-image`) and `reuse_pulled_image` (NOOP reuses the verified local tag). A mocked-docker test
   asserts exactly **one** `docker pull` for GOLD+NOOP and that observed digest == frozen expected.
6. **§7/§8 Fail-closed audit** — matrix strictly from `dev55_gradeability_manifest.json` (55 targets / 110 cells);
   fail-closed aggregate over unique/duplicate/missing/digest/INFRA/UNKNOWN/evidence; GRADEABLE count is a
   scientific result, not an aggregate failure; `<40` gradeable dev targets → `R22_BENCHMARK_INSTRUMENT_NOT_VIABLE`.

## Reconciliation (unchanged from P0.9)
58 relationship pairs → **55 unique evaluator targets** = 40 ORIGINAL_P2 + 15 DEV_RESERVE (3 targets recur across 2
identical pairs). Audit = 55 targets / 110 cells.

## R22A (§9)
Generation code + a synthetic replacement regression test are built (`scripts/r22a_build_manifests.py`); real R22A
manifests are sealed only **after** the audit shows ≥40 gradeable dev targets and the new P1 discriminates 12/12.
`main`, `v0.3.0-rc1`, R1–R21, R22 seals, the original R22 campaign, and `grader_smoke.json` remain frozen. R22 stays
`R22_SCB_GRADER_GATE_FAIL`. No reader selection / P1 / P2 / P3.
