# R7 §4 — G1 No-Memory Pilot → R7-G1 INSTRUMENT STOP (floor)

The G1 dynamic-range gate on the frozen 40 targets (10/language) with the pinned reader (`solar-pro3-260323`,
no memory, temperature 0, one trajectory) on the audited SWE-PolyBench Verified instrument. Definitive clean run
`32046661844`. Result: `artifacts/swe_polybench_r7/G1_pilot_result.json`.

## Gate result — clean run, substantive gate fails
| gate | requirement | observed | verdict |
|---|---|---|---|
| G1a technical terminal | ≥ 38/40 | **40/40 graded** | PASS |
| G1b evaluator/env failures | ≤ 2/40 | **0/40** | PASS |
| G1c target/verifier leakage | = 0 | **0** | PASS |
| **G1d no-memory resolved** | **∈ [4, 28]** (rate [0.10,0.70]) | **1/40 = 0.025** | **FAIL (floor)** |

→ **R7-G1 INSTRUMENT STOP.** The reader is below the measurable band on this instrument. Per protocol the
memory arms (M0–M4) and the frozen main are **NOT run**; per §4 we do **not** try another Solar model, reselect
tasks, change the tool budget, or switch benchmarks.

## Why this is a legitimate floor, not a harness artifact
The run is technically clean — every task reached an official graded outcome, **zero** infrastructure/evaluator
failures, **zero** leakage — so the only failing gate is the substantive one (the resolved rate itself), which is
exactly what an instrument stop should hinge on. Supporting evidence:
- **The full pipeline is validated end-to-end.** G0 smoke passed 8/8 across all four languages; in G1 the reader
  actually resolved **`prettier__prettier-3515`** (resolved=True via the official evaluator), proving pull →
  extract → agent → patch → official grade works and can produce a genuine pass.
- **The floor is a reader-capability limit.** solar-pro3 produced a valid (applicable) patch on only **5/40**
  tasks and resolved **1**. The dominant failure is intrinsic **degenerate repetition**: on tasks it cannot
  localize, the model repeats the *identical* tool call for many turns (observed turns 29–40 repeating one
  search/read), never pivoting to an edit — and this begins *before* any scaffold guard engages, so it is the
  model's behavior, not the harness restricting it.
- **The scaffold is fair.** It offers search/read/line-based `replace_lines`/`edit_file`/`create_file`, tiered
  force-edit, loop-nudges, and a submit-without-edit block. Eight harness iterations were needed, but every fix
  corrected a *harness* defect (inverted patch-apply check, missing image tag for grader reuse, over-strict path
  guard, unenforced tool restriction, exact-string→line edits, API rate-limit backoff, early-submit escape); the
  final run is clean. Further engineering to break the model's repetition loops would cross into
  *strengthening the reader to force it in-band*, which §11 forbids.

## Cross-milestone finding (R3 ↔ R5/R6 ↔ R7): the Goldilocks wall persists
Measuring a memory/skill effect needs a reader in a measurable band. The available Solar readers keep landing out
of range:
- **R3 (DS-1000 + Solar-pro2): CEILING** (0.98) → calibration stop.
- **R5/R6 (SkillsBench + Solar-pro2/pro3): FLOOR** (0.00, even with the official skill) → instrument/viability stop.
- **R7 (SWE-PolyBench Verified + Solar-pro3): FLOOR** (0.025) → instrument stop.
SWE-PolyBench itself is in-band for capable agents (leaderboard: Aider+Sonnet ~16%, Amazon Q ~29%, GPT-5/Opus
33–51%) — the floor is **specific to solar-pro3 as a repository agent**, not the instrument. The company reader
(`COMPANY_REPLICATION = PENDING_CONFIGURATION`, GLM not guessed) or a stronger coding agent remains the documented
revive path under a new preregistration.

## Preserved / not run
- Frozen: G0 official manifest (382 IDs), 8 GHCR digests, reader lock, G1 definitive result + all intermediate
  runs (ratelimited_v1, v2_partial, v7_earlysubmit) kept for the record.
- **Not run:** source bank (§5), relevance labelling (§6), memory arms M0–M4 (§7), primary/secondary endpoints
  (§8), the powered main (§9). No confirmatory memory claim is made.
- **R1–R6 frozen; `main` d56d178; PR#1 draft/OPEN; version 0.2.0.dev1; P6 not started.** No official
  task/test/verifier modified; verifier & gold never exposed to the agent; no synthetic instances; no benchmark
  switch to flee the result.
