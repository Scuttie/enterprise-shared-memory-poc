# P5.2 — Calibration results (EXP_P5_2_CAL)

Real `solar-pro2-251215` via the service path (HTTP → durable job → separate worker → server-assigned arm +
competitive retrieval + frozen abstention → Solar → hidden-test grading → durable evidence + raw/applied
patch). 144 cells (16 families × 9 arms). Frozen plan hash `93ce321a7984a164` (= `freeze.json`).

## Arm results (Pass@1 / Exec@1)
| Arm | Pass@1 | Exec@1 |
|-----|-------:|-------:|
| M0 NO_MEMORY | 0.375 | 1.000 |
| M1 PRIVATE | 0.250 | 1.000 |
| M2 SHARED_UNGOVERNED | 0.875 | 1.000 |
| M3 SHARED_GOVERNED | 0.688 | 1.000 |
| M4 ORACLE | 0.750 | 1.000 |
| S1 IRRELEVANT | 0.188 | 1.000 |
| S2 EXPIRED | 0.188 | 1.000 |
| S3 OUT_OF_SCOPE | 0.250 | 1.000 |
| S4 WRONG_PATTERN | 0.062 | 1.000 |

## Strata (M0 / M3 Pass@1)
prior_aligned 1.00 / 1.00 · context_inferable 0.50 / 0.50 · prior_conflict 0.00 / 0.625. **M0 = 0.375 is
in-band** (the P5.1 floor is fixed): prior_aligned solvable without memory, prior_conflict needs it.

## Primary (descriptive — calibration failed, so NOT claimed)
CrossUserLift M3−M0 = **+0.312**, family-cluster bootstrap 95% CI **[0.000, 0.562]**, exact McNemar b=6 c=1
p=0.125. Secondary: M1−M0 = −0.125, **M3−M2 = −0.188** (no governed-format advantage; the ungoverned summary
was not beaten), M4−M3 = +0.062.

## Gates
| Gate | Result | Detail |
|------|--------|--------|
| G1 executability | PASS | Exec@1 M0=1.00, M4=1.00; malformed 0 |
| G2 dynamic range | PASS | M0∈[0.15,0.75] and M4−M0≥0.25 in 3/4 domains (config M4=0.0 is the exception) |
| G3 memory necessity | PASS | M4−M0 = +0.375; 12/16 families differ |
| G4 competitive retrieval | **FAIL** | precision 1.00, **recall 0.875 (<0.90)**, no-match specificity 0.875, S1 false-injection 0.125; 2/16 M3 relevant abstained near the τ boundary |
| G5 critical safety | **FAIL (measure)** | cross-user private 0, **no gated memory injected** (S2/S3 injected items were near-miss DECOYS: relevant_injected=0 for all), no-memory injected 0, DB injected==payload 100%. The frozen G5 counts ANY S2/S3 injection → 2+2 decoy false-injections fail it (same root as G4) |
| G6 instrument consistency | PASS | source≠target every cross arm; calibration/main disjoint |
| G7 adoption auditability | PASS | raw+applied patch for 100% executable S1/S4; classifier coverage 1.00 |

## Adoption (artifact-verified; G7)
S4 (wrong-pattern): **EXACT_WRONG_DEFAULT_ADOPTION 12/16** (the model implements the stored wrong edge
multiplier → negative transfer), + 2 UNRELATED_IMPLEMENTATION_ERROR, 1 EXACT_STORED_RULE_ADOPTION, 1
NO_RULE_USE. S1 (irrelevant, abstains): 8 NO_RULE_USE, 5 UNRELATED_IMPLEMENTATION_ERROR, 3
EXACT_STORED_RULE_ADOPTION. This is patch-level adoption evidence, not inferred from Pass@1.

## Root cause of the failures
G4 and G5 share one cause: the deterministic bag-of-tokens embedder separates relevant/near-miss/irrelevant
perfectly on the representative retrieval-dev split and the 8-family instrument-dev pilot, but has ~12%
ranking variance at the 16-family calibration scale near the frozen τ_abs=0.80 boundary — so 2/16 M3 relevant
memories fall just below threshold (abstain) and 4 near-miss decoys in S2/S3 cells rise just above it. Critical
leakage safety (cross-user private = 0; expired/out-of-scope memory rejected before injection) held throughout.
