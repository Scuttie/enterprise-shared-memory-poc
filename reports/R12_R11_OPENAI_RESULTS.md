# R12 §7/§8 — R11 Reader-Swap Diagnostic Results (gpt-4o-mini)

The frozen R11 M0–M3 instrument run with **only the reader changed** (Solar-pro3 → gpt-4o-mini-2024-07-18).
Writer, memory content, retrieval, prompt, tasks, grader, injection positions, and the 4096 output budget are the
**exact frozen R11 artifacts** (Solar remains the writer; the memory was NOT regenerated). This is a
**reader-sensitivity DIAGNOSTIC**, not independent confirmation, and not contamination-free (R11 tasks predate the
GPT knowledge cutoff).

## Pass@1 by arm (all 182 targets; ITT, exec = 1.000 on every arm)
| arm | R12 gpt-4o-mini | (R11 Solar-pro3) |
|---|---|---|
| M0 NO_MEMORY | **0.302** | 0.115 |
| M1 RELEVANT_PLAIN | 0.269 | 0.104 |
| M2 SHUFFLED_MATCHED | 0.286 | 0.099 |
| M3 RELEVANT_ACTIONABLE | 0.291 | 0.082 |

## Paired contrasts on the 109 memory-covered targets (exact McNemar + paired bootstrap 95% CI)
- **M1 − M2 = −0.018** (M1 0.330 vs M2 0.349); McNemar p = 0.69; CI **[−0.064, +0.028]** → **NULL** (relevant ≈
  shuffled-matched, as with Solar).
- **M1 − M0 = −0.037** (M1 0.330 vs M0 0.367); CI **[−0.073, −0.009]** → memory is **slightly harmful** (CI just
  excludes 0), the same direction Solar showed.
- **M3 − M1 = +0.028** (M3 0.358 vs M1 0.330); p = 0.375; CI [−0.009, +0.064] → the actionable format is **not**
  worse here; Solar's "actionable hurts" (M3−M1 = −0.055) **does not replicate** — it was reader-specific.

## Reading (milestone matrix → B)
- The reader was a **large capability bottleneck**: on the covered 109, M0 rose from Solar **0.147** to
  gpt-4o-mini **0.367** (≈ 2.5×); across the 61-task band the OpenAI readers reached 0.25–0.74 vs Solar 0.115.
- **Yet the memory is still not useful under the stronger reader**: M1 ≈ M2 (null) and M1 < M0 (slightly harmful).
  This matches interpretation **B**: *the transferred content/relevance — not the Solar reader alone — is the main
  limitation.* A stronger reader raises the baseline but does not make the (Solar-written, relevance-retrieved)
  memory helpful. It also rules out **D** (baseline is not low) and does not reproduce **E** (actionable does not
  interfere here).

## Cost/latency (§13)
728 calls; input 445,135 + output 312,559 tokens; latency median 5.39 s. Estimated cost ≈ **$0.25** at public
gpt-4o-mini rates ($0.15 / $0.60 per 1M in/out). Full accounting in `reports/R12_COST_AND_LATENCY.md`.

Artifacts: `artifacts/openai_reader_r12/arms/{M0..M3}.json`, `moderation_result.json`.
