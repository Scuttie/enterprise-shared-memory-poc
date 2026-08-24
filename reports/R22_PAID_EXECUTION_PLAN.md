# R22 §10/§11 — paid execution cost plan + approval request format

No model was called to produce this. Machine-readable: `configs/r22/paid_run_plan.json`. Estimates are conservative
upper bounds; each stage is re-estimated and re-approved before it runs. Budget is **never** requested all at once.

## Frozen reader-candidate order (before any memory result is seen)
| Rank | Provider | Model | Snapshot-pinnable | in $/Mtok | out $/Mtok | Secret | Rationale |
|---|---|---|---|---:|---:|---|---|
| 1 | deepseek | `deepseek-chat` | no | 0.27 | 1.10 | `DEEPSEEK_API_KEY` | faithful to SWE-Exp (DeepSeek-V3); alias not `-0324`-pinned → any run is `MODEL_DRIFT_REPLICATION` |
| 2 | openai | `gpt-4o-mini` | yes | 0.15 | 0.60 | `OPENAI_API_KEY` | cheap in-band candidate (R14–R18 lineage) |
| 3 | openai | `gpt-4o` | yes | 2.50 | 10.00 | `OPENAI_API_KEY` | stronger reader if gpt-4o-mini falls outside the `[0.10,0.70]` band |

Reader is chosen by §5.1: run 40 dev no-memory tasks and take the **first** frozen candidate whose resolved rate is
in `[0.10, 0.70]` — not the highest scorer. If none is in band → `R22-INSTRUMENT-STOP`.

## Three-stage cost (upper bound; per-task ≈ 20 calls, 500k in / 50k out)
| Stage | What | Runs | in tok | out tok | USD deepseek / 4o-mini / 4o | runner min | docker GB | artifacts |
|---|---|---:|---:|---:|---|---:|---:|---:|
| **P1** | 12-task integration smoke (baseline+memory) | 24 | 12.0M | 1.2M | **$4.6 / $2.5 / $42** | ~240 | ~40 | ~0.3 GB |
| **P2** | 40-task no-memory pilot + oracle O0–O6 on 53 dev | 411 | 205.5M | 20.6M | **$78 / $43 / $720** | ~4,100 | ~60 | ~4 GB |
| **P3** | retrieval-dev R0–R5 (53) + held-out main S0–S6 (58) | 724 | 362M | 36.2M | **$138 / $76 / $1,267** | ~7,200 | ~80 | ~8 GB |

(Task counts come from the sealed split: 53 dev pairs / 58 held-out main pairs; see
`reports/R22_TEMPORAL_AND_LEAKAGE_AUDIT.md`.)

## Approval request (§11) — provide only when all credential-free work is green
**Required to start P1+P2 (clean-room oracle):**
```
R22_READER_PROVIDER      = deepseek | openai
R22_READER_MODEL         = deepseek-chat | gpt-4o-mini | gpt-4o
R22_READER_API_SECRET_NAME = DEEPSEEK_API_KEY | OPENAI_API_KEY
R22_SMOKE_BUDGET_USD     = <cap for P1>
R22_ORACLE_BUDGET_USD    = <cap for P2>
RUN_APPROVED             = RUN_APPROVED
```
**Later, gated on the oracle passing G1–G6:**
```
R22_MAIN_BUDGET_USD      = <cap for P3>
```
- `HF_TOKEN`: **not** required (SWEContextBench is public). Request only if a future gated dataset needs it.
- Docker is **not** requested locally — the official SWE-bench grader is verified on a Docker-capable GitHub
  Actions runner (`ci-r22-grader-smoke.yml`, to be added).
- **Separate** the DeepSeek full upstream-reproduction budget (HOLD) from the R22 clean-room oracle budget
  (request first).

## Recommended default
- **UPSTREAM FULL REPRODUCTION: hold** (exact `-0324` snapshot unavailable; would be `MODEL_DRIFT_REPLICATION`).
- **R22 CLEAN-ROOM ORACLE: request first** — approve P1 + P2 only; gate P3 on the oracle result.
