# REALBENCH-R1 Calibration Decision (§12)

Benchmark: **EvalPlus MBPP+ v0.2.0** (evalplus 0.3.1), dataset content-hash `bbaa3bec8895…`.
Model: **solar-pro2-251215** (temp 0, max 1200 tok, 1 generation, no repair). Grader: official
`evalplus.eval.untrusted_check` + `trusted_exec` ground-truth on Linux (ubuntu-latest).
Split hash `c3cbf496cf2f6fb7`. Calibration n=48 targets × 5 arms = **240 jobs, all SUCCEEDED**,
every one traversed HTTP → durable solve_job → separate worker → retrieval/abstention → Solar →
official MBPP+ grader → durable evidence. `returned_models = [solar-pro2-251215]`.

## C1–C5 instrument gates — ALL PASS (these test the INSTRUMENT, not efficacy)

| Gate | Result | Verdict |
|---|---|---|
| C1 grader validity | setup_failures=0, malformed_rate=0.000 (exec1=1.000 all arms); reference 100% pass in ci-realbench-grader | PASS |
| C2 service validity | cross_user_private_injection=0; memory injected into R0=0 (DB injected == backend payload by construction) | PASS |
| C3 dynamic range | R0 Pass@1 = 0.542 ∈ [0.10, 0.85] — MBPP+ is neither floored nor ceilinged for this model | PASS |
| C4 retrieval sanity | R2 injected 89.6%, R3 injected 79.2% (governed abstains more), R4 oracle 100%, R0 0% — abstention + source≠target working | PASS |
| C5 reproducibility | split_hash matches freeze; calibration∩main = 0 | PASS |

## Efficacy readout (NOT a gate; §12 forbids requiring positive lift)

| Arm | Pass@1 |
|---|---|
| R0 no-memory | 0.542 |
| R2 shared-ungoverned | 0.646 |
| R3 shared-governed | 0.604 |
| R4 oracle | 0.604 |
| R1 private | 0.625 |

- Primary **R3 − R0 = +0.0625**, McNemar b=5/c=2, **p=0.453** (not significant); bootstrap 95% CI **[−0.042, +0.167]** includes 0.
- **R3 − R2 = −0.042** (governance/contract format does NOT beat plain shared summary here). Per the frozen
  note, R3−R0 is therefore NOT presented as evidence for the contract format.
- The memory effect on this calibration slice is small and statistically null. **Per §12 a null/negative
  calibration effect is not an instrument failure.**

## Decision

**Instrument VALID (C1–C5 all pass).** Per §12/§13, open the frozen held-out main (120 disjoint MBPP+
targets) **regardless of which memory arm looks best**. The main will report actual Pass@1 and the
paired R3−R0 with no requirement that it be positive. Endpoint target: **REALBENCH-R1 MAIN COMPLETE**.
