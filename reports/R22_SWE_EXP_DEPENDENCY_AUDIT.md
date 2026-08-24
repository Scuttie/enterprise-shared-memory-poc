# R22 — SWE-Exp dependency + reproduction-readiness audit

Source: `third_party_r22/swe-exp` @ `6b5c92e`. This audit determines what §3.1 (author-artifact recalc, no model
calls) and §3.3 (full paired reproduction) require, and whether they can execute here.

## §3.1 Author-artifact recalculation
- The repository ships **no** predictions/trajectories/patches. `assets/` contains only method figures
  (`SWE-Exp3.png`, `SWE-Exp4.png`, `method.png`). No `*.jsonl`, `all_preds`, or results directory exists.
- Therefore there is nothing to regrade against the authors' reported per-task outcomes.
- **Verdict: `AUTHOR_ARTIFACT_UNAVAILABLE`.**

## §3.3 Full paired reproduction (U0 baseline / U1 memory) — dependency chain
1. **Model API**: `deepseek/deepseek-chat` via `litellm==1.72.9` — requires a **DeepSeek API key** (paid).
   The exact snapshot `DeepSeek-V3-0324` from the paper is not pinned in code (provider alias).
2. **Grader**: `moatless-testbeds` (`git+…@91938b8…`) — a **Docker-based** SWE-bench Verified evaluation harness
   (per-instance containers). Requires Docker + image pulls.
3. **Embedder**: `intfloat/multilingual-e5-large-instruct` — HF model download.
4. **Engine**: `moatless-tree-search==0.0.4`, `instructor==1.9.0`, `sentencepiece==0.2.0`.

## Can it run in this environment?
No. See `reports/R22_BLOCKER.md`. In short:
- No `DEEPSEEK_API_KEY` / no reader-model credential of any kind is present.
- No approved budget: `R22_UPSTREAM_BUDGET_USD` and `RUN_APPROVED` are unset (§3.3 requires the budget env var and
  refuses to run when the approved amount would be exceeded; §21 makes exceeding the paid budget a hard stop).
- SWE-bench grading needs Docker + the moatless-testbeds infrastructure.

Per §3.3: "exact model snapshot을 호출할 수 없으면 `UPSTREAM_MODEL_SNAPSHOT_UNAVAILABLE`로 기록한다." Both the
snapshot-unavailability and the unapproved cost gate apply.
