# R23-B0 — Reproduction scale & cost feasibility

`artifacts/r23/reproduction_cost_grid.json` (prices recorded 2026-08-31; re-verify before paid). No paid call in B0.
Per-run estimate (conservative Mini-SWE-Agent Verified solve incl. accumulated context): ~250K input + ~25K output
tokens; extraction (AR2/AR3/AR5) counted inside the same budget.

| plan | runs | gpt-4o-mini | gpt-4o | claude-sonnet |
|---|---|---|---|---|
| `EXACT_PAPER_SCALE` primary (500 × 3 orders × {AR0,AR2,AR3}) | 4500 | ~$236 | ~$3,938 | ~$5,063 |
| `EXACT_PAPER_SCALE` full ablation (500 × 3 × AR0–AR5) | 9000 | ~$473 | ~$7,875 | ~$10,125 |
| `SCALED_PROTOCOL_REPLICATION` (120 × 1 × {AR0,AR2,AR3}) | 360 | ~$19 | ~$315 | ~$405 |
| `MECHANISM_DEVELOPMENT` (oracle/factorial dev × arms) | sized in O0 | — | — | — |

One official grader Docker container run per (task, arm) = the same run counts; GitHub Actions minutes + Docker
hours scale accordingly. **A 60/120-task subset is `SCALED_PROTOCOL_REPLICATION`, never "exact reproduction".** Three
reader price points are given (cheapest gpt-4o-mini → middle gpt-4o → stronger claude-sonnet); the actual reader is
fixed by the frozen reader-band pilot, not by cost. The full exact ablation on a mid/strong reader (~$8–10k +
thousands of Docker runs) is the honest price of a true reproduction — reported so the scale is not understated.
