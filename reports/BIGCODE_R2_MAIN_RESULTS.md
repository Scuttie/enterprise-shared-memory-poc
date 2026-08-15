# BigCode-R2 Confirmatory Main — Results (§10–§12) — MAIN COMPLETE (endpoint C)

**Benchmark:** BigCodeBench-Instruct v0.1.4 (content-hash `98e377a8…`), official grader in the eval image.
**Model:** `solar-pro2-251215`, temp 0, one generation, no repair, max 2048 tok. **Production embedder**
all-MiniLM-L6-v2 (384-d). **Frozen** split_hash `6e075558`, selected memory representation **F1_PLAIN_LESSON**
(discovery §8). One org, 24 source + 24 target users. **Preregistered** (docs/BIGCODE_R2_PREREGISTRATION.md);
fixed-sequence E1→E2, Holm secondary, ITT primary, interleaved submission.

## Run integrity
500 CONFIRMATORY_MAIN targets × 7 physical arms (M6≡M2 under the plain-format selection) run as a 20-chunk
parallel matrix. **19/20 chunks succeeded.** Chunk 8 (25 targets) was lost to **three consecutive GitHub
runner shutdowns** (exit 143 — the runner received a shutdown signal each time after seeding + submitting its
175 jobs and running ~46 min; a deterministic infra preemption of that one long tf-heavy job, **not** a
code/grader fault — the 19 identical sibling chunks all passed). After the third loss, **N=475 is the accepted
final** (≥ the 470-pair power target of §12). **3275 SUCCEEDED / 42 FAILED / 8 DEAD_LETTER (97.8%)**; exec@1
= 0.98–0.99 per arm; **cross-user private injection = 0**; `returned_models = [solar-pro2-251215]`. The 25
missing targets are a **uniform** loss across all arms (the whole chunk didn't run), so they cannot bias the
paired E1 contrast; ITT and complete-case give the same null (below).

## Actual Pass@1 by arm (BigCodeBench-Instruct, no repair)
| Arm | memory | Pass@1 |
|---|---|---|
| **M0** | NO_MEMORY (baseline) | **0.394** |
| M1 | PRIVATE_SELECTED (own prior source) | 0.417 |
| M2 | TRUE_RELEVANT_SELECTED (relevant, cross-user, oracle) | 0.390 |
| M3 | SHUFFLED_MATCHED_SELECTED | 0.411 |
| M4 | DEPLOYABLE_RETRIEVED_SELECTED (prod retrieval) | 0.394 |
| M5 | ALWAYS_INJECT_TOP1_SELECTED | 0.402 |
| M6 | RELEVANT_PLAIN_SAME_SOURCE | ≡ M2 (0.390) — logical alias under the plain-format selection |
| M7 | RELEVANT_GOVERNED_SAME_SOURCE | 0.396 |

## Primary family (fixed sequence, α=.05, two-sided paired)
- **E1 — relevance causal effect: M2 (relevant) − M3 (shuffled-matched) = −0.021**, task-bootstrap 95% CI
  **[−0.051, +0.008]**, exact McNemar b=21 / c=31, **p = 0.212 → DOES NOT REJECT.** Relevant memory does **not**
  help beyond generic matched extra context (if anything the shuffled arm is nominally higher).
- **E2 — deployable business effect (M4 vs M0): GATED OUT** by the fixed sequence (E1 did not reject). For
  reference M4 = M0 = 0.394 (Δ = 0.000).

## Secondary (Holm-corrected, none significant)
| contrast | Δ | p | reject |
|---|---|---|---|
| M1 − M0 (private-memory effect) | +0.023 | 0.144 | no |
| M2 − M4 (retrieval headroom) | −0.004 | 0.902 | no |
| M5 − M4 (threshold/abstention) | +0.008 | 0.608 | no |
| M7 − M6 (governed vs plain, same source) | +0.006 | 0.784 | no |

## Interpretation (honest, confirmatory)
On BigCodeBench-Instruct, with a **proper relevance control** (shuffled-matched) and a **preregistered** design:
1. **Relevant memory has no causal benefit over generic matched context** (E1 null, slightly negative). This is
   the milestone's headline confirmatory finding and it **replicates the R1 / R1.1 pattern at scale** with the
   causal control R1 lacked.
2. **No deployable lift**: M4 (production retrieval) = M0 (no memory) exactly (0.394); the memory arms cluster
   ~0.39–0.42 with no meaningful separation. The only nominal positive is M1 (the target's own prior source,
   +0.023 over M0) — **not significant** (Holm p=0.14) and not the shared-transfer condition.
3. **No governed-format advantage** (M7 − M6 = +0.006), consistent with R1.
4. Complete-case sensitivity (M0 .400 / M2 .395 / M3 .417 / M4 .400) matches the ITT result.

**A null confirmatory result is a valid, final endpoint (§12).** No task/policy/threshold/arm/endpoint/N was
changed after seeing the outcome; no other benchmark was opened because p ≥ .05.
