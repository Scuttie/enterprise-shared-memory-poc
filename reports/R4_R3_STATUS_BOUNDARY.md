# R4 §1 — R3 Status Boundary (correction carried into R4)

Exact status of REALBENCH-R3, to prevent overclaiming as R4 begins:

- **R3 service / source-bank / injection pipeline = PASS.** DS-1000 official evaluator reproduced 100%
  (1000/1000); multi-user source bank 183/200 verified; oracle injection audited to **82/82 per arm** after
  fixing a two-part bug (top-k-filter oracle → direct-load; RLS tenant context).
- **R3 discovery representation result = injection-corrected DESCRIPTIVE NULL under near-ceiling conditions.**
  Best RelevantBundleLift = +0.008 (1 task of 82, noise); no B0–B9 bundle beats the shuffled-matched baseline.
- **R3 confirmatory representation effect = UNRESOLVED.** The held-out main was **not run**: the no-memory
  calibration Pass@1 = **0.98** (discovery 0.925), so the preregistered §16 G3 dynamic-range gate fired a §0-C
  CALIBRATION STOP.
- **The next study (R4) moves to a harder, repository-level, skill-relevant benchmark.**

Explicitly NOT claimed (per §1):
- ✗ "all memory representations are ineffective" — the instrument was near-ceiling; the effect is unresolved.
- ✗ "B5 generalized-diff is the winning format" — B5 was selected only by the efficiency tie-break among
  *null-lift* bundles.
- ✗ "DS-1000 proves memory does not help" — DS-1000 at 0.925–0.98 base rate has no headroom to measure it.

R1 (MBPP+, small n.s.), R2 (BigCodeBench confirmatory null), R3 (DS-1000 injection-audited descriptive null +
calibration stop) are all frozen. P6 not started.
