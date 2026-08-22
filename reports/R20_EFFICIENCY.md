# R20 Efficiency

Per-arm means (gpt-4o-mini), 248 tasks each; total ~$6.72 for all six arms.

| arm | mean prompt tok | mean inject chars | mean turns | resolved |
| --- | --- | --- | --- | --- |
| B0 | 18522 | 0 | 9.2 | 19 |
| B1 | 35928 | 4361 | 10.3 | 19 |
| F00 | 31987 | 4506 | 10.2 | 18 |
| F10 | 26590 | 4367 | 8.6 | 23 |
| F01 | 22957 | 0 | 9.3 | 22 |
| F11 | 25788 | 3074 | 8.3 | 23 |

Router ON (F11) injects less than router OFF (F10) — 3074 vs 4367 chars — at equal resolve rate, i.e. the router
trims injected tokens without losing success (a modest efficiency/safety property, not a performance gain).
