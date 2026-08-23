# P5.1 — Calibration results

**Model:** `solar-pro2-251215` (returned model recorded for every job), via the OpenAI-compatible Upstage
endpoint. **Backend:** whole-file model output → server-side difflib diff. **Path:** authenticated HTTP
`POST /v1/solve` → durable PostgreSQL job → separate worker → server-assigned arm → governed retrieval →
PostgreSQL canonical reload → Solar → patch validation → controlled sandbox graded on the **hidden** test →
durable evidence. 144 cells (16 families × 9 arms), executed in `ci-experiment-calibration`.

**Frozen plan hash:** `4eb030a9f6f18f6d` — identical to `artifacts/experiments/p5_1/freeze.json`, so these
results are from the unmodified frozen plan.

## Arm results (Pass@1 / Exec@1, n=16 each)
| Arm | Pass@1 | Exec@1 |
|-----|-------:|-------:|
| M0 NO_MEMORY | 0.000 | 1.000 |
| M1 PRIVATE_ONLY | 0.938 | 1.000 |
| M2 CROSS_USER_SHARED_UNGOVERNED | 1.000 | 1.000 |
| M3 CROSS_USER_SHARED_GOVERNED | 1.000 | 1.000 |
| M4 ORACLE_GOVERNED | 1.000 | 1.000 |
| S1 IRRELEVANT_GOVERNED | 0.000 | 1.000 |
| S2 EXPIRED_GOVERNED | 0.000 | 1.000 |
| S3 OUT_OF_SCOPE_GOVERNED | 0.000 | 1.000 |
| S4 WRONG_REUSABLE_PATTERN | 0.000 | 1.000 |

## Primary endpoint (descriptive at calibration)
`CrossUserLift = Pass@1(M3) − Pass@1(M0)` paired by family: **mean +1.000**, family-cluster bootstrap 95% CI
**[1.000, 1.000]**, exact paired McNemar **b=16, c=0, p = 3.05e-05**. Secondary: M1−M0 = +0.938, M3−M2 = 0.000,
M4−M3 = 0.000.

## Preregistered gates
| Gate | Result | Detail |
|------|--------|--------|
| G1 executability | **PASS** | Exec@1 M0=1.00, M4=1.00; malformed 0.00 |
| G2 dynamic range | **FAIL** | M0 Pass@1 = 0.00 in all 4 domains — below the [0.15, 0.75] band (floor effect); M4−M0 = 1.00 |
| G3 memory necessity | PASS | M4−M0 = +1.00; 16/16 families' target world differs from the prior (C≠D) |
| G4 retrieval | PASS | M3 relevant-retrieval precision = 1.00; missing-expected 0.00 |
| G5 safety | **FAIL** | irrelevant (S1) injected rate = 1.00 > 0.20 tolerance. **Critical safety clean:** cross-user private injection = 0, expired injected = 0, out-of-scope injected = 0, no-memory injections = 0 |
| G6 instrument consistency | PASS | DB `injected` = backend payload 100%; source_user ≠ target_user for every cross-user arm; calibration/main families disjoint |

**All gates pass: NO.** G2 and G5 fail.

## Interpretation
The service path works end to end against a real coding model, and governed cross-user memory produces a
maximal, unambiguous lift (M3−M0 = +1.00, McNemar p ≈ 3e-5), while every **critical** safety invariant holds
(no cross-user private leakage; expired and out-of-scope governed memory are rejected by the governance gates
and never injected; the no-memory arm injects nothing; the persisted `injected` flag equals the backend
payload byte-for-byte). The wrong-pattern (S4) and irrelevant (S1) arms do not help (Pass@1 = 0), i.e. bad
memory did not rescue the un-solvable-without-memory tasks.

Two preregistered gates are not met:
- **G2 (dynamic range):** the instrument is *too hard without memory* — M0 floors at 0 in every domain, so
  the [0.15, 0.75] baseline band is not established. The large lift is real but sits against a floor.
- **G5 (irrelevant abstention):** the retrieval has no relevance-score abstention floor, and each cell is
  seeded in isolation with a single memory, so the one available (irrelevant) memory is always injected
  (rate 1.00). This is an injection-side gate; it did **not** cause adoption (S1 Pass@1 = 0).
