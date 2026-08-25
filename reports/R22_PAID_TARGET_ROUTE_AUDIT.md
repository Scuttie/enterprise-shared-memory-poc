# R22 §3/§12 — paid target route audit + grading feasibility (TECHNICAL BLOCK)

## Route audit (`artifacts/r22/paid_target_routes.json`)
- Unique frozen paid targets (reader-band/P2 dev 40 + P1 smoke 12): **40 distinct**.
- Present in the pinned enriched prebuilt-image datasets (`SWE-bench/*`): **0 / 40**.
- All 40 are SWE-ContextBench **Related** instances with the SWE-bench schema (repo/base_commit/test_patch/
  FAIL_TO_PASS/PASS_TO_PASS/version/environment_setup_commit) but **no prebuilt `image`**.

## Decisive grading probe (`ci-r22-real-grade-probe`, run 32817881771)
Attempted to grade one python (`astropy__astropy-14500`) and one multilingual (`apache__lucene-13388`) target with
the pinned official `swebench==5.0.2`:
1. `--dataset_name jiayuanz3/SWEContextBench` → **DatasetGenerationError** (SCB splits are Experience/Related, not
   the `test` split swebench expects). This is why §4 forbids the SCB dataset name in the invocation.
2. A LOCAL SWE-bench-format dataset built from the SCB row **loads**, and the no-patch cell is correctly graded
   unresolved (empty patch short-circuits). But the gold cell fails at spec time:
   **`swebench/harness/utils.py make_test_spec → image=instance["image"] → KeyError: 'image'`.**

## Root cause (why this is a fundamental block)
- **swebench 5.0.2 requires a prebuilt `image` field and does NOT build images from `base_commit`.** SCB Related
  rows have no `image`, and no official `sweb.eval.x86_64.*` image is published for them.
- The 40 frozen targets are **absent** from the enriched prebuilt-image datasets (0/40).
- The **SWE-ContextBench evaluation code has no license** (established in R22 §2) and cannot be vendored to grade
  the Related targets.
- Therefore the frozen oracle targets **cannot be graded by the pinned official SWE-bench harness credential-free**.
  Per §3 rule 6 / §12: **`R22_REAL_PAID_HARNESS_TECHNICAL_BLOCK`**.

## What would unblock it (not attempted — outside credential-free scope)
1. An **official, licensed** SWE-ContextBench grader/image set for the Related targets; or
2. SWE-ContextBench Related instances **published as prebuilt swebench images** (with the `image` field); or
3. Re-scoping the oracle target set to instances that **exist in the enriched `SWE-bench/*` prebuilt datasets**
   (a benchmark-design change to a NEW, non-frozen manifest — not a silent edit of the frozen R22 set).

The paid-execution HARNESS CODE is complete and correct (real CLIs, official grader adapter, replay provider,
evidence, budget); the block is the **benchmark's gradeability**, not the harness.
