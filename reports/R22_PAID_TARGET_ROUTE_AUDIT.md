# R22 §3/§12 — paid target route audit  **[RETRACTED by P0.8]**

> ## ⛔ RETRACTION (R22-P0.8)
> The **`R22_REAL_PAID_HARNESS_TECHNICAL_BLOCK`** conclusion below is **WRONG and withdrawn.**
> P0.7 selected the **wrong evaluator**: it fed frozen SWE-ContextBench *Related* targets to generic
> `swebench==5.0.2`, which expects the enriched SWE-bench `image` field. SWE-ContextBench is evaluated by the
> **benchmark's own** pinned `swebench_memory.harness.run_evaluation` against **official per-instance images**
> `jiayuanz3/swecontextbench:<instance-tag>`.
>
> Verified in P0.8 (pinned commit `31bb04155f52b184bf31b220e3cff0607ac9c953`):
> - Official evaluator **exists**: `swebench_memory/harness/run_evaluation.py` (+ `combine_instances.py`,
>   `build_instance.py`, per-language Dockerfile templates), `evaluation.sh`, `environment.yml`.
> - Official images **exist**: Docker Hub `jiayuanz3/swecontextbench` has 358 tags; **40/40** frozen targets
>   resolve to a `linux/amd64` manifest with an immutable digest (`artifacts/r22/scb_image_manifest.json`).
> - Official case files **exist**: **40/40** frozen targets have a `cases/<subset>/<id>.json`
>   (`artifacts/r22/scb_case_route_manifest.json`); core-row equivalence vs the frozen benchmark row is **40/40**.
>
> Specifically retracted claims:
> - ~~"SWE-ContextBench Related has no official evaluator."~~ → false; `swebench_memory` is the official evaluator.
> - ~~"No official image is published."~~ → false; 40/40 official per-instance images exist with digests.
> - ~~"0/40 in enriched SWE-bench means the tasks are ungradeable."~~ → false; gradeability is judged by the
>   benchmark's OWN evaluator/images, not by presence in the enriched `SWE-bench/*` datasets.
> - ~~"swebench==5.0.2 is the official evaluator for SCB Related."~~ → false; it is the wrong grader.
>
> The one true observation below — that generic `swebench 5.0.2` `make_test_spec` needs an `image` field it cannot
> build from `base_commit` — only proves generic swebench is the **wrong tool** for SCB, not that SCB is ungradeable.
>
> **Current status:** `R22_WRONG_GRADER_SELECTED_PENDING_OFFICIAL_SCB_RERUN`. See the P0.8 audits:
> `reports/R22_SCB_OFFICIAL_EVALUATOR_AUDIT.md`, `R22_SCB_CASE_EQUIVALENCE_AUDIT.md`,
> `R22_SCB_IMAGE_AVAILABILITY.md`, `R22_UPSTREAM_RIGHTS_STATUS.md`.

---

## (Historical, retracted) original P0.7 finding

The generic-swebench probe (`ci-r22-real-grade-probe`, run 32817881771) attempted to grade
`astropy__astropy-14500` and `apache__lucene-13388` with `swebench==5.0.2`:
1. `--dataset_name jiayuanz3/SWEContextBench` → DatasetGenerationError (SCB splits are Experience/Related).
2. A local SWE-bench-format dataset built from the SCB row loads; the no-patch cell grades unresolved; the gold
   cell fails at `make_test_spec` with `KeyError: 'image'`.

P0.7 read this as a benchmark-gradeability block. **That reading was wrong** — it only shows that generic swebench
requires a prebuilt enriched `image` and does not build from `base_commit`. SWE-ContextBench ships its own
evaluator and its own prebuilt images, which P0.7 did not use. The probe workflow is retained as provenance of the
mis-selection only; it is **not** the authoritative SCB grader.
