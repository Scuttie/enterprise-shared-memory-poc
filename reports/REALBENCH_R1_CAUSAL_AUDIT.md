# REALBENCH-R1 Causal Audit (§1.2 / §23)

An audit of what the frozen REALBENCH-R1 result can and cannot causally support, and how REALBENCH-R2 closes
each gap. R1 remains a valid *actual-benchmark* result (MBPP+ Pass@1 through the production path); this audit
only bounds the *causal* interpretation.

## Confounds present in REALBENCH-R1

| # | Confound | Consequence | R2 remedy |
|---|---|---|---|
| A | **No relevance control.** Any shared summary was injected; there was no matched-but-irrelevant ("shuffled") arm and no evaluator relevance oracle. | A lift could be generic "extra context" rather than *relevant* memory. | R1.1 **D5 SHUFFLED_MATCHED** / **D8 TRUE_ORACLE_RELEVANT**; BigCode primary **E1: M2 (relevant) vs M3 (shuffled-matched)**. |
| B | **No real multi-user transfer.** One synthetic org+user per arm; source≠target users never modelled. | R1 cannot claim cross-user knowledge transfer. | R2 §5: one org, ≥24 users, `source_user != target_user` enforced; USER_SUCCESS_BANK from real source solves. |
| C | **Non-production retrieval.** `DeterministicTestEmbedder`, not the pinned production embedder. | R1 retrieval/abstention numbers are not deployable. | R2 §6.2: pinned production embedder + Qdrant/Mem0 path; CI forbids `DeterministicTestEmbedder` in paid benchmark. |
| D | **Format confounded with selection & wording.** R3−R2≈0; governed vs plain also differed in retrieved content. | R1 cannot attribute any effect to the contract *format*. | R2 §6.3: freeze source IDs on a **neutral** projection, then render plain/governed from the **same** IDs (M6 vs M7). |
| E | **Heuristic patch labels.** Every changed failing patch called adoption; patches not persisted. | R1 "transfer" is not adoption evidence. | R2 §1.3 evidence-based classifier; patches persisted in R1.1/R2. |
| F | **Gate assertions hard-coded.** C4/C5 `pass=True`. | Gates asserted, not computed. | R2 §1.4 run-local predicates; the computed values happen to hold for R1. |

## What R1 DID establish (unchanged)

- On 120 held-out MBPP+ targets, `solar-pro2-251215` (no memory) solves **57.5%** through the real service
  path under the official EvalPlus grader.
- Adding a shared memory produces at most a **small, directional, non-significant** lift; governed format
  adds essentially nothing over a plain summary. This is a legitimate null-ish actual-benchmark finding and
  is **not** overturned — R2 tests whether a *relevant, production-retrieved* memory does better under a
  properly powered, preregistered design.

## Diagnostic reuse rule

The R1 120-target main has been **observed**. Per §2 it may be reused only for **mechanism diagnostics**
(descriptive Pass@1 / adoption / retrieval). **No p-value or CI from R1 or the R1.1 diagnostic may support a
new confirmatory claim.** Confirmatory evidence comes only from the frozen BigCode-R2 500-task main (§10–12)
and, for external validity, SWE-Skills-Bench (§15).
