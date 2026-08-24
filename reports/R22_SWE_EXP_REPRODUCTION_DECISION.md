# R22 §1 — SWE-Exp reproduction decision (frozen)

Final upstream state for the positive reference `cslsolow/SWE-Exp @ 6b5c92e` (Apache-2.0):

- **Author task-level artifacts unavailable** — the repo ships code + method figures only; no predictions or
  trajectories to regrade (`AUTHOR_ARTIFACT_UNAVAILABLE`).
- **Exact `DeepSeek-V3-0324` snapshot is not pinned in released code** — `workflow.py` uses the provider alias
  `deepseek/deepseek-chat` (temp 0.7), so the exact paper snapshot is resolved provider-side, not in the repo.
- A run with the current `deepseek/deepseek-chat` alias is therefore **not an exact reproduction**.
- A full live rerun (U0 baseline / U1 memory) requires an **approved credential and budget** plus Docker +
  moatless-testbeds grading.
- Any later rerun that does not use the exact `-0324` snapshot **must be labelled `MODEL_DRIFT_REPLICATION`**,
  kept separate from a faithful reproduction and from our own clean-room results.

**Decision:** `UPSTREAM_REPRODUCTION = BLOCKED` is retained for the SWE-Exp sub-task only. It does **not** halt
R22 — all credential-free Stage B/C work (SWE-ContextBench audit, split, schema, GOLD bank, retrieval/oracle
scaffolding, CI) continues, and paid execution is requested separately per `reports/R22_PAID_EXECUTION_PLAN.md`.
