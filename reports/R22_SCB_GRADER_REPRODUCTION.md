<!-- R22_CURRENT_ENDPOINT: R22_UPSTREAM_EVALUATOR_EXECUTION_REVIEW -->
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

## Status — PENDING EXECUTION APPROVAL (not run)
This smoke **executes the pinned upstream evaluator**, whose code has **no explicit license**
(`R22_UPSTREAM_RIGHTS_STATUS.md`), and needs a Docker host. It is dispatch-only and gated on
`confirm_exec_approved=EXEC_APPROVED` + `R22_SCB_UPSTREAM_EXEC_APPROVED=1`. Until then it does not execute upstream
code. **paid API calls = 0.**

On approval → dispatch `ci-r22-scb-grader-smoke` with `EXEC_APPROVED` → 24 cells populate
`artifacts/r22/scb_grader_smoke.json`; if all criteria pass the endpoint flips to
`R22_OFFICIAL_SCB_GRADER_READY_AWAITING_READER_SELECTION`.

### Manifest-hash reconciliation note
The P0.8.1 §4 "required manifest hash" `9e2d24a8…` matches neither the committed bytes (`895bcdd2…`) nor any
canonical content hash of `oracle_smoke_manifest.json`; the frozen 12-target identity is intact
(`081440db…`). The prepare job verifies the real frozen identity and records
`spec_manifest_hash_matches:false` in `artifacts/r22/scb_smoke_matrix.json` for reconciliation — the frozen
manifest was not altered.
