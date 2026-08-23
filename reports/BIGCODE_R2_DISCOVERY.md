# BigCode-R2 Discovery (§7/§8) — DESCRIPTIVE, selection by predeclared rule

Ran the 15-cell fractional design over the 120 MEMORY_DISCOVERY targets in 3 parallel chunks (production
embedder, official grader). DESCRIPTIVE only — no confirmatory p-value.

## Selected (predeclared §8 rule, frozen in selected_policy.json)
**Format F1_PLAIN_LESSON, policy P1_PROD_TOP1.** The rule (committed before discovery) maximises
Pass@1(relevant-fixed) − Pass@1(shuffled-matched) per format; F1 had the largest combined effect (+0.258),
alone within 0.01 of the best, and passed the loss/token tie-breaks. Hard safety passed (target/test leakage 0,
cross-user private leakage 0, invalid injection 0).

| format | relevant P0 | shuffled P4 | rel−shuf |
|---|---|---|---|
| F0_MINIMAL_HINT | 0.442 | 0.208 | +0.233 |
| **F1_PLAIN_LESSON** | 0.392 | 0.133 | **+0.258** |
| F2_API_CARD | 0.367 | 0.167 | +0.200 |
| F3_GOVERNED_COMPACT | 0.283 | 0.167 | +0.117 |
| F4_RAW_VERIFIED_TRACE | 0.383 | 0.167 | +0.217 |

## Honest limitation (does NOT affect the confirmatory main)
At ~150–160 s/job (heavy BigCodeBench grading), the runner's **cell-ordered submission** starved later-submitted
cells at each chunk's deadline: relevant (P0) cells executed 0.82–0.98, but shuffled (P4) executed only
~0.47–0.56 and three retrieval cells (F2/F3@P1, F2@P2) executed ~0. So the shuffled Pass@1 is deflated
(pending scored 0) and the rel−shuf magnitudes are inflated; the format RANKING is only weakly separated
(F0/F1/F4 within ~0.04). The selection is the mechanical output of the frozen rule on the available data.
**This is a descriptive selection only** — the confirmatory main independently tests relevance (E1: M2 vs M3)
and deployability (E2: M4 vs M0) with INTERLEAVED submission so paired arms complete evenly. Discovery is not
re-run for a cleaner selection because that would not change the confirmatory design and the rule is frozen.
