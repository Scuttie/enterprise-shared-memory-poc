# R22-P0.9 §5 — Upstream issue DRAFT (not posted)

> **Do not post automatically.** Posting requires separate user approval. No upstream source code is copied into
> this repository. This draft describes a **candidate** defect; the exact class is confirmed only after the
> `EXEC_APPROVED_R22_P09` diagnostic (§3.5) runs. Machine-readable reproducer:
> `artifacts/r22_p09/upstream_reproducer_manifest.json`.

**Repository:** `jiayuanz3/SWEContextBench` (evaluation harness) · **pinned commit:**
`31bb04155f52b184bf31b220e3cff0607ac9c953`

## Title (draft)
Some Ruff (Rust) instances score `FAIL_TO_PASS 0/N` with "Collected 0 test results" under the official evaluator,
including on the pristine base image, while other Ruff instances score correctly

## Summary
Grading two SWE-ContextBench **Multilingual** Ruff instances with the benchmark's own
`swebench_memory.harness.run_evaluation`, on the **official per-instance images**, with the **official gold patch**,
yields `FAIL_TO_PASS 0/N` because the evaluator reports **"Collected 0 test results"** — both before and after the
model patch, and in the harness's own "fix-first fallback re-run on the base image (no patches applied)". A third
Ruff instance in the same run grades correctly (`Collected 9`, resolved). The failure is independent of selector
count (one failing instance has a single FAIL_TO_PASS selector).

## Affected instances
| instance | FAIL_TO_PASS | PASS_TO_PASS | collected | resolved |
|---|---|---|---|---|
| `astral-sh__ruff-15725` | 1 | 35 | 0 | no |
| `astral-sh__ruff-16445` | 98 | 2 | 0 | no |
| `astral-sh__ruff-15997` (positive control) | 1 | 8 | 9 | yes |

## Exact command (from the harness's generated `eval.sh`, identical for all three)
```bash
cd /testbed
git apply /test.patch
git apply /patch.diff        # official gold
source $HOME/.cargo/env && cargo test
```
(no test-name filter; the harness parses `cargo test` stdout to match the case's FAIL_TO_PASS/PASS_TO_PASS selectors.)

## Observed vs expected
- **Observed:** "Collected 0 test results" for the two affected instances (and on their base images with no patches);
  every FAIL_TO_PASS selector is then reported as a failure → `0/N`, `Resolved: False`.
- **Expected:** with the official gold applied, the intended FAIL_TO_PASS tests should collect and pass (as they do
  for `ruff-15997`).

## Diagnostic status (updated)
The raw `cargo test` diagnostic **has run** (run 32922333871): the code **compiles**, base_commit **matches**, and
**509–592 tests collect and run** directly via the identical command — so a compile/pre-collection failure and a
true-zero-collection are **excluded**, and the adapter/image/base/patch are valid. What remains is a **selector-level**
determination — whether each intended FAIL_TO_PASS test is (a) absent from `cargo test -- --list`, (b) present and
**passes** under gold but is scored failed/uncollected by the evaluator, or (c) present and **fails** under gold.
That P0.9.2 selector-level diagnostic **has now run** (run 33050922491) and is **decisive**: every intended
FAIL_TO_PASS selector, executed **directly** under the official gold patch with
`cargo test "<selector>" -- --exact`, **PASSES** — `astral-sh__ruff-15725` **1/1**, `astral-sh__ruff-16445`
**98/98** (0 fail, 0 absent) — yet the official evaluator scores every one not-passed. **The official gold is VALID;
the evaluator's PARSER miscounts the intended tests.** Class: **`R5_UPSTREAM_PARSER_BUG`** for both. This is the
concrete, reproducible defect to report (evidence: `artifacts/r22_p09/ruff_diagnostic_results_v2.json`). Still **not
posted** — posting requires separate user approval.

## Provenance (no secrets, no model output)
Pinned case JSON hashes, official image digests, and evaluator file/tree hashes are in the reproducer manifest and
`artifacts/r22_p09/ruff_forensic_manifest.json`. Public source: `github.com/jiayuanz3/SWEContextBench` @ the pinned
commit; case files under `cases/SWEContextBench Multilingual/`.
