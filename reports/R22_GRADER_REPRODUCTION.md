<!-- R22_SUPERSEDED_BY: R22_UPSTREAM_EVALUATOR_EXECUTION_REVIEW -->
# R22 (G0.1) — GENERIC_ENRICHED_SWEBENCH_GRADER_PASS

**Status: `GENERIC_ENRICHED_SWEBENCH_GRADER_PASS` — narrow scope only.** This result validates the **generic
enriched SWE-bench** grader routing (Verified/Lite/Multilingual, `image` taken from the enriched `SWE-bench/*`
row). It is **NOT** the SWE-ContextBench Related grader and **does not** gate the R22 paid campaign.

> ⚠️ Scope boundaries (P0.8.1 §1):
> - Validates **generic enriched SWE-bench Verified/Lite/Multilingual routing** only.
> - Uses the **historical G0.1 12-task set** (a *different* set: `apache__lucene-11760`, `astral-sh__ruff-15543`,
>   `astropy__astropy-8707`, `caddyserver__caddy-5761`, `google__gson-2311`, … — it does **not** overlap the frozen
>   SWE-ContextBench P1 12).
> - **Does NOT validate** the frozen SWE-ContextBench **Related** P1/P2 grader (that path uses the benchmark's own
>   `swebench_memory.harness.run_evaluation` + `jiayuanz3/swecontextbench:<tag>` images).
> - **Is NOT sufficient for paid approval.**
> - **Superseded for the R22 paid gate** by **`R22_UPSTREAM_EVALUATOR_EXECUTION_REVIEW`** (see
>   `reports/R22_SCB_GRADER_REPRODUCTION.md` and `artifacts/r22/grader_smoke_supersession.json`).

## Result (run 32801365294, enriched SWE-bench/* datasets, historical commit `1cc9d92`)
| Gate | Required | Actual |
| --- | --- | --- |
| gold resolved | 12/12 | **12/12** |
| no-patch unresolved | 12/12 | **12/12** (0 resolved) |
| infrastructure failures | 0 | **0** |
| result completeness | 24/24 | **24/24** |
| official tests modified | 0 | **0** |

The historical bytes of `artifacts/r22/grader_smoke.json` are preserved unchanged (schema `r22/grader_smoke/2.0.0`,
verdict field `R22_GRADER_READY_AWAITING_PAID_APPROVAL` retained as a historical value). Its supersession is
recorded in `artifacts/r22/grader_smoke_supersession.json` — that verdict must **not** be read as the current R22
endpoint.

## Why this cannot gate P1/P2
The generic enriched-SWE-bench path pulls the `image` field from the enriched row; the frozen SWE-ContextBench
Related targets are **not** in those enriched datasets and are graded by the **benchmark's own** evaluator/images.
Two additional gaps closed in P0.8.1 for the real SCB gate: the baseline control is now a **no-op patch** (not an
empty patch that short-circuits without executing tests), and the official image is **pulled by digest and
verified** at runtime. See `reports/R22_SCB_GRADER_REPRODUCTION.md`.
