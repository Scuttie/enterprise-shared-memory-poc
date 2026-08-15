# R3 §4 — DS-1000 Dependency & Evaluator Audit

Primary new confirmatory benchmark for R3: the **official DS-1000** (Lai et al., ICML 2023). Chosen because it is
API-heavy, library/precondition-sensitive, suits API cards / executable properties / edit schemas, and is
independent of the MBPP+ (R1) and BigCodeBench (R2) target sets. All facts below were verified from official
sources on 2026-08-15; the machine-readable lock is `configs/actionable_memory_r3/ds1000_lock.json`.

## Provenance (pinned)
| item | value | source |
|---|---|---|
| Code repo | `xlang-ai/DS-1000` | GitHub |
| Code commit (pin) | `b39aab71da6d23ef8d3cac59a7c5f834516ab334` | GitHub API `/commits/main` |
| Release tag | none (pin by commit) | GitHub `/tags`, `/releases` |
| HF dataset | `xlangai/DS-1000` (org has **no hyphen**) | HF API |
| HF revision (pin) | `4416080ac5cb80bdf7576aefb8f9a0b4d5426a44` | HF API |
| Data file | `data/ds1000.jsonl.gz` (gzip JSONL, 418,089 B) | repo @ commit |
| Tasks | **1000** | counted from data file |
| License (code & data) | **CC-BY-SA-4.0** | GitHub `license.spdx_id`, HF `cardData.license` |

Library breakdown (counts from the data file): Pandas 291, Numpy 220, Matplotlib 155, Sklearn 115, Scipy 106,
Pytorch 68, Tensorflow 45. Perturbation: Origin 452, Semantic 234, Difficult-Rewrite 162, Surface 152.

## Evaluator (reproduced, not reimplemented)
- Record fields: `prompt`, `reference_code`, `code_context`, `metadata{problem_id, library, perturbation_type,
  library_problem_id, perturbation_origin_id, test_case_cnt}`.
- **Completion mode only** (insertion/infilling removed upstream). Program assembly (verbatim):
  `program = "code = " + repr(answer) + "\n" + code_context`; `code_context` defines `test_execution(solution)`
  and optionally `test_string(solution)` and invokes them.
- Grading entrypoint: **`execution.check_correctness(program, timeout=120, completion_id=id)`** in the upstream
  repo; score = `1 if result['passed'] else 0`. Per-task **`multiprocessing.Process` isolation is mandatory**
  (stateful tensorflow/matplotlib), timeout via `signal.setitimer(ITIMER_REAL)` → **Linux-only**.
- We call the **official `execution` module unchanged** (cloned at the pinned commit, put on `PYTHONPATH`);
  `experiments/actionable_memory_r3/ds1000_grader.py` only assembles the completion program and returns
  pass/fail. Benchmark tests are never modified (§26 hard stop).

## Environment (official)
Conda env `ds1000-3.10` from the repo `environment.yml` (no `requirements.txt`): python 3.10; numpy 1.26.4,
pandas 1.5.3, scipy 1.12.0, scikit-learn 1.4.0, matplotlib 3.8.4, pytorch 2.2.0 (cpuonly), tensorflow-cpu 2.16.1,
xgboost 2.0.3, gensim 4.3.2, seaborn 0.13.2, statsmodels 0.14.1 (+ pip datasets, tqdm).

## Reproduction gate (this milestone)
Workflow `ci-r3-official-grader.yml` clones DS-1000 @ the pinned commit, builds the official env via micromamba,
and runs `scripts/r3_ds1000_reference_repro.py`: it feeds each task's **`reference_code`** as the completion
answer through the official `check_correctness` and asserts the reference passes at **≥ 0.99** (per-process,
16 workers, mirroring `test_ds1000.py`). It also verifies the task count (1000) and records the data-file
sha256 + an order-independent content hash (both written into the lock as the frozen dataset fingerprint).

**Decision rule:** if the reference solutions do not reproduce (< 0.99), the official evaluator is not faithfully
reproduced here → **§0-A TECHNICAL STOP**; no substitute benchmark is used (§4/§26). Result recorded in
`artifacts/actionable_memory_r3/ds1000_reference_repro.json` and this report is updated with the measured rate.

## Not verified (honest)
No explicit `matplotlib.use('Agg')` or TF-determinism block was found in `execution.py`; per-process isolation
is the mechanism upstream relies on. Recorded in the lock under `not_verified`.

## STATUS — GATE PASSED
`ci-r3-official-grader` run `31882070895` (public repo, micromamba env from the official `environment.yml`):
- **Reference reproduction = 1.0000 (1000/1000)**, every library 100% (Pandas 291, Numpy 220, Matplotlib 155,
  Sklearn 115, Scipy 106, Pytorch 68, Tensorflow 45). 0 failures.
- Data fingerprint verified: `data_sha256 = e8c6daa9…` (matches lock), order-independent
  `content_hash = 3fd0b7aef93ea709…`, task_count 1000.
- Artifact `artifacts/actionable_memory_r3/ds1000_reference_repro.json`.

The official evaluator is faithfully reproduced (≥0.99 gate met at 1.00) → **no TECHNICAL STOP**. Proceed to §5
partition freeze (done, `split_hash e16bfb852f7395cb`) and R3-M0 (canonical memory + multi-user source bank).
