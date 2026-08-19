# R12-D0 §10 — Repository-Agent Band Audit (gpt-5.6-terra) → GATE PASS

gpt-5.6-terra (reasoning medium) on the **exact frozen R7 40-task SWE-PolyBench no-memory pilot** via the
Responses API through the R7 repository-agent harness (tools, Docker instance images, official evaluator, patch
format, tool policy, 40-turn / wall-clock budget all reused verbatim; only the model/provider changed).

## Result
| gate | requirement | observed | verdict |
|---|---|---|---|
| R1 technical terminal | ≥ 38/40 graded | **40/40** | PASS |
| R2 evaluator/env failure | ≤ 2/40 | **0/40** | PASS |
| R3 leakage | 0 | 0 (gold/tests never in agent context) | PASS |
| R4 resolved count | ∈ [4, 28] | **15/40 (0.375)** | PASS |
| R5 transcript/accounting | ≥ 38/40 | 40/40 | PASS |

Per-language resolved: Java 4/10, JavaScript 6/10, Python 4/10, TypeScript 1/10. Terminal: 39 ok + 1 empty_patch,
all graded. Tokens: input 3.10M, output 78.5k, reasoning 36.9k (avg/task 77.5k in, 1.96k out, 182 s).

## Headline — the repository-agent floor was reader-bound
On the **identical** frozen pilot, Solar-pro3 resolved **1/40 (0.025, a floor** → R7-G1 INSTRUMENT STOP);
gpt-5.6-terra resolves **15/40 (0.375, comfortably in-band)**. Swapping only the reader moves the instrument from
floor to a measurable band — the R7 repository-agent floor was primarily **reader capability**, not the task,
harness, or extraction. gpt-5.6-terra is a competent agent (e.g., search→read→replace_lines→submit in 5 turns).

## Decision
**GATE PASS → proceed to R12-E** (SWE-PolyBench memory main under a new reader-specific preregistration; exclude
the 40 pilot tasks; corrected M0–M4). A cost estimate is written first (`R12_REPOSITORY_MAIN_COST_ESTIMATE.md`,
§12) before any memory-arm call. No tool budget / reasoning effort / prompt changes were made after this band
result (§16 hard stop respected).
