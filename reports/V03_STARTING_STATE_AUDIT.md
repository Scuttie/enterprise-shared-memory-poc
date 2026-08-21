# V03 Starting-State Audit (P6 / R19 — utility-aware shared memory)

Captured at the start of `codex/utility-router-v0.3`, before any product feature work. Purpose: freeze the
baseline so every later change is diffable and the frozen research is provably untouched.

## Git safety (§1)
| Item | Value |
| --- | --- |
| Working branch (new) | `codex/utility-router-v0.3` (worktree at `C:/Users/jewon/esm-v03`) |
| Branched from | `codex/production-service-v0.2` head |
| Start commit (both) | `7fddfb959bef04a6de5f9d528ef9266a723f3740` |
| PR #1 | `#1` OPEN / DRAFT / base `main` — head `284dabf` at audit start, `7fddfb9` after straggler commit; **not merged, not marked ready** |
| PR #2 | to be opened: head `codex/utility-router-v0.3`, base `codex/production-service-v0.2`, DRAFT |
| `main` | untouched |
| `v0.1.0-poc` | untouched |

Straggler commit before branching: added `scripts/r12e_analysis.py`, `scripts/r13_analysis.py` (previously
untracked R12e/R13 analysis tooling) to `codex/production-service-v0.2` so the tree was clean before creating the
worktree. No existing frozen artifact was modified.

## Starting blob hashes (`git hash-object`)
| File | Blob |
| --- | --- |
| README.md | `70b9b59e076aa5fe5303ab519a3f384ce0ed5efd` |
| docs/ARCHITECTURE.md | `51b877e8d3588412eaa422688df9d43791410e49` |
| docs/COMPANY_HANDOFF.md | `a8e0907268f6ff8fe176a0ac245e6b02d3885614` |
| openapi_v1.json | `e520cb264eb6acbf83ccfde8f8f755d395a1917a` |
| pyproject.toml | `8511fb97daa2199401d60e32c0ef1a45ba1feea1` |
| migrations/versions/0013_job_patches.py | `e0370384487bcf3a9e9140bfd51fa8ece42ec72d` |

## Migration head (§5)
Alembic head resolved programmatically = **`0013`** (`0013_job_patches`, down `0012`). P6 experience tables begin
at `0014`. (Chain verified single-headed: revisions 0001→0013, each `down_revision` present except initial.)

## Frozen research (must not mutate — §22)
`reports/` contains 20 frozen R11–R18 / MEMORY_TRANSFER experiment reports; `artifacts/swebench_r14/` holds the
R14–R18 arm data; `docs/*_PREREG.md` the preregistrations. These are DEVELOPMENT_OBSERVED for R19 (§10.1) and are
never mutated. A hash audit of these paths is produced again at V03-R0 to prove non-mutation.

## Surfaces to correct (stale — see V03_DOCUMENTATION_TRUTH_AUDIT.md)
README/ARCHITECTURE/COMPANY_HANDOFF describe the old SQLite/demo PoC and assert an efficacy claim that R14–R18
refuted. STATUS.yaml is introduced this commit as the single machine-readable source of truth; ci-docs enforces it.

## Workflows
54 workflows at start (recorded in `docs/STATUS.yaml.workflow_count`; ci-docs asserts parity).
