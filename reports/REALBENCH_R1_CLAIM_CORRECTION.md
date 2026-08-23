# REALBENCH-R1 Claim Correction (REALBENCH-R2 §1)

This corrects how the frozen REALBENCH-R1 result is described. **No frozen R1 task, result, or manifest is
changed** — `artifacts/realbench_r1/*` and `reports/REALBENCH_R1_MAIN_RESULTS.md` are byte-for-byte intact
(seal `ci-realbench-seal` still green). Only labels, causal wording, the patch classifier, and gate-computation
code are corrected here, going forward.

## 1.1 R4 renamed — it is NOT an oracle

| Before | After |
|---|---|
| `R4` name `ORACLE_GOVERNED`, docstring "oracle … isolate retrieval headroom" | `R4` name **`ALWAYS_INJECT_TOP1`** |

**Actual R4 behavior:** the *current retriever's* top-1 source is injected with the abstention threshold
disabled (`tau_abs=0.0`). The top-1 may be irrelevant. R4 measures "always inject the nearest source under
the frozen neutral projection" — **not** a perfect/relevance oracle and **not** a theoretical ceiling. The
R1 main number previously described as an "oracle ceiling (+5.8pp)" is really the **always-inject-top-1**
effect. A true relevance oracle (evaluator-labelled source) does not exist in R1; it is introduced as a
separate diagnostic arm (R1.1 **D8 TRUE_ORACLE_RELEVANT**, BigCode **M2 TRUE_RELEVANT_SELECTED**).

`arm.code` stays `"R4"` so the frozen result/manifest keys are unchanged; only the descriptive `.name` and
docstring changed (`.name` is not hashed in any sealed manifest — verified: seal still passes).

## 1.2 Corrected causal claim

**REALBENCH-R1 established:**
- a small **directional** shared-memory lift (R3−R0 = +0.050 on 120 held-out MBPP+ targets);
- **no statistically significant** primary result (95% CI [−0.017, +0.117] includes 0; McNemar p=0.238);
- **no meaningful governed-format advantage** (R3−R2 = +0.008);
- task-level **gains and losses** (heuristic count 12 gains / 6 losses for R3).

**REALBENCH-R1 did NOT establish:**
- a **relevant-memory causal effect** — R1 had no relevance control (no shuffled-matched negative, no
  evaluator relevance oracle); a shared summary could help via generic extra context rather than relevance.
- **true cross-user transfer** — R1 seeded one synthetic org+user per arm; source and target were not
  distinct real users. R1 did not demonstrate source-user→target-user transfer.
- **production semantic-retrieval performance** — R1 used `DeterministicTestEmbedder`, not the pinned
  production embedding model. R1 retrieval numbers do not characterize the deployable retriever.
- **contract-format efficacy** — R3−R2≈0, and format was confounded with wording length; R1 cannot claim
  the governed contract format helps.

These four are exactly the gaps REALBENCH-R2 is designed to close (relevance control, real multi-user
transfer, production embedder, same-source format contrast).

## 1.3 Patch-adoption classifier replaced (see REALBENCH_R1_PATCH_FORENSICS.md)

The R1 heuristic labelled **every** changed-and-failing memory-arm patch `PARTIAL_MEMORY_PATTERN_ADOPTION`.
That is not evidence of adoption. It is replaced by `experiments/patch_forensics.py`, which classifies a loss
only when the failing patch contains a **new** source code element (import / API / control-flow / operation),
proven by AST comparison against the source memory and the no-memory patch. Classes now include
`UNRELATED_IMPLEMENTATION_ERROR`, `PARSER_OR_APPLY_FAILURE`, and `GRADER_FAILURE`. Because the R1 runner did
**not** persist applied patches into the results artifact, the R1 main losses **cannot be reclassified
offline**; evidence-based forensics are produced on the R1.1 diagnostic (which persists patches) and on
BigCode-R2. The R1 heuristic "transfer" field is marked SUPERSEDED in `analysis.py`.

## 1.4 Gate computation corrected

The R1 runner hard-coded `"pass": True` for C4 (retrieval) and C5 (reproducibility). This is replaced by
run-local predicates:
- **C4** now asserts `R0_injected == 0` (computed) and lists the deeper canonical-validity /
  augmented-tests-never-in-memory guarantees explicitly as `SEPARATE_CI_INVARIANT_VERIFIED` (enforced by the
  `ci-realbench-*` workflows), rather than claiming the paid run recomputed them.
- **C5** now asserts the run's `split_hash == freeze.json split_hash` (read from the committed freeze) and
  `calibration ∩ main == 0`, both computed.

For the frozen R1 artifact these computed predicates are in fact all true (R0 injected = 0; split_hash
`c3cbf496…` matches; cal∩main = 0), so the correction does not change the R1 conclusion — it stops the code
from *asserting* a pass it did not compute.
