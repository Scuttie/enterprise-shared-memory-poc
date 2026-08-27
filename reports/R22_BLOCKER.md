# R22 — precise blocker and stage verdicts

## Valid endpoint reached
**A. R22-UPSTREAM-REPRO-COMPLETE — via proven blocker** (§0 allows "또는 정확한 blocker를 증명"; §3.1/§3.3).
Every downstream stage (B/C/D/E) additionally requires paid model execution that is likewise blocked.

## The gate (measured, not assumed)
Probed at start of R22:

| Requirement | State |
| --- | --- |
| `R22_UPSTREAM_BUDGET_USD` | **unset** (no approved upstream budget) |
| `R22_MAIN_BUDGET_USD` | **unset** |
| `RUN_APPROVED` | **unset** |
| `DEEPSEEK_API_KEY` | **unset** (SWE-Exp policy model) |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | **unset** (no alternative reader) |
| `HF_TOKEN` | unset (public MIT dataset may still download) |
| Docker + moatless-testbeds grader | not provisioned |

Network to GitHub is available (SWE-Exp remote HEAD == pinned `6b5c92e`), which is why the **credential-free**
upstream audit below completed.

## Why each stage is blocked (no way to reach a numeric result)
- **§3.1 author-artifact recalc** → `AUTHOR_ARTIFACT_UNAVAILABLE`: SWE-Exp ships only code + PNG figures; no
  predictions/trajectories to regrade (no model calls would have been needed, but there is nothing to grade).
- **§3.3 upstream rerun (U0/U1)** → `UPSTREAM_MODEL_SNAPSHOT_UNAVAILABLE` + `BUDGET_NOT_APPROVED`: needs a
  DeepSeek credential (exact `-0324` snapshot not even pinned in code) + Docker grading + an approved budget.
- **§5 reader selection pilot** (40 dev tasks, no-memory) → cannot run: no callable reader model of any kind.
  Per §5 this is an instrument failure (`R22-INSTRUMENT-STOP`) — here it is stronger than "no model in band":
  there is **no** callable model to place in the band at all.
- **§13 oracle**, **§14 retrieval-dev**, **§16 held-out main**, **§18 company bridge** → all require the reader +
  budget → **NOT_RUN**.

Per §21, "유료 호출 승인액 초과" is a hard stop; with a zero/unset approved budget, initiating any paid call
would exceed it. This is a sanctioned cost/credential stop, not an arbitrary intermediate halt.

## What WAS completed (credential-free, real deliverables)
- Git preserved: `main` == `ce10ab4…f5f5b55`, tag `v0.3.0-rc1` == `c1741c6…` (unchanged).
- R22 worktree/branch `codex/r22-stage-aligned-memory` off `main`.
- SWE-Exp pinned + **license = Apache-2.0** + **config verified from code** (not just the paper) — frozen in
  `artifacts/r22/upstream/swe_exp_lock.json` with per-file sha256.
- Claim boundary (§2) established with only the author-reported line populated.

## Separated verdicts (§23)
- `UPSTREAM_REPRODUCTION = BLOCKED` (AUTHOR_ARTIFACT_UNAVAILABLE + UPSTREAM_MODEL_SNAPSHOT_UNAVAILABLE + BUDGET_NOT_APPROVED)
- `ORACLE_INFORMATION_VALUE = INSTRUMENT_STOP` (no callable reader to instrument)
- `DYNAMIC_RETRIEVAL = NOT_RUN`
- `HELD_OUT_MEMORY_EFFECT = NOT_RUN`
- `COMPANY_NATIVE_BRIDGE = NOT_RUN`

## To unblock (what a maintainer must provide)
1. A callable reader-model credential — ideally `DEEPSEEK_API_KEY` for a faithful SWE-Exp rerun, or an alternative
   reader (recorded as `MODEL_DRIFT_REPLICATION`, kept separate from a faithful reproduction).
2. `R22_UPSTREAM_BUDGET_USD` (and later `R22_MAIN_BUDGET_USD`) + `RUN_APPROVED`, with a per-stage cost estimate
   approved before each paid run.
3. Docker + the moatless-testbeds SWE-bench grader (or the official SWE-bench harness in a paid CI runner; note
   the repo's Actions quota history).

With those, the next credential-free step (SWE-ContextBench §4 dataset audit + clean-room adapter + StageMemoryRecord
schema §7–8) proceeds, then the paid ladder §3.3 → §5 → §6 → §13 → §14 → §16 executes in order behind the cost gate.
