# R22 §1 — paid-runner gap audit (before → after)

Facts recorded at the start of P0.5 and the closure state.

| Gap (before) | State | After (this closure) |
| --- | --- | --- |
| `r22-reader-selection.yml` gate real but runner **commented/echo-only** | closed | calls `experiments/r22/reader_band.py --mode real …` + uploads artifact |
| `r22-reader-smoke.yml` P1 runner commented; reader-lock **not verified** | closed | `scripts/r22_verify_reader_lock.py` then `experiments/r22/p1_runner.py --mode real …` |
| `r22-oracle-dev.yml` P2 runner commented; P1-PASS **not verified** | closed | `scripts/r22_verify_p1_pass.py` then `experiments/r22/p2_runner.py --mode real …` |
| `ci-r22-paid-analysis.yml` could skip / `\|\| true` hid failure | closed | fail-closed `scripts/r22_paid_analyze.py`; no failure suppression |
| `experiments/r22/reader_band.py` **missing** | closed | implemented |
| `experiments/r22/p1_runner.py` / `p2_runner.py` **missing** | closed | implemented (+ generic `paid_runner.py`) |
| `experiments/r22/statistics.py` / `mechanism_audit.py` / `information_retention.py` **missing** | closed | implemented |
| reader-lock verifier / P1-integrity verifier **missing** | closed | `scripts/r22_verify_reader_lock.py`, `scripts/r22_verify_p1_pass.py` |

## Reused (not rewritten)
The repository-agent tool design (`list_dir/read_file/search/replace_lines/create_file/submit`) mirrors
`scripts/r7_repo_agent.py`; the OpenAI provider request shape mirrors `scripts/r14_swebench_agent.py`; the real
grader path is the enriched-dataset official swebench harness from `scripts/r22_grader_run.py`. Frozen R14/R7 files
were **not** modified — a new `experiments/r22/runtime/` package holds the shared code.

## Result
No paid workflow contains a commented-out runner or ends after `echo`; the fake-provider full E2E is green
(`ci-r22-paid-harness`); analysis is fail-closed. Endpoint: `R22_PAID_EXECUTION_HARNESS_READY_FOR_APPROVAL`.
