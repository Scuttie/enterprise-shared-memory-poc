# REALBENCH-R1.1 Diagnostic (§2) — MECHANISM ONLY, NOT CONFIRMATORY

**These numbers are descriptive.** They come from the ALREADY-OBSERVED 120 MBPP+ main targets and carry **no
p-value or confidence interval**. Per §2 and the R1 causal audit, **no result here may support a new
confirmatory claim.** The confirmatory evidence is the frozen BigCode-R2 500-task main (§10–12).

Setup: same HTTP → durable job → separate worker → retrieval → Solar `solar-pro2-251215` → **official MBPP+
grader** path, with the **pinned production embedder** (`all-MiniLM-L6-v2`, 384-d) — never
`DeterministicTestEmbedder`. `cross_user_private_injection = 0`; Exec@1 = 1.000 on every memory arm;
`labels_hash = b2768ab6…` (evaluator relevance labels frozen, source-only, never exposed).

## Pass@1 by diagnostic arm (n=120)

| Arm | Memory | Pass@1 | inject | gains/losses vs D0 |
|---|---|---|---|---|
| D0 | NO_MEMORY | **0.600** | 0.00 | — |
| D1 | RELEVANT_PLAIN | 0.558 | 1.00 | 9 / 14 |
| D2 | RELEVANT_GOVERNED (same source as D1) | 0.617 | 1.00 | 6 / 4 |
| D3 | RELEVANT_API_CARD (same source) | **0.650** | 1.00 | 9 / 3 |
| D4 | RELEVANT_RAW_VERIFIED_TRACE (same source) | 0.600 | 1.00 | 8 / 8 |
| D5 | SHUFFLED_MATCHED (derangement) | 0.625 | 1.00 | 10 / 7 |
| D6 | IRRELEVANT_LENGTH_MATCHED | 0.600 | 1.00 | 9 / 9 |
| D7 | ALWAYS_INJECT_TOP1 (production retriever) | 0.633 | 1.00 | 9 / 5 |
| D8 | TRUE_ORACLE_RELEVANT | = D1 by construction (one physical arm) | | |

## Key descriptive contrasts

| Contrast | Δ Pass@1 |
|---|---|
| **relevant_plain − shuffled_matched (D1 − D5)** | **−0.067** |
| relevant_plain − irrelevant_matched (D1 − D6) | −0.042 |
| relevant_plain − no_memory (D1 − D0) | −0.042 |
| **api_card − plain, same source (D3 − D1)** | **+0.092** |
| governed − plain, same source (D2 − D1) | +0.058 |
| raw_trace − plain, same source (D4 − D1) | +0.042 |
| always_inject_top1 − no_memory (D7 − D0) | +0.033 |

## What the mechanism data suggests (descriptive)

1. **A plain "relevant" lesson is not causally helpful on MBPP+.** D1 (relevant, plain) ≤ D5 (shuffled) ≤ D0
   (no memory). Injecting the truly-relevant source as a plain prose lesson did **not** beat matched-irrelevant
   context — it slightly underperformed no memory. This is exactly the confound R1 could not rule out, now
   made visible: on MBPP+, *relevance alone (plain rendering) is not the active ingredient.*
2. **Representation matters more than relevance here.** Holding the source ID fixed, the **API-card** (+0.092)
   and **governed-compact** (+0.058) renderings clearly beat the plain lesson; the raw verified trace does not
   help (models may over-anchor on a different problem's full code). D3 API_CARD (0.650) is the best arm.
3. **Evidence-based adoption is modest and mostly absent.** Per arm, ~15/120 patches show a genuine
   source-operation/API/control-flow adoption (AST-verified); the large majority of losses are
   `UNRELATED_IMPLEMENTATION_ERROR` (104–113/120) — i.e. NOT memory poisoning. This corrects the R1 heuristic
   that labelled every changed failing patch "adoption": most memory-arm variation is unrelated to the source.

## Consequence for BigCode-R2

- The confirmatory primary (§11 E1) — **relevant vs shuffled-matched** — is the right test: the naive
  expectation (relevant helps) is not supported by the MBPP+ mechanism data, so the causal question is
  genuinely open and worth a powered, preregistered test.
- The format-discovery (§7) should include **API_CARD and GOVERNED_COMPACT** as leading candidates and treat
  **PLAIN and RAW_TRACE** as weak; the discovery selection rule (§8) will choose on
  `relevant − shuffled` on the discovery split, not on this observed set.

Artifacts: `artifacts/realbench_r1/diag/diagnostic_results.json`, `relevance_labels.json` (labels_hash sealed).
