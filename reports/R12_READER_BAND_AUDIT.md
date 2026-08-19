# R12 §6 — No-Memory Reader-Band Audit + Selection

Frozen 61-task set (`artifacts/openai_reader_r12/band_tasks.json`, sha256 `8d4ff626…`, hash-stratified over
difficulty × platform of the 182 R11 targets). NO_MEMORY only; official LiveCodeBench grader; identical prompt +
frozen 4096 output budget across readers. Live OpenAI (Responses API via OpenAIResponsesProvider).

## Results
| reader | Pass@1 | exec | malformed | returned model |
|---|---|---|---|---|
| gpt-4o-mini-2024-07-18 | **0.246** | 1.000 | 0/61 | gpt-4o-mini-2024-07-18 |
| gpt-5.6-luna / medium | 0.656 | 0.885 | 4/61 | gpt-5.6-luna |
| gpt-5.6-terra / medium | 0.738 | 0.918 | 1/61 | gpt-5.6-terra |

## Headline — the Solar reader WAS a major bottleneck
Solar-pro3's no-memory band was ~0.115 (R11). Every OpenAI reader is far higher on the same frozen tasks:
gpt-4o-mini **0.246**, luna **0.656**, terra **0.738**. This directly answers R12's core question in the
direction of **reader capability**: much of the prior floor was the reader, not (only) the instrument.

## Eligibility (E1 exec≥0.98 · E2 infra≤0.02 · E3 malformed≤0.02 · E4 Pass@1∈[0.20,0.70] · E5 leakage=0)
- **gpt-4o-mini — ELIGIBLE** (exec 1.000, malformed 0, Pass@1 0.246 in band).
- **gpt-5.6-luna — INELIGIBLE**: exec 0.885 < 0.98 and malformed 6.6% > 2%.
- **gpt-5.6-terra — INELIGIBLE**: Pass@1 0.738 > 0.70 (near-ceiling) and exec 0.918 < 0.98.
- The luna/terra exec shortfalls are **genuine, not a harness bug**: every non-ok call is `final_status=parser`
  ("empty/incomplete") because the **reasoning tokens (~3500–3700) exhausted the frozen 4096 output budget**,
  leaving no room for the code. The budget is frozen and identical across readers (changing it is a hard stop),
  so these count as failures (ITT).

## Selection (frozen rule, not by memory lift/p-value/preference)
Among eligible readers, minimise |Pass@1 − 0.45|; gpt-4o-mini is selectable because **no GPT-5.6 candidate is
eligible**. → **SELECTED = `gpt-4o-mini-2024-07-18`** (family gpt4o, temperature 0, no reasoning; Pass@1 0.246).
This is also the Goldilocks choice for measuring a memory effect (mid-band, solving some-but-not-all), whereas
terra sits near the ceiling where memory effects would be hard to detect.

`artifacts/openai_reader_r12/{band_results,selected_reader}.json`. Next: R12-C0 — the frozen R11 M0–M3
reader-swap diagnostic with the selected reader (Solar memory reused verbatim; reader-sensitivity DIAGNOSTIC,
not confirmation).
