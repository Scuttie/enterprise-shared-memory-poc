# R12-E — Deferred on cost (terra too expensive); pivot to gpt-4o-mini

## Decision (2026-08-19, user cost concern at ~$9 spent)
The R12-E repository memory main was designed to run gpt-5.6-terra × M0–M4 × 60 targets = 300 agentic calls.
Estimated at ~$35 (terra is a reasoning model with ~77k input tokens/task in the agentic loop). It was
**cancelled before completion** to control spend.

## Why this is scientifically OK
- R12's core question is already answered without E: **reader capability was a large bottleneck** (B0: Solar
  0.115 → OpenAI 0.246–0.738; D0: Solar 1/40 → terra 15/40), but **the transferred memory is not useful even
  with a much stronger reader** (C0: M1−M2 ≈ 0 null; M1−M0 slightly negative; reader-moderation DiD ≈ 0). E on
  terra would most likely replicate that null in the agentic setting at ~70× the cost per task of gpt-4o-mini.
- terra was needed only to **prove the reader was the bottleneck** (D0 PASS), which is done. It is a poor choice
  for the *representation* question (near-ceiling on LiveCodeBench; hugely expensive on SWE-PolyBench).

## What replaces it (cheaper + more on-topic)
The actual research question — **which memory ENCODING/DECODING helps** — moves to **R13** on the mid-band,
~100× cheaper **gpt-4o-mini** (LiveCodeBench). The frozen R12-E partition, prereg, and memory remain committed and
can be run later on terra if a budget is approved (the E artifacts are preserved, not deleted).

## Endpoint
R12 concludes at **C (DIRECT-CODE READER-SWAP COMPLETE) + D0 repository band PASS**; **E deferred (cost)**, not a
REPOSITORY READER STOP. R1–R12 artifacts + P6 frozen; PR#1 draft; P6 not resumed.
