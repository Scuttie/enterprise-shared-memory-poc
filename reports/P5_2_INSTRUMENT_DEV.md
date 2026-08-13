# P5.2 — instrument-dev pilot (EXP_P5_2_INSTRUMENT_DEV)

Development evidence only (8 dev families, 2/domain = 1 prior_aligned + 1 prior_conflict; disjoint from
calibration/main). Ran through the REAL service path against `solar-pro2-251215` (72 cells): authenticated
HTTP → durable job → separate worker → server-assigned arm + **competitive retrieval + frozen abstention** →
Solar → hidden-test grading → durable evidence + raw/applied patch.

## Results (Pass@1 / Exec@1, n=8)
| Arm | Pass@1 | Exec@1 |
|-----|-------:|-------:|
| M0 NO_MEMORY | 0.500 | 1.000 |
| M1 PRIVATE | 0.500 | 1.000 |
| M2 SHARED_UNGOVERNED | 0.750 | 1.000 |
| M3 SHARED_GOVERNED | 0.875 | 1.000 |
| M4 ORACLE | 1.000 | 1.000 |
| S1 IRRELEVANT | 0.500 | 1.000 |
| S2 EXPIRED | 0.500 | 1.000 |
| S3 OUT_OF_SCOPE | 0.500 | 1.000 |
| S4 WRONG_PATTERN | 0.000 | 1.000 |

## Purpose checks (§6)
- **M0 not forced to zero:** M0 = 0.500 (the prior_aligned families are memory-less-solvable). ✔
- **M4 not below ceiling:** M4 = 1.000. ✔
- **Competitive retrieval through the real path:** relevant-query precision 1.00, recall 1.00, no-match
  specificity 1.00, S1 false-injection 0.00. ✔ (This is genuine competitive precision, not P5.1's singleton.)
- **Critical safety:** cross-user private injection 0, expired injected 0 (S2 gated), out-of-scope injected 0
  (S3 gated), no-memory injected 0, DB injected == payload 100%. ✔
- **Adoption auditability (G7):** raw+applied patch persisted for 100% of executable S1/S4 cells; classifier
  coverage 1.00. S4 = **EXACT_WRONG_DEFAULT_ADOPTION** for all 8 (the model adopts the stored wrong edge
  multiplier → fails), i.e. artifact-verified negative transfer; S1 = mix of NO_RULE_USE /
  EXACT_STORED_RULE_ADOPTION (S1 abstains, so behaves like M0). ✔
- Task serialization + hidden graders exercised end-to-end (Exec@1 = 1.00 everywhere). ✔

G1/G2/G4/G5/G6/G7 pass on the dev split; G3 "fails" only because its `>=12/16 families differ` threshold is a
calibration-size rule applied to the 8-family dev split (M4−M0 = 0.50 ≥ 0.25 holds). This is expected and does
not gate the pilot.

## Global instrument adjustment (§6)
**NO ADJUSTMENT.** The pilot confirms a nonzero in-band M0, a ceiling M4, perfect competitive retrieval, clean
critical safety, and a working adoption classifier. No task-tier change is warranted. The calibration freeze
uses the instrument exactly as piloted.
