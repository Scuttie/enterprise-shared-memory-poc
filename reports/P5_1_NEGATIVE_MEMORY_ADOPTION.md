# P5.1 — negative-memory (S1 / S4) adoption forensics

## Aggregate (persisted)
| Arm | n | injected | Exec@1 | Pass@1 |
|-----|---|---------:|-------:|-------:|
| S1 IRRELEVANT_GOVERNED | 16 | 16 | 1.00 | 0.00 |
| S4 WRONG_REUSABLE_PATTERN | 16 | 16 | 1.00 | 0.00 |

Both negative-memory arms were injected in every cell (the P5.1 cell-isolated singleton bank forces injection),
executed cleanly (Exec@1 = 1.00), and never produced a passing solution (Pass@1 = 0).

## Adoption classification: NOT POSSIBLE from persisted P5.1 artifacts
Per the P5.2 rule, **Pass@1 = 0 is not an adoption classification**. Classifying each S1/S4 patch as
`NO_RULE_USE` / `PARTIAL_RULE_USE` / `EXACT_STORED_RULE_ADOPTION` / `EXACT_WRONG_DEFAULT_ADOPTION` /
`UNRELATED_IMPLEMENTATION_ERROR` / `MALFORMED`, and programmatically testing whether an S4 patch implements the
stored wrong prior-default formula `D`, both require the **raw and applied patch text**. Those were held only in
the ephemeral CI store and were not persisted, and re-running Solar to recover them is forbidden.

**Therefore P5.1 S1/S4 adoption is UNCLASSIFIED (evidence unavailable), not "no adoption".** The only defensible
statement is: the negative memory did not rescue tasks that are unsolvable without the correct convention.

## What can be said structurally
- S4's wrong-pattern memory carries the prior-default formula `D` (e.g. `value ** 1` for schema); if the model
  adopted it, the output would equal the prior baseline (which fails the hidden test, since C ≠ D). This is
  consistent with Pass@1 = 0 but does not distinguish adoption from unrelated error without the patch.
- S1's irrelevant memory describes an unrelated convention; Pass@1 = 0 is consistent with either abstention-in-
  spirit (ignored) or mild degradation, again indistinguishable without the patch.

## Implication for P5.2
Gate **G7** makes adoption auditability mandatory: the P5.2 runner persists the raw + applied patch for 100% of
executable S1/S4 cells, and a programmatic adoption classifier (including a direct test of whether the patch
implements the stored wrong `D`) runs over all of them, so P5.2 negative-memory adoption is artifact-verified.
