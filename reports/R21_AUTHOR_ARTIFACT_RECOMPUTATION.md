# R21 Stage A — Author-Artifact Recomputation

Regraded the RELEASED MemGovern trajectory predictions with the official SWE-bench Verified grader
(`swebench==5.0.2`). **No model calls.** Upstream patches were graded in an ephemeral CI runner and never
committed here (only per-instance resolved labels).

## Result table
| Condition | Released preds | Regraded resolved | Regraded rate (released) | Published successes | Published rate | Recomputable? |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| GPT-4o baseline | 99 | 32 | 0.323 | 116 | 0.232 | NO |
| GPT-4o MemGovern | 99 | 33 | 0.333 | 163 | 0.326 | NO |
| GPT-4o-mini baseline | 10 | 1 | 0.100 | 70 | 0.140 | NO |
| GPT-4o-mini MemGovern | 128 | 17 | 0.133 | 86 | 0.172 | maybe |

## Released-artifact lift (the only paired comparison possible)
GPT-4o default and agentic share **98 overlapping instances**. On that overlap:
baseline **32**, MemGovern **33** → **released-subset lift = +1 (1.02pp)**,
versus the published **+9.4pp**. The GPT-4o-mini tarballs share **0** instances, so no paired mini comparison exists.

## Why this is not a table verification
1. The released predictions (99/99/10/128) are a **partial subset** of the 500-instance runs; in 3/4 conditions the
   published success count exceeds the number of released predictions.
2. The released GPT-4o baseline resolves at **32.3%** — higher than the published 23.2% — so the released subset is
   **not representative** of the full benchmark.
3. **Author per-task grade labels are not in the release**, so author-vs-recomputed label agreement is not computable.

## Verdict
**AUTHOR_ARTIFACT = AUTHOR_ARTIFACT_UNAVAILABLE.** The released artifacts are insufficient (and non-representative)
to recompute the published SWE-bench Verified table. This is a reproducibility gap in the *release*, not a claim
that the published numbers are wrong — the full-run artifacts may exist privately. `INDEPENDENT_EXACT_REPRODUCTION
= NOT_RUN`, `COMPANY_NATIVE_BRIDGE = NOT_RUN`.
