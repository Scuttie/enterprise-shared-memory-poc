# BigCode-R2 Source Bank (§5)

Built by running the **300 SOURCE_POOL** tasks through the real service path (HTTP → durable job → separate
worker → NO memory → Solar `solar-pro2-251215` (instruct backend) → official BigCodeBench grader) inside the
eval image. One org, **24 source users** (round-robin assignment), `source_user != target_user` by
construction (target sets use a disjoint target-user pool).

## USER_SUCCESS_BANK (deployable) — primary

| | |
|---|---|
| Source tasks attempted | 300 |
| **Verified (passed official tests)** | **134 (44.7%)** |
| Distinct source users represented | 24 |
| Memory content | the source user's OWN verified solve (the applied whole-file patch) |
| Per-fact signature | imports / called APIs / operations / control-flow (AST of the verified solve) |

**This 44.7% is also the first large-sample NO-MEMORY Pass@1 on BigCodeBench-Instruct for this model.** It sits
squarely in the C3 dynamic-range band [0.10, 0.90] — the model is neither floored nor ceilinged, so there is
real room for memory to help or hurt. (An earlier run returned 0/300 due to a prompt-wiring bug — the P52
backend never included the NL instruction; fixed by the instruction-driven backend, confirmed by the jump to
44.7%.)

## GOLD_VERIFIED_BANK (diagnostic upper bound only)

300 facts derived from the OFFICIAL reference solutions (`complete_prompt + canonical_solution`), used ONLY
for: (a) evaluator-side relevance labels (§6.1), (b) the true-relevance oracle arm (M2), (c) source-fact
verification. **Never presented as deployable user experience**, never placed in a target prompt.

## Persisted

`artifacts/bigcode_r2/source_bank.json` (USER_SUCCESS facts incl. verified_code + tags + owner_user) and
`gold_bank.json` (reference signatures). These freeze the memory content for discovery / calibration / main.
No target reference solution or test is included in either bank's target-facing use.
