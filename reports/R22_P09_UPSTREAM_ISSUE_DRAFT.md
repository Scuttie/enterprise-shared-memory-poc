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

## Diagnostic still required before assigning a class (we have not run it)
Run `cargo test` in the two affected base/official images and capture the **raw** stdout + return code, plus a
diagnostic unfiltered collection, to determine whether it is: a compile/pre-collection failure, tests that run but
whose names the parser fails to match, or an invalid gold. That diagnostic is gated (`EXEC_APPROVED_R22_P09`).

## Provenance (no secrets, no model output)
Pinned case JSON hashes, official image digests, and evaluator file/tree hashes are in the reproducer manifest and
`artifacts/r22_p09/ruff_forensic_manifest.json`. Public source: `github.com/jiayuanz3/SWEContextBench` @ the pinned
commit; case files under `cases/SWEContextBench Multilingual/`.
