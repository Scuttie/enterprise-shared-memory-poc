# REALBENCH-R11 (LiveCodeBench) — LIVEBENCH MAIN COMPLETE (null primary)

One widely-used public benchmark, minimal causal controls, run end-to-end on the official evaluator. **Primary
result is NULL**: relevant verified prior-problem memory does not beat matched context-stuffing. Per the
milestone a null closes the static positive-efficacy public-benchmark track. No benchmark ladder; nothing
fabricated; R1–R10 frozen; P6 not started.

## Instrument + provenance (pinned)
- Repo `github.com/LiveCodeBench/LiveCodeBench` @ `28fef95…` (**MIT**); dataset `livecodebench/code_generation_lite`
  @ `0fe84c39…`, config `release_v6` (1055 problems, May 2023–Apr 2025). Official code-generation setting,
  official `extract_code` + `codegen_metrics` (Pass@1, `multiprocessing.Process`, no Docker). id=`question_id`,
  date=`contest_date`. `configs/livecodebench_r11/benchmark_lock.json`. Per instruction, contest-site/problem
  licenses were recorded as provenance, not audited as a separate gate.
- **Technical smoke PASS**: extractor + grader work; **grader is discriminative** (deliberately wrong body → 0/20;
  correct → 20/20 on contaminated 2023 tasks). Env: `datasets==2.21.0` (script loader), Python 3.10 (pyext).

## Frozen partition (before any target call)
Temporal split by `contest_date`, cutoff **2025-01-01**: **TARGET = 182** (Jan–Apr 2025, HARD 82 / MED 55 / EASY
45; AtCoder 112 / LeetCode 70), **SOURCE_POOL = 873** (< 2025-01-01). Disjoint; sha256 `352d156f…`
(`artifacts/livecodebench_r11/task_partition.json`). Recent window chosen by date (contamination-reduced), not by
no-memory success. The smoke touched only 2023 source tasks — no target was pre-observed.

## Reader
`solar-pro3-260323` (returned string confirmed), temperature 0, one generation, no repair, fixed 4096-token
budget. Unchanged across all arms.

## No-memory band (M0 = the main M0 arm)
Pass@1 = **11.5% (21/182)** — EASY 28.9%, MEDIUM 12.7%, HARD 1.2%. A low but non-zero band on contamination-free
recent competitive problems (the honest reality for this reader). Sources (2023–24) are near-ceiling for easy
items but the relevance-nearest sources to the HARD targets are themselves hard.

## Source bank + memory (verified only)
456 candidate sources solved (M0), **62 verified** (passed official tests). Relevance = cosine of PINNED
`all-MiniLM-L6-v2` embeddings over public title+content (median nearest-sim 0.71); no target solution/tests ever
entered a memory. **Coverage: 109/182 targets** have a verified relevant source in top-10. Per covered target: M1
= plain lesson (technique+pitfall+verify, med 383c) and M3 = actionable lesson (Algorithm/Preconditions/Edge
cases/Invariants, med 1136c) from the **same** verified source; M2 = plain lesson from a difficulty-matched
UNRELATED verified source (outside top-K, deterministic pick). Controls held: M1/M3 identical source ID; M1/M2/M3
same injection position/format; memory contains no target body/tests.

## Main results (all arms 182/182 terminal ok — full ITT, 0 infrastructure failures)
| arm | Pass@1 (182) | Pass@1 (covered 109) |
|---|---|---|
| M0 NO_MEMORY | 0.115 | 0.147 |
| M1 RELEVANT_PLAIN | 0.104 | 0.138 |
| M2 SHUFFLED_MATCHED | 0.099 | 0.128 |
| M3 RELEVANT_ACTIONABLE | 0.082 | 0.083 |

Paired contrasts on the 109 covered targets (exact McNemar + deterministic paired bootstrap 95% CI):
- **H1 (primary) M1 − M2 = +0.009**; discordant 9 (M1✓M2✗) vs 8 (M1✗M2✓); **McNemar p = 1.0**; boot95 CI
  **[−0.073, +0.083]** → **NULL**. Relevant verified prior experience does **not** beat matched context-stuffing.
- **H2 M1 − M0 = −0.009**; positive transfer (fail→pass) = 8 vs negative (pass→fail) = 9; p = 1.0; CI
  [−0.083, +0.064] → **no benefit over no-memory** (near-symmetric noise flips).
- **H3 M3 − M1 = −0.055**; discordant 3 vs 9; p = 0.146; CI [−0.119, +0.009] → **negative trend**: the verbose
  actionable format *hurt* relative to plain. Pass@1 falls monotonically with memory verbosity
  (M0 > M1 > M2 > M3).
- By difficulty (covered): the only movement is EASY (M1 14 vs M2 12); MEDIUM 1 vs 2; HARD 0 vs 0. No effect
  survives on medium/hard.
- Tokens: completion ~0.62M per arm; M3 uses the most prompt tokens (147k) for no gain.

## Conclusion + track closure
**The primary hypothesis is not supported (null).** On LiveCodeBench recent competitive problems with solar-pro3,
relevant verified prior-problem memory neither beats a matched-irrelevant control nor a no-memory baseline, and a
more elaborate "actionable" rendering actively degrades performance. The result is bounded and honest, not a
manufactured positive: controls, disjointness, leakage-freeness, and ITT all held; the grader was validated
discriminative. Per the milestone, a null **closes the static positive-efficacy public-benchmark track** — **no
other public benchmark will be opened.** Whether to begin P6 contamination/governance work is a separate decision
to be asked explicitly.

**Preserved:** R1–R10 frozen; `main` d56d178; PR#1 draft/OPEN; version 0.2.0.dev1; tag v0.1.0-poc; **P6 not
started.**
