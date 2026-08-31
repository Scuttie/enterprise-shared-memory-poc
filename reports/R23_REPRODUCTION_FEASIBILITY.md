# R23 — Reproduction scale and cost accounting (not a gate verdict)

Source: `artifacts/r23/reproduction_cost_grid.json`, generated from the frozen per-arm contract in
`artifacts/r23/r0_budget_lock.json`. The token rates are the inherited 2026-08-31 B0 planning snapshot and must be
re-verified before any paid approval. **Paid/model calls so far: 0.**

## Units are separated

| plan | paired statistical task N | order repeats | task runs | planned grader containers | expected solve calls | expected extraction calls | spendable hard-cap calls |
|---|---:|---:|---:|---:|---:|---:|---:|
| exact primary, AR0/AR2/AR3 | **500** | 3 | 4,500 | 4,500 | 180,000 | 7,500 | 1,132,500 |
| exact full ablation, AR0–AR5 | **500** | 3 | 9,000 | 9,000 | 360,000 | 19,500 | 2,269,500 |
| scaled 120-task primary | **120** | 1 | 360 | 360 | 14,400 | 600 | 90,600 |

The three frozen stream orders are repeated measurements/order-sensitivity runs over the same tasks. They increase
execution cost, but **do not turn paired task N=500 into N=1,500**. A 60/120-task run remains
`SCALED_PROTOCOL_REPLICATION`, never exact reproduction.

## Expected cost versus enforced hard cap

Expected solving assumes 250K input + 25K output tokens and 40 solver calls per task run. Extraction is separate:
AR0/AR1 use 0 calls, AR2 uses 1 expected call, and AR3–AR5 use 4 expected calls; each expected extraction call is
12K input + 1,024 output tokens. These are planning estimates, not limits.

| plan | rate snapshot | expected solving | expected extraction | expected total | spendable hard-cap total |
|---|---|---:|---:|---:|---:|
| exact primary | gpt-4o-mini | $236.25 | $18.11 | **$254.36** | $972.22 |
| exact primary | gpt-4o | $3,937.50 | $301.80 | **$4,239.30** | $16,203.60 |
| exact primary | claude-sonnet | $5,062.50 | $385.20 | **$5,447.70** | $20,840.40 |
| exact full ablation | gpt-4o-mini | $472.50 | $47.08 | **$519.58** | $1,960.76 |
| exact full ablation | gpt-4o | $7,875.00 | $784.68 | **$8,659.68** | $32,679.36 |
| exact full ablation | claude-sonnet | $10,125.00 | $1,001.52 | **$11,126.52** | $42,035.04 |
| scaled 120-task primary | gpt-4o-mini | $18.90 | $1.45 | **$20.35** | $77.78 |
| scaled 120-task primary | gpt-4o | $315.00 | $24.14 | **$339.14** | $1,296.29 |
| scaled 120-task primary | claude-sonnet | $405.00 | $30.82 | **$435.82** | $1,667.23 |

The common per-task envelope is 250 solver calls plus 4 reserved extraction slots, 1,064,000 input tokens, and
108,192 output tokens. Every arm receives that same envelope; arm-specific extraction permissions make unused
capacity unspendable rather than transferable to solver steps. The JSON records both the common equal envelope and
the lower spendable hard cap.

## Grader smoke accounting

The frozen smoke manifest contains 12 repository-stratified targets × `{GOLD, NOOP}` = 24 condition grades.
Frozen image digests exist, but grader containers executed = **0** pending separate EXEC approval. This report does
not claim benchmark/grader viability or a terminal R23 endpoint.
