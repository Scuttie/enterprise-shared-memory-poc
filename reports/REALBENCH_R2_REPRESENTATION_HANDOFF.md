# REALBENCH-R2 → R3 Representation Handoff (§1 claim boundary)

This document fixes exactly what R2 established, so that REALBENCH-R3 is understood as a test of a **new
hypothesis about representation actionability** — **not** a reanalysis intended to rescue the R2 null.

## Exact R2 conclusions (frozen, not to be reinterpreted)
From the preregistered BigCodeBench-Instruct confirmatory main (`artifacts/bigcode_r2/results/main_results.json`,
N=475 paired ≥ the 470 power target; split_hash `6e075558`; dataset content-hash `98e377a8…`):

1. **Relevant memory did not outperform shuffled-matched memory.** E1 (M2 TRUE_RELEVANT − M3 SHUFFLED_MATCHED)
   = **−0.021**, 95% CI [−0.051, +0.008], exact McNemar b=21/c=31, p=0.212 → did not reject.
2. **Deployable retrieved memory did not outperform no memory.** M4 = M0 = 0.394 (Δ=0.000); E2 gated out.
3. **No governed-format advantage was established.** M7 − M6 (governed vs plain, same source) = +0.006, Holm n.s.
4. **API/AST adoption occurred without an accuracy benefit.** M2 showed 7 AST-verified source-API adoptions among
   its losses; adoption was real but did not convert to correctness.
5. **Wrong-memory poisoning was NOT established in the confirmatory main.** The §13 safety subset showed S2/S3/S4
   = baseline and S1 shuffled −0.05 (≈3/60) with **0 source-adoption** — no AST evidence of poisoning.
6. **BigCodeBench R2 is frozen as a confirmatory NULL.** No task/format/threshold/arm/endpoint/N was changed
   after seeing the outcome.

## What R3 tests (new, not a rescue)
R2 asked *whether relevant memory helps at all* under a plain/governed lesson encoding and found it does not
beat a matched control. **R3 asks a different question:** for a **fixed, verified, relevant** source experience,
**which representation most reliably converts that experience into correct target code** — an *actionability
ladder* from prose → structured decision → procedural → executable constraint → code-edit representation, each
paired with a matched decoder, on an **independent unseen benchmark (official DS-1000)**.

Key design consequences carried into R3 (from the R2 lessons):
- source ID is **frozen before rendering**; every representation is generated from the **same canonical source
  object**; retrieval projection and execution view are **separate**; representation+decoder form **one bundle**;
  relevant-vs-shuffled and same-source (selected-vs-plain) controls are **mandatory**.
- R3's primary contrasts are **H1 M2(selected repr) > M1(plain)** and **H2 M2 > M3(shuffled-matched)** — the
  plain-vs-selected same-source contrast is exactly the axis R2 could not resolve.

**R3 is a forward test of representation actionability. A null R3 is equally final; it will not be used to
reinterpret R2, and R2's frozen null stands regardless of R3's outcome.**
