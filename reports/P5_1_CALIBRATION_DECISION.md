# P5.1 — Calibration decision: STOP-CALIBRATION

## Decision
**STOP-CALIBRATION.** The frozen calibration executed in full (144 cells, real `solar-pro2-251215`, through
the service API → durable job → separate worker path). Two preregistered hard gates — **G2 (dynamic range)**
and **G5 (irrelevant abstention)** — are not met. Per the frozen stop rule (§13/§18), the held-out **main
experiment is NOT run**, no families are replaced, and **no threshold or task is edited after seeing results**.
A required redesign must start a new experiment id with a new preregistration.

This is calibration outcome **A (CALIBRATION FAIL)**: all correctness/CI gates pass, the frozen calibration
executes, a preregistered gate fails, main is not run, and this honest report is committed.

## Why each failing gate failed (and the required redesign)
### G2 — dynamic range (M0 Pass@1 ∈ [0.15, 0.75] in ≥3/4 domains)
Observed M0 Pass@1 = 0.00 in all four domains. The frozen conventions (formula shape + constant `C ≠ D`) are
genuinely un-recoverable from the incomplete public test, so a memory-less model floors. The primary lift is
therefore real and maximal (M3−M0 = +1.00) but rests against a floor, which the dynamic-range gate is designed
to reject.
**Redesign (new experiment id):** introduce partial baseline solvability — e.g. a fraction of families whose
convention is plausibly guessable, or public tests that pin a second (still C-independent) case that narrows
the formula family — targeting M0 Pass@1 ≈ 0.2–0.5 while keeping M3 high.

### G5 — irrelevant-memory abstention (irrelevant injected ≤ 0.20)
Observed irrelevant (S1) injected rate = 1.00. Each cell is seeded in isolation with exactly one memory and
the governed retrieval has **no relevance-score abstention floor**, so the single available (irrelevant)
memory is always injected. Note the *critical* safety signals are all clean (cross-user private injection = 0,
expired injected = 0, out-of-scope injected = 0, no-memory arm injects 0), and the irrelevant memory did not
cause adoption (S1 Pass@1 = 0).
**Redesign:** add a relevance/similarity abstention floor to injection, and/or evaluate S1 against a memory
pool that also contains the correct memory (measuring mis-ranking rather than isolated injection), so the
abstention gate is well-posed.

## What the calibration DID establish (kept for the record; not a promotion claim)
- The full authenticated HTTP → durable job → **separate worker** → governed retrieval → PostgreSQL canonical
  reload → real-Solar coding backend → hidden-test grading → durable evidence path works end to end.
- Governed cross-user memory produces a large, clean lift (M3−M0 = +1.00; McNemar p ≈ 3e-5) on this
  instrument; private own-memory nearly matches it (M1−M0 = +0.938).
- Every critical safety invariant held under a real model: no cross-user private leakage; expired and
  out-of-scope governed memory rejected and never injected; no-memory arm injected nothing; DB `injected`
  equalled the backend payload byte-for-byte; source_user ≠ target_user for every cross-user arm.

## Consequences
- **Main experiment: not run.** No efficacy claim is made from calibration.
- **No P6.** No promotion/review or K8s sandbox work.
- The instrument, gates, and manifests remain frozen under experiment id `EXP_P5_1_CAL`
  (plan hash `4eb030a9f6f18f6d`); the results are `artifacts/experiments/p5_1/results/calibration_results.json`.
