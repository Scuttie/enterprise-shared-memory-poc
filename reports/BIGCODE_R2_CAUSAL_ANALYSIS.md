# BigCode-R2 — Causal & Transfer Analysis (§10, §14)

Companion to BIGCODE_R2_MAIN_RESULTS.md. Every claim below is backed by the frozen job evidence and the
evidence-based patch classifier (`experiments/patch_forensics.py`) — **memory adoption is never asserted
without AST/API/operation/control-flow evidence** in the emitted patch.

## 1. The causal contrast is clean
The relevance effect is identified by **M2 (TRUE_RELEVANT) vs M3 (SHUFFLED_MATCHED)**: both inject the *same
number* of verified cross-user source lessons in the *same F1_PLAIN format*; only the **content relevance**
differs (M3 is a frozen derangement of the M2 assignment). Confounds held constant: injection count, format,
token budget, model, temperature, benchmark task set (paired). So any Pass@1 gap is attributable to relevance,
not to "more context."

**Result: M2 − M3 = −0.021, 95% CI [−0.051, +0.008], McNemar b=21/c=31, p=0.212.** The point estimate is
*negative* and the CI's upper bound (+0.008) rules out any relevance benefit larger than ~1 pt. Relevant
memory does not causally help; the discordant pairs even lean toward the shuffled arm (31 vs 21).

## 2. Transfer forensics — memory rarely gets adopted, and when it does it doesn't convert to correctness
Losses = tasks a memory arm fails that M0 solves; gains = the reverse. Classes from the AST classifier:

| Arm (vs M0) | gains | losses | of losses: UNRELATED impl error | of losses: **source-adoption** |
|---|---|---|---|---|
| M1 PRIVATE | 29 | 18 | 16 | 2 (1 API, 1 control-flow) |
| M2 RELEVANT | 30 | 32 | 25 | **7 (API-call adoption)** |
| M3 SHUFFLED | 29 | 21 | 20 | 0 |
| M7 GOVERNED | 35 | 34 | 23 | 10 (9 API, 1 CF) |

Reading:
- **Gains ≈ losses in every arm** (M2 30/32, M1 29/18, M3 29/21) → the memory arms mostly *reshuffle* which
  tasks pass rather than adding net solutions. This is the mechanism behind the flat Pass@1.
- **When the model does adopt source content (M2: 7 API-call adoptions among its losses; M7: 10)**, that
  adoption is associated with *breaking* a task M0 solved — i.e. even genuine transfer is not net-beneficial on
  this benchmark. Adoption is real (AST-evidenced) but not helpful.
- **M3 (shuffled) shows 0 source-adoption** — as designed, irrelevant lessons are ignored — yet its Pass@1 is
  *not lower* than M2. If relevance mattered, M2's 7 adoptions should have bought correctness over M3's 0. They
  did not.
- The dominant loss class everywhere is **UNRELATED_IMPLEMENTATION_ERROR** (model-side mistakes unrelated to
  the injected memory), confirming losses are mostly not memory-poisoning.

## 3. §14 patch-level transfer conclusion
There **is** measurable content transfer (M2/M7 API-call adoptions are AST-verifiable), so the null is *not*
an artifact of the model ignoring memory. The finding is stronger: **the model reads and sometimes applies the
relevant lessons, and it still yields no accuracy benefit over the relevance-matched control.** Transfer
happens; causal lift does not.

## 4. Safety-relevant read
No cross-user private leakage occurred (`cross_user_private_injection = 0` across all 3,275 jobs). Wrong-memory
harm is quantified separately on the RESERVE tasks in BIGCODE_R2_SAFETY.md (§13). Within the main, the shuffled
arm (M3) did not underperform baseline, i.e. irrelevant injected memory was not measurably harmful here either.
