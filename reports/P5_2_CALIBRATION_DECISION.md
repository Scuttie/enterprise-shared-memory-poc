# P5.2 — Calibration decision: STOP-P5.2-CALIBRATION

## Decision
**STOP-P5.2-CALIBRATION** (valid endpoint **B**). The new frozen calibration `EXP_P5_2_CAL` (plan hash
`93ce321a7984a164`) executed in full against real `solar-pro2-251215` through the service path, and two
preregistered hard gates failed: **G4** (competitive retrieval — relevant recall 0.875 < 0.90; relevant-missing
0.125 > 0.10) and **G5** (as frozen — 2 S2 + 2 S3 cells injected a near-miss decoy). Per the frozen stop rule
(§8) the held-out **main is NOT run**, no families are replaced, **no threshold is retuned after the freeze**,
and **no P6**. A required redesign starts a new experiment id + new preregistration.

## What the calibration DID establish (kept for the record; not an efficacy claim)
Relative to the failed P5.1 instrument, P5.2 fixed the two P5.1 defects it targeted:
- **Dynamic range (P5.1 G2 floor) is fixed:** M0 = 0.375, in [0.15, 0.75], via the prior_aligned /
  context_inferable / prior_conflict strata (M0 strata 1.00 / 0.50 / 0.00). G2 passes.
- **Competitive retrieval + abstention (P5.1 G5 singleton) is real:** every query searched a bank of 1
  relevant + 3 same-domain near-miss + 4 cross-domain irrelevant; relevant precision = 1.00, and — critically
  — the expired (S2) and out-of-scope (S3) relevant memories were **rejected before injection** in every cell
  (relevant_injected = 0), and cross-user private injection = 0. This is genuine competitive precision, not a
  cell-isolated singleton.
- **Adoption is artifact-verified (G7):** raw+applied patches persisted for 100% of executable S1/S4 cells; a
  programmatic classifier shows S4 = EXACT_WRONG_DEFAULT_ADOPTION for 12/16 (negative transfer from a stored
  wrong rule), not inferred from Pass@1.

## Why it still stops
The single remaining weakness is retrieval-ranking robustness at scale: the deterministic embedder's ~12%
variance at 16 families pushes 2 relevant memories below, and 4 near-miss decoys above, the frozen τ_abs=0.80
margin — failing G4 recall and the (any-injection) G5 measure. This is not a leakage or plumbing defect; it is
a retrieval-separation limitation of the credential-free test embedder.

## Required redesign (new experiment id, new preregistration)
- Use a retrieval representation with a larger relevant/decoy margin at scale (e.g. a stronger embedding or a
  wider tag signal), and select τ on a same-scale representative dev split, so recall ≥ 0.90 and decoy
  false-injection ≤ 0.20 hold at 16+ families.
- Separate the G5 measure into "gated-memory injection" (which held at 0 here) vs "decoy false-injection"
  (the S1/abstention metric), so critical-safety and retrieval-robustness are gated independently.

## Consequences
- **Main experiment: not run.** No efficacy claim (the primary M3−M0 = +0.31 is descriptive; M3−M2 = −0.19,
  so no governed-format advantage was observed).
- **No P6.** P5.1 remains permanently frozen and untouched (`tests/unit/test_p5_1_immutable.py` green).
