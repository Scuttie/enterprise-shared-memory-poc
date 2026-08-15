# R3 §16 — Calibration Decision: §0-C CALIBRATION STOP

## Decision
**CALIBRATION STOP.** The R3 instrument fails the §16 **G3 dynamic-range** gate: no-memory Pass@1 = **0.98** on
the calibration split (and 0.925 on discovery), far above the required [0.10, 0.90] band. Per the frozen §16
rule ("if any technical gate fails: CALIBRATION STOP; main is not run"), the **confirmatory main (M0–M6, §17)
and its safety subset (§20) are NOT run.**

## Why this is the correct, honest endpoint
- solar-pro2 solves DS-1000 completion-mode tasks at ~0.93–0.98 with no memory (the completions are genuinely
  correct; see R3_REPRESENTATION_DISCOVERY.md). At that base rate there is essentially no headroom for any memory
  representation to demonstrably improve correctness.
- Running the confirmatory main anyway would (a) violate the preregistered §16 gate, and (b) only yield a
  ceiling-confounded H1/H2 that could not distinguish "representation doesn't help" from "no room to help".
- The gate did its job: it caught a benchmark/model mismatch (DS-1000 too easy for this model) **before** an
  uninterpretable confirmatory run — exactly the §16 design intent.

## What R3 established (valid despite the stop)
1. **§21-C achieved is a CALIBRATION STOP** (not a confirmatory-main completion). The primary endpoint is the
   honest gate decision, not a p-value.
2. **Discovery — real null representation effect** (with injection audited to 82/82 per arm after fixing a
   two-part oracle-injection bug): best RelevantBundleLift +0.008 (noise); no bundle across the full
   actionability ladder (prose → API card → condition-action → procedural → AST-edit → diff-template → property
   spec → contrast → hybrid → raw trace) beats the shuffled-matched baseline. This replicates R1/R2 at the
   representation level, but is **confounded by the ceiling** and so is reported as suggestive, not confirmatory.
3. The **service path, official evaluator (reproduced 100%), multi-user source bank (183 verified), canonical
   memory, renderers, and injection mechanism are all validated** — the infrastructure is sound; the blocker is
   purely the benchmark/model dynamic range.

## What would be needed to obtain a confirmatory result (future, requires REALBENCH_ACTIONABLE_MEMORY_R4)
A benchmark/model pairing with no-memory Pass@1 in-band (e.g. a harder benchmark, a harder predeclared DS-1000
stratum frozen *before* discovery, or a weaker/temperature-varied model). Changing the task selection now — after
seeing the ceiling — is forbidden (§22/§26) and would require a new preregistration (R4). **No such change is
made here.**

## Not run (consequences of the stop)
- §17 confirmatory main (M0–M6), §18 H1/H2 hypotheses — NOT run.
- §20 safety subset — NOT run (main-path; also uninterpretable at ceiling).
- §15 retrieval-threshold development — moot for the (un-run) M4 arm; the abstention default was used only for the
  calibration C3 arm.
