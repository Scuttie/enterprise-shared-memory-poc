# P5.1 — permanent closure and claim boundary

**P5.1 is closed and immutable.** `EXP_P5_1_CAL` (plan hash `4eb030a9f6f18f6d`) and its committed results
(`artifacts/experiments/p5_1/results/calibration_results.json`) are frozen. No P5.1 task, threshold, prompt,
result, or manifest may be modified by P5.2. `tests/unit/test_p5_1_immutable.py` locks the content hashes of
every P5.1 frozen file + the calibration results and fails if any is changed.

## What P5.1 established (and what it did NOT)
- The frozen calibration executed in full against real `solar-pro2-251215` through the service path
  (HTTP → durable job → separate worker → governed retrieval → Solar → hidden-test grading). This is a
  **service-path + instrument-sensitivity** result.
- **Gates G2 (dynamic range) and G5 (irrelevant abstention) FAILED** → STOP-CALIBRATION.
- The P5.1 **held-out main was NOT run.**

## Claim boundary (binding)
- **M3−M0 = +1.00 is calibration SENSITIVITY (a positive control), not efficacy.** It shows the tasks are
  un-solvable without the injected memory and solvable with it; it does not measure real-world coding benefit.
- **M3−M2 = 0** → **no governed-format advantage was observed** (the typed governed contract did not beat the
  ungoverned summary on this instrument). M3−M0 must never be presented as evidence for the contract format.
- **M4−M3 = 0** → **retrieval headroom was not estimable** (oracle equalled similarity because each cell held
  a single memory).
- **G4 in P5.1 was ISOLATED relevant-retrieval success, not competitive precision.** Each experiment cell was
  seeded in its own org with exactly one memory, so retrieval had no competing pool and no abstention was ever
  exercised. G4 must not be cited as retrieval precision.
- **S1 (irrelevant) and S4 (wrong-pattern) adoption remains PENDING patch-level forensics.** Aggregate: both
  were injected 16/16 with Pass@1 = 0/16, but Pass@1 = 0 is not an adoption classification. The P5.1 per-job
  raw responses and patches were held only in the ephemeral CI PostgreSQL + MinIO and were not persisted, so
  patch-level adoption cannot be classified from P5.1 artifacts without new Solar calls (forbidden). P5.2
  persists raw + applied patches for every executable S1/S4 cell (gate G7) so P5.2 adoption is artifact-verified.

## Why the gates failed (design, not a code defect)
- **G2:** the P5.1 conventions are un-recoverable from the incomplete public test, so a memory-less model
  floors (M0 = 0 in every domain) — a floor effect, not a bug.
- **G5:** cell-isolated singleton banks + no relevance-abstention floor mean the single seeded memory is always
  injected (irrelevant rate 1.00). This is a retrieval-design gap, not a leakage: cross-user private, expired,
  out-of-scope, and no-memory injection were all 0, and DB `injected` equalled the backend payload 100%.

No correctness defect that would invalidate P5.1's own (sensitivity/safety) interpretation was found; the STOP
was a legitimate design-calibration outcome. P5.2 rebuilds the instrument (partial baseline solvability) and
the retrieval (competitive pool + frozen abstention rule) under new experiment ids.
