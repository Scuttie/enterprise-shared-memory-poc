# R22 §5 — paid v2 cost plan (recomputed)

All values computed by `scripts/r22_recompute_paid_costs.py` (no hard-coded decimals). Hard per-run cap: 800000 in / 80000 out tokens. Prices per Mtok checked 2026-08-25.

| model | per-run | reader-band 40 | P1 84 | P2 total 280 | selected-reader total 364 |
|---|---:|---:|---:|---:|---:|
| deepseek-chat | $0.304 | $12.160 | $25.536 | $85.120 | $110.656 |
| gpt-4o-mini | $0.168 | $6.720 | $14.112 | $47.040 | $61.152 |
| gpt-4o | $2.800 | $112.000 | $235.200 | $784.000 | $1019.200 |

Run counts: reader-band 40/candidate · P1 84 · P2 analyzed 280 (O0 40 reused → 364 new for the selected reader). Primary contrasts: Q1 O5−O2 · Q2 O5−O4 · Q3 O6−O5. Product candidates O4/O5/O6 (O3 is an oracle upper bound, not selectable).

Approval vars: `R22_READER_SELECTION_BUDGET_USD`, `R22_SMOKE_BUDGET_USD`, `R22_ORACLE_BUDGET_USD`, `RUN_APPROVED`. **`R22_MAIN_BUDGET_USD` must remain unset (P3 withheld).**