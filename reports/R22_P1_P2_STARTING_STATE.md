# R22 P1/P2 continuation — starting state (verified live)

| Item | Value |
| --- | --- |
| Branch / HEAD | `codex/r22-stage-aligned-memory` @ `4995b9a` (descends from 4995b9a ✓) |
| PR #16 | OPEN / DRAFT (base main) |
| main | `ce10ab49586db7a859fbe5cca93051b93f9f5b55` — UNCHANGED |
| tag `v0.3.0-rc1` | `c1741c6d635bc97e470ea553753c143888a0c0be` — UNCHANGED |
| R22 main seal (v2) | `dd79f3d2af349bc7e4461222206150611bc046b121d8e2d39b18c65669152ddc` |
| R22 oracle freeze | `100d7caa…` |
| Worktree | clean before continuation |
| **Paid API calls before continuation** | **0** |
| Existing R22 CI | 7/8 credential-free green; `ci-r22-grader-smoke` was the one block |
| Current grader blocker | 12-task mixed smoke could not grade via a single `--dataset_name` |

## Paid-approval gate (checked live) — ALL UNSET
`RUN_APPROVED`, `R22_READER_PROVIDER`, `R22_READER_MODEL`, `R22_READER_API_SECRET_NAME`,
`R22_SMOKE_BUDGET_USD`, `R22_ORACLE_BUDGET_USD`, `DEEPSEEK_API_KEY`, `OPENAI_API_KEY` — **none present**.

Consequence: **P1 and P2 cannot run** (§4.1/§4.2/§12 forbid any paid call without `RUN_APPROVED` + budget + one
exact reader). This continuation therefore executes only the credential-free G0 (mixed-grader recovery) and stops
at a grader/approval endpoint. No model call is made.
