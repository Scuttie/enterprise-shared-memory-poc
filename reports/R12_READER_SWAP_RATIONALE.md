# R12 §1 — Reader-Swap Rationale + Claim Boundary

R12 asks one question, holding the memory channel fixed: were the repeated Solar null/floor results driven mainly
by the **Solar reader**, or is the **transferred memory** itself not useful enough? It changes **only the reader**
(Solar → OpenAI); the writer, memory, retrieval, prompts, tasks, and grader stay exactly as frozen in R11/R7.

## Exact pre-R12 state (recorded, not discarded)
- **R11 LiveCodeBench (Solar-pro3, official grader, frozen):** M0 no-memory = **0.115**, M1 relevant-plain =
  **0.104**, M2 shuffled-matched = **0.099**, M3 relevant-actionable = **0.082**.
- **Primary R11 relevant-vs-shuffled (M1−M2) = null** (+0.009, McNemar p=1.0, CI [−0.073,+0.083]).
- **Actionable representation was directionally worse** (M3−M1 = −0.055).
- Solar-pro3 sat in a **low direct-code band** (~11%); R5/R6 SkillsBench and R7 SWE-PolyBench showed
  repository-agent **floors** (R7 no-memory 1/40 = 0.025); DS-1000 was a **near-ceiling** (0.98); BigCodeBench
  (R2) produced a **powered causal null**.

## What R12 does / does not claim
R12 **does not discard** any of the above. It tests **reader moderation** with the memory channel fixed:
writer fixed + source correctness fixed + memory content fixed + retrieval fixed + benchmark fixed + **reader
changed**. Because the R11 task set and Solar results were already observed, all R12-on-R11 inference is an
explicit **reader-sensitivity DIAGNOSTIC**, never independent confirmation, never a new primary efficacy result,
and it does not replace the R11 conclusion. The R11 LiveCodeBench tasks also predate the GPT-5.6 knowledge
cutoff, so R12-on-R11 is **not** contamination-free.

## Constraints
No new benchmark search; no new tasks/source memories/retrieval pairing/memory formats; no per-model prompt
optimization; reader never selected using memory-arm results; no sample expansion after p-values. R1–R11 and
P6-A0/B0 frozen; `main` d56d178; PR#1 draft; version 0.2.0.dev1. Further P6 work is **paused** for the duration
of R12 (existing P6 results preserved).
