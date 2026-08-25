<!-- R22_CURRENT_ENDPOINT: R22_SCB_GRADER_GATE_FAIL -->
# R22-P0.8/P0.8.1 — Official SCB grader discrimination smoke (frozen P1 12)

**This is the authoritative CURRENT R22 grader gate.** It supersedes the generic enriched-SWE-bench G0.1 result
(`reports/R22_GRADER_REPRODUCTION.md` = `GENERIC_ENRICHED_SWEBENCH_GRADER_PASS`,
`artifacts/r22/grader_smoke_supersession.json`).

Driver: `scripts/r22_scb_grader_smoke.py` · Matrix: `scripts/r22_scb_prepare_matrix.py` (from the frozen manifest)
Workflow: `.github/workflows/ci-r22-scb-grader-smoke.yml` · Adapter:
`experiments/r22/runtime/scb_official_grader.py` · Result: `artifacts/r22/scb_grader_smoke.json` (on approval).

## Design (P0.8.1)
Per frozen P1 target, one per-target shard, two conditions via the **benchmark-specific** evaluator (pinned
ephemeral checkout of `swebench_memory.harness.run_evaluation`):
- **GOLD** = official case `patch` → expect resolved, FAIL_TO_PASS complete, PASS_TO_PASS 0 regression.
- **NOOP-BASELINE** = `NOOP_BASELINE_PATCH` (adds `.r22_noop`; **no** source/test change) → expect **unresolved**
  but with the official test_patch applied and FAIL_TO_PASS/PASS_TO_PASS **actually executed**
  (`patch_applied=true`, `tests_status` present) — **not** the empty-patch "No patch" short-circuit.

Three P0.8.1 hardenings vs P0.8:
1. **§2** the baseline is a real no-op patch; an **empty** patch is explicitly rejected as an invalid control
   (`assert_valid_baseline_patch` → `EmptyBaselineRejected`).
2. **§3** the official image is **pulled by immutable digest** (`docker pull --platform linux/amd64 repo@sha256:…`),
   `observed_digest` is required to equal the frozen `expected_digest` (else `ImageDigestMismatch` →
   `R22_SCB_IMAGE_INTEGRITY_BLOCK`), and that exact image is locally tagged as the evaluator's pull tag.
3. **§4** the 12-target matrix is derived from the frozen `oracle_smoke_manifest.json` (no second hard-coded list).

## Pass criteria (§6)
GOLD: patch_applied=true · infra_ok=true · resolved=true · FAIL_TO_PASS complete · PASS_TO_PASS regression=0.
NOOP-BASELINE: patch_applied=true · infra_ok=true · resolved=false · tests actually executed · failure ≠ "No patch".
Campaign: target completeness 12/12 · result completeness 24/24 · gold 12/12 · noop 0/12 · infra 0 ·
expected==observed digest 12/12 · official tests modified by us 0.

## Status — EXECUTED (user-authorized EXEC_APPROVED) → `R22_SCB_GRADER_GATE_FAIL`
The smoke was executed once under the user's EXEC_APPROVED (GitHub Actions run **32863011986**, commit `6f55b83`;
credential-free — no secret, no model, paid API = 0; official images pulled by digest). 24 cells completed.

**Harness fully validated:** noop-baseline resolved **0/12** (perfect discrimination), image expected==observed
digest **12/12**, infrastructure failures **0**, tests actually executed on all 24 cells, missing raw evidence
**0**. A first attempt (run 32858666703) exposed a harness bug — the evaluator ran with a relative `PYTHONPATH`
under `cwd=results_dir` (`ModuleNotFoundError: swebench_memory`) — fixed (absolute paths) with a regression test;
that run was cancelled, not counted.

**Gate FAIL — 2 targets:** gold resolved **10/12**. The two failures are **`astral-sh__ruff-15725`** and
**`astral-sh__ruff-16445`**: with the **official gold patch** applied on the **official image**, the official
evaluator reports **`FAIL_TO_PASS 0/98` ("Collected 0 test(s)")** while `PASS_TO_PASS` passes — i.e. the gold patch
does not resolve those two instances under the benchmark's own evaluator. This is an **upstream benchmark/evaluator
inconsistency for those 2 instances**, not a harness defect (the 3rd ruff `ruff-15997` and all Java/Go/Python
targets resolve 10/10 gold + 10/10 F2P-complete). Per §5 the run is preserved and **not** re-run. The frozen 12
set (§0) was not altered.

<!-- SCB_RESULTS_START -->
## Results (aggregated from shard artifacts)
Verdict: **FAIL** — endpoint `R22_SCB_GRADER_GATE_FAIL`.

| gate | value |
|---|---|
| gold resolved | 10/12 |
| noop resolved | 0/12 |
| gold tests_executed | 12/12 |
| noop tests_executed | 12/12 |
| expected==observed digest | 12/12 |
| infra failures | 0 |
| missing raw evidence | 0 |
| duplicate cells | 0 |

Failed gates: ['gold_resolved', 'gold_f2p_complete']
<!-- SCB_RESULTS_END -->

### Manifest semantic hash (P0.8.2 §1)
`9e2d24a8a04a22b8…` is the manifest's **semantic** hash — `sha256(json.dumps(task_list, sort_keys=True))` over the
84 frozen task-arm rows — and is stored in the manifest as `manifest_sha256`. The prepare job recomputes it and
requires `task_list_manifest_sha256 == embedded_manifest_sha256 == 9e2d24a8…` (`spec_manifest_hash_matches:true`).
Three integrity values are kept distinct and never cross-compared: `manifest_file_sha256` (LF bytes),
`task_list_manifest_sha256` (`9e2d24a8…`), `frozen_target_ids_sha256` (`081440db…`, sorted 12 IDs). The earlier
P0.8.1 "UNRECONCILED" note was a mistake (it hashed the whole file / wrong object) and is withdrawn.
