# Release result audit (offline; no API calls)

Corrections applied to every release-facing summary:

## Acceptance-gate count — corrected to **3/5** (was mis-stated as 4/5)
Recomputed from committed definitions + raw ledger:
| gate | result | reason |
|---|---|---|
| M7 perf (cache) | **FAIL** | P5 cache 13/16 (>=12 ok), flip 5/8 (>=5 ok), but P5-P1 cache = +3 (**< +4**) |
| M7 all-domain | **FAIL** | **P5 malformed 3/32 = 9.4% > 2% threshold** (P5 within 2 of P7 ok; scope-viol 0 ok) |
| positive control (internal_api) | **PASS** | P5 not >2 below P1; flip 8/8 |
| governance | **PASS** | invalid compiler output 0; refusals 8/8 |
| safety-development | **PASS** | P5 invalid-injection 0/8; within 1 of P0; old-fix 0/8 |
**Total: 3/5 passed.** A failed preregistered threshold is a failure, not an artifact.

## Threshold wording
"P5 improved over P1 by three cache world tasks, narrowly missing the predeclared four-task engineering
threshold." (The earlier phrase "threshold artifact" is withdrawn.)

## Token / latency coverage
The frozen ledger logs token_usage + latency for **288/384** logical calls (N2 256 + safety 32). **N1 call
usage (96) and latency were NOT logged** and are not recoverable without new API calls (forbidden). The
**57,030 completion tokens is a partial subtotal** (N2 + safety only), not total pilot usage; the missing
N1 usage is not estimated. No total efficiency/cost claim is made.

## DecisionExecutionConsistency
N1 was 32/32 for P5 and P5 Pass@1 was 29/32; therefore DecisionExecutionConsistency = 29/32 **equals** P5
Pass@1 in this experiment and is not independent evidence.

## Verdicts
Product architecture supported as a design direction, but the preregistered acceptance suite was not fully
passed. Implementation: demo-complete, not production-ready. Research: strong domain-scoped evidence for
interface-aligned literal memory rendering; no general coding-memory efficacy claim.
