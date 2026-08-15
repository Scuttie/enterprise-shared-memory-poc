# R3 §3 — Offline Actionability Forensics (R1/R2 persisted evidence, NO new model calls)

Purpose (§3): **define candidate representations** for R3 from where R1/R2 memory failed to convert into correct
code. This does **not** select a winning representation from old benchmark accuracy. Input: the frozen R2 main
raw job records (`artifacts/bigcode_r2/results/main_raw.*.json`) + R2 source-bank AST signatures. Classifier:
`experiments/patch_forensics.py`. Output JSON: `artifacts/actionable_memory_r3/r1_r2_forensics.json`.
(Alias `reports/R3_R1_R2_ACTIONABILITY_FORENSICS.md` points here per the §3 filename.)

## What is offline-recoverable vs not (honest boundary)
Persisted by R2 and usable: generated/applied target code, source operation/API/import/control-flow tags,
injection truth (DB), exec/grader outcome. **Not persisted** by R2 (so we do NOT guess them): the raw model
response, the target's **first failing test**, and the target's expected interface. Gap classes that require
those are reported as *requires-online-evidence*; R3 WILL persist the first-failing-test (§19) so they can be
populated in the confirmatory run.

## Gap taxonomy over failing memory-arm jobs (M2 = relevant, F1_PLAIN)
| A-code | offline? | M2 count | motivates representation |
|---|---|---|---|
| A1 MISSING_API_DETAIL | yes | 0 | B1 API_OPERATION_CARD |
| A2 MISSING_PRECONDITION | **no** (needs failing test) | — | B1/B6 preconditions |
| A3 WRONG_APPLICABILITY_DECISION | **no** | — | B2 CONDITION_ACTION_TABLE / B7 |
| A4 PROCEDURE_NOT_REALISED | yes | 0 | B3 PROCEDURAL_PSEUDOCODE |
| A5 TARGET_INTERFACE_MISMATCH | yes | 0 | B4 AST_EDIT / B5 diff |
| A6 SOURCE_NAMES_OR_CONSTANTS_COPIED | yes | **52** | B4/B5 placeholder edit (forbid copy) |
| A7 PROPERTY_NOT_VERIFIED | **no** | — | B6 EXECUTABLE_PROPERTY_SPEC |
| A8 COUNTEREXAMPLE_IGNORED | **no** | — | B7 POSITIVE_NEGATIVE_CONTRAST |
| A9 UNRELATED_MODEL_ERROR | yes | **229** | (not representation-addressable) |
| A10 PARSER_OR_EVALUATOR | yes | 9 | (engineering, not representation) |
| A11 UNCLASSIFIED | yes | 0 | (insufficient evidence) |

## Cross-arm buckets (475 targets)
- **Gains** (memory passes, M0 fails): M1 29, M2 30, M3 29, M5 35, M7 35.
- **Losses** (M0 passes, memory fails): M1 18, M2 32, M3 21, M5 31, M7 34. Gains≈losses everywhere → memory
  reshuffles which tasks pass rather than adding net solutions (the mechanism behind R2's flat Pass@1).
- **Adoption-present-but-failed** (injected job whose patch adopted a source element yet still failed): **M2 52,
  M7 59, M1 41, M3 6**. The shuffled control M3 is near-zero (as designed — irrelevant content isn't adopted);
  the relevant arms adopt frequently and **still fail**.
- **Plain vs governed, same source** (M2 vs M7): both_pass 160, plain_only 25, governed_only 28, both_fail 262
  → symmetric (governed +3 of 475), confirming R2's *no governed-format advantage*.

## The finding that defines R3's ladder
The dominant *memory-related* failure is **A6: the model adopts source API calls / operations and runs, but the
transferred content does not realise as correct target code** (M2: 52 such failures; M7: 59). This is decisive
for representation design:

1. The bottleneck is **not** retrieval or the model ignoring memory — relevant content IS being read and
   adopted. The bottleneck is **realisation**: converting an adopted technique into code that satisfies the
   target's interface and semantics.
2. **Prose and governance do not address realisation** (plain≈governed). So the R3 ladder must move *past* prose
   toward representations that constrain realisation: procedural (B3), executable-constraint (B6), and
   code-edit (B4/B5) — with a matched decoder that forces applicability-check → map-to-target → verify.
3. Classes that a *plain lesson* structurally cannot prevent — wrong applicability (A3), unverified properties
   (A7), ignored counterexamples (A8) — motivate the **decision/constraint** rungs (B2 condition-action, B6
   property spec, B7 positive/negative contrast). R2 could not measure these because it did not persist the
   first-failing-test; **R3 persists it** and can therefore test whether these representations close the gap.

**Conclusion:** candidate bundles B0–B9 are justified by observed R1/R2 failure modes (chiefly adopt-but-don't-
realise), not by any accuracy ranking. Selection among them is deferred to the frozen R3 discovery rule (§14),
computed on the independent DS-1000 discovery split.
