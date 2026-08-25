# R22-P0.8 §6 — Official SCB grader discrimination smoke (12 P1 targets)

Driver: `scripts/r22_scb_grader_smoke.py` · Workflow: `.github/workflows/ci-r22-scb-grader-smoke.yml`
Adapter: `experiments/r22/runtime/scb_official_grader.py` · Result artifact (per shard):
`artifacts/r22/scb_grader_smoke_<instance>.json`.

## Design
For each of the 12 frozen P1 targets, in one per-target shard (image pulled once):
- **A. no-patch** prediction → expect **unresolved**.
- **B. official gold-patch** prediction (`case["patch"]`) → expect **resolved**.

Grading is the **benchmark-specific** path: an ephemeral pinned checkout of `swebench_memory.harness.run_evaluation`
(hashes verified vs `scb_official_evaluator_lock.json`) against the official image
`jiayuanz3/swecontextbench:<tag>`. No `swebench.harness.run_evaluation`. No synthesized `image` field. No model
call, no secret, paid API = 0. Infrastructure errors are recorded separately from model (unresolved) results.

Required to pass: no-patch unresolved 12/12; gold resolved 12/12; infra failures 0; image failures 0; case
mismatch 0; result completeness 24/24; official test modification by us 0.

## Status — PENDING EXECUTION APPROVAL (not yet run)
This smoke **executes the pinned upstream evaluator**, whose code has **no explicit license**
(`R22_UPSTREAM_RIGHTS_STATUS.md`), and requires a Docker host (the credential-free authoring environment has no
Docker daemon). It is therefore **dispatch-only and gated** on `confirm_exec_approved=EXEC_APPROVED` +
`R22_SCB_UPSTREAM_EXEC_APPROVED=1`. Until that approval is given the workflow runs the approval gate and stops
**without executing upstream code**.

All prerequisites are verified and frozen:
- evaluator exists + pinned + hash-locked (§2);
- cases 40/40, core-row equivalent 40/40 (§3);
- images 40/40 `linux/amd64` with digests (§4);
- adapter + driver + workflow committed, and the credential-free real-path harness (`scripts/r22_scb_real_path.py`)
  is wired to this same grader.

On approval, dispatch `ci-r22-scb-grader-smoke.yml` with `EXEC_APPROVED`; the 24 cells (12×{gold,no-patch}) then
populate this report and flip the endpoint to `R22_OFFICIAL_SCB_GRADER_READY_AWAITING_PAID_APPROVAL`.
