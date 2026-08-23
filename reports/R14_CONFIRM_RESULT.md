# R14-CONFIRM — RESULT: the n=60 positive did NOT replicate. Final verdict = NULL (not confirmed).

Preregistered powered confirmation, same reader (gpt-4o-mini), same harness/memory/controls. 120 NEW targets
(sha256 284ee88f), disjoint from the original 60, pooled to N=180. The original 60 were reused unchanged. The
decision rule was fixed in advance: **confirmed iff pooled M1−M2 > 0 with McNemar p < 0.05 AND cluster-boot CI
excludes 0.**

## Split-by-split (the replication)
| split | M0 | M1 (relevant raw fix) | M2 (shuffled raw fix) | M1−M2 | M1−M0 |
|---|---|---|---|---|---|
| original 60 | 0.083 (5) | **0.150 (9)** | 0.083 (5) | +0.067 (p=0.22) | +0.067 (p=0.22) |
| **confirm 120 (preregistered)** | 0.100 (12) | **0.092 (11)** | 0.117 (14) | **−0.025 (p=0.38)** | −0.008 (p=1.0) |
| **pooled 180** | 0.094 (17) | 0.111 (20) | 0.106 (19) | **+0.006 (p=1.0)** | +0.017 (p=0.51) |

## Verdict — NOT CONFIRMED (null)
On the fresh preregistered 120, the effect did not merely shrink — it slightly **reversed** (M1 was the lowest
arm). Pooled N=180: M1−M2 = +0.006, McNemar p = 1.0, cluster-boot CI [−0.018, +0.035]; M1−M0 = +0.017, p = 0.51,
CI [−0.024, +0.042]. The preregistered decision rule is **not met** on any criterion. The R14 n=60 positive
(M1 doubling M0/M2, relevance-specific) was **small-sample noise**: at a ~9% base rate, 60 tasks give only a
handful of discordant pairs, and the apparent "relevance-specific doubling" was 4 lucky discordant flips.

## What this means for the program
Even the best-case redesign — a REAL prior same-repo resolved issue with its actual gold diff (raw worked
example, not a distilled abstraction), on the most-used repository benchmark (SWE-bench Verified) — does **not**
produce a reliable memory-transfer benefit for this reader. This is consistent with, and strengthens, the earlier
nulls (R1 MBPP+, R11 LiveCodeBench, R13 encodings): across code benchmarks, injecting another problem's/engineer's
solved memory does not reliably help the model solve a new problem. The honest headline: **no reliable positive
transfer, confirmed under preregistration; the one apparent positive failed to replicate.**

Discipline note: because the confirmation was preregistered with a fixed decision rule and disjoint frozen tasks,
this null is trustworthy — it is not the result of stopping at a favorable N or reshuffling after seeing data.
`artifacts/swebench_r14/main_result.json` (pooled). R1-R13 + P6 frozen; PR #1 draft.
