# R4 — SWE-Skills-Bench Author Artifact Request (template)

To revive a faithful reproduction (as a NEW experiment `REALBENCH_SWE_SKILLS_R5_FULL_RELEASE`, not a quiet R4
resume), the SWE-Skills-Bench authors would need to release the instance-level corpus + harness that the public
49-row HF release omits. Frame the request as a **reproducibility audit needing a manifest linking the public 49
rows to the paper's ~565 instances** — not merely "please share code".

## Exact artifacts to request
```
- full ~565 task-instance corpus (per-instance, not skill-level representatives)
- official evaluation harness commit or release archive (the repo is currently 404)
- per-instance requirement documents
- per-instance repository URL + immutable commit SHA
- per-instance verifier / acceptance test
- per-instance Docker image digest or Dockerfile
- with-skill / no-skill invocation protocol used in the paper
- a result-to-instance manifest (mapping the paper's per-skill/averaged numbers to specific instances)
```

## On arrival
- Open **`REALBENCH_SWE_SKILLS_R5_FULL_RELEASE`** with a fresh freeze; keep the R4 §0-A technical stop as the
  honest historical record of the 2026-08-16 release state.
- Re-run §2/§3 provenance + evaluator reproduction against the full corpus; only then form the §5 per-skill
  calibration/held-out partition and the calibration gates.

## Do NOT
- Do not synthesize the missing ~516 instances, nor pin repository commits the data omits, nor author the
  verifiers — that is our own benchmark, not SWE-Skills-Bench.
- Do not expand 49 rows to ~565 by repeated trajectories/seeds (10 trajectories ≠ 10 instances).
