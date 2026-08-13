# REALBENCH-R1 — dependency / provenance audit

Uses the **official EvalPlus** implementation of **MBPP+** — no unofficial mirror, no modified tests, no
silent fallback to the original limited MBPP base tests (MBPP+ = base + the official augmented `plus` tests).

| field | value |
|-------|-------|
| benchmark | MBPP+ (EvalPlus) |
| package | `evalplus` |
| package version | **0.3.1** (`pip install evalplus==0.3.1`) |
| MBPP+ dataset version | **v0.2.0** |
| dataset source | official release `github.com/evalplus/mbppplus_release` v0.2.0 `MbppPlus.jsonl.gz` |
| dataset hash | `92743def42b30b354a30898e4fa33fb0` (`get_mbpp_plus_hash()`) |
| tasks | 378 |
| Python | 3.11 |
| evaluator | `evalplus.eval.untrusted_check` (candidate) + `evalplus.gen.util.trusted_exec` (ground-truth from the official canonical solution) |
| grader platform | **Linux only** — `evalplus.eval.unsafe_execute` imports the Unix `resource` module; the local host is Windows, so ALL grading runs in CI (`ci-realbench-grader`, `ci-realbench-adapter`, and the paid calibration/main workflow, all `ubuntu-latest`) |
| license | Apache-2.0 (EvalPlus) + MIT (MBPP) |

Pass@1 (MBPP+) requires BOTH the base and the augmented (`plus`) tests to pass. Ground-truth expected outputs
are computed server-side from the official canonical solution and are NEVER exposed to the coding backend.

The evalplus whole-dataset ground-truth cache cannot pickle rare `re.Match` outputs; we compute ground-truth
per task in-memory via the official `trusted_exec` (same code path, no cache), so the official evaluator logic
is unchanged.
