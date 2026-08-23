# P6-A0 — Contamination Gradient (result)

Frozen date-stratified no-memory sweep (solar-pro3, temp 0, official grader) to test whether early
LiveCodeBench scores are inflated by training-set contamination. Sample: 105 tasks, 4 per (year-quarter ×
difficulty), 2023Q2–2025Q2, sha256 `108dcc6c…` (`configs/p6_contamination/gradient_sample.json`). Result:
`artifacts/p6_contamination/gradient_M0.json`.

## Pass@1 by quarter (difficulty balanced within each quarter)
| quarter | Pass@1 | | quarter | Pass@1 |
|---|---|---|---|---|
| 2023Q2 | 0.00 (0/12) | | 2024Q3 | 0.17 (2/12) |
| 2023Q3 | 0.00 (0/12) | | 2024Q4 | 0.17 (2/12) |
| 2023Q4 | 0.08 (1/12) | | 2025Q1 | 0.00 (0/12) |
| 2024Q1 | 0.25 (3/12) | | 2025Q2 | 0.11 (1/9) |
| 2024Q2 | 0.25 (3/12) | | overall | **0.114 (12/105)** |

## Finding — NO monotone contamination gradient (the opposite, if anything)
- A simple training-contamination story predicts **highest** Pass@1 on the **oldest** problems (most likely
  memorized) decaying toward recent ones. The data show the reverse at the extremes: the **oldest** quarters
  (2023Q2–Q3) are the **lowest (0%)**, the curve peaks in **2024** (25%), then falls again in 2025. With
  difficulty held balanced per quarter, this is **not** consistent with date-based memorization inflating early
  scores.
- The R11 technical smoke's "20/20 on 2023" was **not representative**: those were the first-20 `question_id`s,
  which are all 2023 **LeetCode EASY** — a cherry of the easy tail, not the 2023 population. On a balanced 2023
  sample, EASY is 0/4 and 0/4 in Q2/Q3.
- Overall Pass@1 across the whole release window is **~11%**, the same low band as the R11 targets (M0 = 11.5%).
  solar-pro3 is uniformly weak on stratified LiveCodeBench competitive problems regardless of era.

## Implication for R11
This **strengthens the R11 null's validity**: the recent 2025 target window is **not** an anomalously depressed
slice relative to the broader distribution, and early "ceiling" fears were an artifact of a non-representative
easy-LeetCode smoke. The R11 memory null therefore reflects the reader's genuine (low) capability band, not a
contamination cliff at the target dates.

## Honest caveats
- Small N per cell (4) and per quarter (9–12) → high variance; the non-monotone bumps (e.g., the 2024 peak) are
  within noise and should not be over-read. The robust, low-variance claim is the **negative** one: there is **no
  evidence of a monotone old→recent decline**, i.e. no visible training-contamination signature at the release-
  window scale for this reader.
- A temporal Pass@1 gradient, even if present, is confounded by real difficulty/platform drift across releases;
  here difficulty was balanced per quarter, but platform mix (LeetCode/AtCoder) was not, and could contribute to
  the 2024 bump.

## Status
P6-A0 (gradient) + P6-B0 (governance re-attestation, ALL 13 checks PASS,
`artifacts/p6_contamination/governance_attestation.json`) complete. No official test modified; no new benchmark
(static efficacy track stays closed). R1–R11 frozen; `main` d56d178; PR#1 draft; **P6 in progress, no P7/P8**.
