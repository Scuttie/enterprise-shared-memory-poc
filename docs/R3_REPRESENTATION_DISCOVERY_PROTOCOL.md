# R3 Representation Discovery Protocol (§12–§14, frozen before discovery calls)

Discovery finds which memory-representation bundle best converts a fixed, verified, relevant source into correct
DS-1000 target code. **Discovery is descriptive — no p-values are used for policy selection.** It runs ONLY on
the frozen `REPRESENTATION_DISCOVERY` split (120 tasks; `split_hash e16bfb852f7395cb`).

## Invariant (§8/§11)
For every representation comparison: **same target + same evaluator-frozen relevant source ID + different
execution-view renderer**. The relevant source ID is selected BEFORE rendering and is identical across B0–B9.
Retrieval projection (source selection) and execution view (rendered memory) are permanently separate; each
bundle = representation renderer + matched decoder, budget-fit to exactly 220 tokens under cl100k_base (§10).

## Arms (§12)
D0 NO_MEMORY · D1 SHUFFLED_MATCHED (baseline bundle) · D2 B0_PLAIN · D3 B1_API_CARD · D4 B2_CONDITION_ACTION ·
D5 B3_PROCEDURAL · D6 B4_AST_EDIT · D7 B5_DIFF_TEMPLATE · D8 B6_PROPERTY_SPEC · D9 B7_POS_NEG_CONTRAST ·
D10 B8_HYBRID · D11 B9_RAW_TRACE_220. All relevant-format arms use the SAME relevant source ID; the shuffled
control is a frozen derangement (same library/domain, matched source frequency + injection indicator).

## Primary discovery quantity (per eligible bundle)
`RelevantBundleLift = Pass@1(relevant bundle) − Pass@1(shuffled-matched, same bundle)`. Also recorded per bundle:
no-memory delta, positive/negative transfer, exact source-pattern adoption, malformed rate, token count, latency,
abstention/refusal, interface-violation rate, official-grader result.

## Matched-decoder ablation (§13)
On a frozen 40-task subset disjoint from the main discovery subset, for the three best bundles (by preliminary
non-inferential Pass@1): {representation + matched decoder} vs {representation + generic decoder} vs {plain
lesson + candidate decoder}. Descriptive only; does NOT override the frozen selection rule.

## Predeclared selection rule (§14, lexicographic — NOT min-p)
1. **HARD SAFETY** (all must be 0): target-solution leakage, hidden-test leakage, cross-user private leakage,
   invalid-state injection, source-identifier-copying violations. (B9 eligible only if truncation ≤ 0.02 and no
   source leakage.)
2. **ACTIONABILITY**: maximise RelevantBundleLift.
3. **ROBUSTNESS**: among bundles within 0.01 of the best lift, minimise memory-induced loss rate.
4. **CODE REALISATION**: among those within 0.01, minimise interface + signature + parser + source-copy rate.
5. **EFFICIENCY**: among those within 0.01, minimise mean injected tokens.
6. **DETERMINISTIC TIE-BREAK**: fixed order B1, B4, B6, B7, B8, B3, B2, B5, B0, B9.

Implemented in `experiments/actionable_memory_r3/analysis.py::select_policy` (unit-tested). The full calculation
is persisted to `artifacts/actionable_memory_r3/selected_policy.json`; once selected, the policy cannot change.
Outputs: `reports/R3_REPRESENTATION_DISCOVERY.md`, `reports/R3_MATCHED_DECODER_ABLATION.md`.

## Integrity
Server-owned arm assignment; production embedder (all-MiniLM-L6-v2, 384-d) for retrieval; official DS-1000
grader (reproduced 100%). The model only ever sees the rendered execution view; relevance labels are
evaluator-side. A null/negative discovery result is reported honestly and does not, by itself, force any
particular selection beyond the frozen rule (executable/edit bundles must at least match plain, else §0-B
DISCOVERY STOP).
