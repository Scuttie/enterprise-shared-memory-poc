# R22 — research claim boundary (§2)

R22 keeps four evidence lines strictly separate. None is filled with another line's numbers, and none is filled
from a paid run that did not execute.

| Evidence | Baseline | Memory | Delta | Status |
|---|---:|---:|---:|---|
| Published SWE-Exp | 0.354 | 0.416 | +0.062 | **author report** (arXiv:2507.23361; not our measurement) |
| Our SWE-Exp rerun | — | — | — | **BLOCKED** (no DeepSeek credential / no approved budget / Docker grader) |
| R22 clean-room | — | — | — | **NOT_RUN** (all execution stages paid-gated) |
| Company-native | — | — | — | **NOT_RUN** (runs only if held-out main is positive) |

## Forbidden statements (not made anywhere in R22)
- Presenting the upstream/published numbers as our product result.
- Presenting oracle results as retrieval results.
- Claiming a memory-content effect from a no-memory rise alone.
- Claiming a memory effect without beating shuffled + compute controls.
- Presenting calibration results as main results.

## Current status
Only the **Published SWE-Exp** line carries numbers, explicitly attributed to the authors. Every line that would
require our own model execution is BLOCKED/NOT_RUN pending model credentials + an approved budget — see
`reports/R22_BLOCKER.md`.
