# BigCodeBench Dependency & Provenance Audit (§3)

## Official source (no mirror)

| Field | Value |
|---|---|
| Package | `bigcodebench` **0.2.5** (PyPI, official) |
| Dataset | HuggingFace `bigcode/bigcodebench`, version **v0.1.4** (`BIGCODEBENCH_VERSION` in the package) |
| Variant | **BigCodeBench-Instruct** (`instruct_prompt` field) — natural-language instruction interface, per §3 |
| Subset | `full` — **1140** official tasks (exactly the §4 partition sum 300+80+120+80+500+60) |
| License | **Apache-2.0** (permits the required use) |
| Task fields | `task_id, complete_prompt, instruct_prompt, canonical_solution, test (unittest.TestCase), entry_point` |
| Evaluator | `bigcodebench.evaluate.check_correctness` → `bigcodebench.eval.untrusted_check` (self-contained unit tests per task; official resource guards) |
| Resource limits | `max_as_limit=max_data_limit=30*1024`, `max_stack_limit=10`, `min_time_limit=1.0`, `gt_time_limit=2.0` (package defaults, frozen) |
| Execution modes | `--execution [e2b | gradio | local]`; we use **local** grading inside the official image |
| Eval image | `bigcodebench/bigcodebench-evaluate` (Docker Hub, official) |

## Endpoint-A (technical stop) analysis — RULED OUT

- The benchmark, dataset, and evaluator are official, installable, and callable **programmatically**
  (`check_correctness`), exactly like the evalplus MBPP+ path already in production. No mirror, no
  modification of any test or reference solution.
- Grading is deterministic per candidate: `Pass@1 = base test suite passes`. BigCodeBench has one test suite
  per task (no separate "plus" set), so `check_correctness` returns `{"base": (status, details)}`.
- Reference/canonical solutions and unit tests can be isolated: the adapter exposes to the backend ONLY the
  `instruct_prompt`; grading runs server-side via the `BIGCODE:<task_id>` marker.

## Endpoint-B (instrument) risk — the Python-3.10 eval environment

The eval dependency set (`Requirements/requirements-eval.txt`, 73 pinned deps) includes `numpy==1.21.2`,
`tensorflow==2.11.0`, `numba==0.55.0`, `scipy==1.7.2`, `scikit-image==0.18.0`, etc. **These pin the eval
environment to Python 3.10** (they do not build on 3.11+). Consequence for our architecture:

- The ESM service (API + worker) runs on **Python 3.11**; the BigCodeBench **grader cannot import into that
  interpreter**. Grading must run in the official **Python-3.10 eval image** with the full dependency set.
- **Decision:** the paid BigCode CI jobs run **inside `container: bigcodebench/bigcodebench-evaluate`**
  (Python 3.10 + all task deps present). The ESM app + `[postgres,qdrant,artifacts,oidc,embed]` extras are
  installed on top of that image, so the same interpreter runs the worker AND
  `from bigcodebench.evaluate import check_correctness`. This keeps the whole service path intact (HTTP →
  durable job → worker → sandbox → official grader) while using the official, faithful evaluation deps.
- This is verified by `ci-bigcode-grader` (below) BEFORE any paid Solar run. If the official image cannot be
  used in CI, that is a **BIGCODE INSTRUMENT STOP (endpoint B)**, reported honestly — not worked around.

## Provenance probe (`ci-bigcode-grader`, unpaid)

Loads the official dataset inside the eval image, asserts the task count, grades K canonical solutions
(expect PASS) and K corrupted solutions (expect FAIL), and prints `content_hash()` +
`get_bigcodebench_hash()`. Those two hashes + the confirmed count are then written into
`configs/bigcode_r2/bigcodebench_lock.json` (currently `PENDING_CI_PROBE`) and sealed before any model call.

`experiments/bigcode_r2/grader.py` and `adapter.py` are the faithful shims; `localsandbox.py` routes the
`BIGCODE:` marker; `ci_container.py` wires `REPO_PROVIDER=bigcode`.
