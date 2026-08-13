# REALBENCH-R1 Held-Out Main Results (§13) — MAIN COMPLETE

**Benchmark:** EvalPlus **MBPP+ v0.2.0** (evalplus 0.3.1), dataset content-hash `bbaa3bec8895…`.
**Model:** `solar-pro2-251215` (temp 0, max 1200 tok, 1 generation, **no repair**) — `returned_models = [solar-pro2-251215]`.
**Grader:** official `evalplus.eval.untrusted_check` + `trusted_exec` ground-truth, Linux (ubuntu-latest).
**Split hash** `c3cbf496cf2f6fb7`; held-out main = **120 targets**, disjoint from source (150) and calibration (48),
near-dups (Jaccard≥0.6) and funcname collisions excluded. Frozen BEFORE any main model call (preregistration seal).

Every target was solved through the **real production path**: HTTP `/v1/solve` (server-assigned arm, client cannot
choose) → durable `solve_jobs` → **separate worker process** → memory retrieval + abstention → Solar coding backend →
**official MBPP+ grader** in the sandbox (routed by `EVALPLUS:<task_id>`) → durable evidence + raw/applied patch.

## Run integrity

- **599 / 600 jobs SUCCEEDED.** 1 `DEAD_LETTER`: **R0 / Mbpp/599** — retries exhausted (infrastructure), in the
  **no-memory baseline** arm, not a model/grader failure. Reported transparently below with a sensitivity analysis.
- `cross_user_private_injection = 0` across all 600 jobs; R0 memory-injected = 0 (DB injected flag == backend payload
  by construction). Exec@1 = 1.000 for every memory arm (R0 = 0.9917 = 119/120, the one dead-lettered job).
- C1–C5 instrument gates recomputed on the main slice: **all PASS** (same as calibration).

## Actual Pass@1 (MBPP+ = passes BOTH base AND augmented plus tests)

| Arm | Pass@1 (as-run, n=120) | Pass@1 (excl. dead-letter, n=119) |
|---|---|---|
| **R0 no-memory (baseline)** | **0.5750** | 0.5798 |
| R2 shared-ungoverned | 0.6167 | 0.6134 |
| R3 shared-governed | 0.6250 | 0.6218 |
| R4 oracle (top-1 always injected) | 0.6333 | 0.6303 |
| R1 private-only | 0.6000 | 0.5966 |

## Primary endpoint — paired R3 − R0

- **As-run (n=120, dead-letter scored 0):** diff **+0.0500**, bootstrap 95% CI **[−0.017, +0.117]**,
  McNemar b=12 / c=6, **p = 0.238**.
- **Paired excl. dead-letter (n=119 — the correct paired estimate, since Mbpp/599 has no R0 observation):**
  diff **+0.0420**, McNemar b=11 / c=6, **p = 0.332**.
- Both: **positive but NOT statistically significant** (CI includes 0; p > 0.2).

## Secondary contrasts

| Contrast | Δ Pass@1 |
|---|---|
| R2 − R0 (does shared memory help at all) | +0.042 |
| R3 − R2 (does the governance/contract format add anything) | **+0.008** |
| R4 − R3 (headroom to a perfect oracle) | +0.008 |
| R1 − R0 (private-only lesson) | +0.025 |

## §14 patch-level transfer (from persisted applied patches, never inferred from Pass@1)

| Arm | memory-induced gains | memory-induced losses | loss classes |
|---|---|---|---|
| R2 | 11 | 6 | 6 PARTIAL_MEMORY_PATTERN_ADOPTION |
| R3 | 12 | 6 | 6 PARTIAL_MEMORY_PATTERN_ADOPTION |
| R4 | 11 | 4 | 4 PARTIAL_MEMORY_PATTERN_ADOPTION |
| R1 | 10 | 7 | 7 PARTIAL_MEMORY_PATTERN_ADOPTION |

Memory produces **both gains and losses** on individual tasks; the net is positive but the losses are real
(injected memory + a different, failing patch). No losses were grader/parser artifacts (0 PARSER_OR_GRADER_FAILURE)
and none were "memory not actually injected" (0 UNRELATED_ERROR) — the injected memory genuinely changed the patch.

## Honest interpretation

1. **This is an actual public-benchmark result.** solar-pro2-251215 solves **57.5%** of held-out MBPP+ with no
   memory, through the full production service path, graded by the official EvalPlus grader.
2. **Memory gives a small, non-significant lift** (~+4 to +6 pp). Even the **oracle** (R4, always inject the single
   nearest verified source lesson) reaches only **63.3%** — a **+5.8 pp ceiling**. On MBPP+, most tasks are either
   solved without help or not helped by a single retrieved lesson, so the achievable memory effect is inherently small.
3. **The governance/contract format adds essentially nothing over a plain shared summary** (R3 − R2 = **+0.008**),
   consistent with the calibration (R3 − R2 = −0.042) and the prior P5.2 finding. Per the frozen preregistration note,
   **R3 − R0 is not presented as evidence for the contract format** — the ungoverned summary captures nearly all of it.
4. Result is consistent between calibration (R3−R0 = +0.06, p=.45) and main (R3−R0 = +0.05, p=.24): **a small,
   directionally-positive, statistically-null memory effect on MBPP+ for this model.**

## Endpoint

**REALBENCH-R1 MAIN COMPLETE** (spec endpoint C): a frozen, preregistered, held-out **official MBPP+** run
completed through the production service path and reported its **actual Pass@1** and paired lift honestly —
no synthetic substitution, no post-hoc benchmark repair, no requirement that the effect be positive.
