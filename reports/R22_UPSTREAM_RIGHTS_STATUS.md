# R22-P0.8 §9 — Upstream rights status

This is a factual record, **not** a legal conclusion and **not** a technical grader block.

- The **dataset** (`jiayuanz3/SWEContextBench`, Hugging Face) is **separately declared MIT** per its released
  dataset metadata.
- The **GitHub evaluator repository** (`jiayuanz3/SWEContextBench` @ `31bb04155f52b184bf31b220e3cff0607ac9c953`)
  has **no explicit license file detected**: `LICENSE`, `LICENSE.md`, `LICENSE.txt` all return 404 at the pinned
  commit, and `README.md` contains no license statement.
- The upstream evaluator code is **not vendored or redistributed** by this repository. It is **not** copied into
  the wheel, sdist, Docker image, or any release, and it is **not** modified and redistributed.
- CI uses a **pinned ephemeral checkout only** (`experiments/r22/runtime/scb_official_grader.py`:
  `git fetch --depth 1 origin <pinned-commit>`), verified against
  `artifacts/r22/scb_official_evaluator_lock.json`, and **only if research execution is approved**
  (`R22_SCB_UPSTREAM_EXEC_APPROVED=1`, dispatched with `confirm_exec_approved=EXEC_APPROVED`). Without approval the
  grader raises `UpstreamExecutionNotApproved` and executes nothing.
- **No legal conclusion is claimed** here (no clearance, no license inference).
- **Author clarification of the evaluation-code license is recommended** before any redistribution or product
  inclusion, and before executing the upstream evaluator if institutional policy forbids running unlicensed public
  code.

Because the only thing standing between the verified-ready harness and a live official rerun is this
execution-of-unlicensed-code decision, the P0.8 endpoint is the **compliance** status
**`R22_UPSTREAM_EVALUATOR_EXECUTION_REVIEW`** — explicitly *not* `R22_REAL_PAID_HARNESS_TECHNICAL_BLOCK`.
