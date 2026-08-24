# R22 §2 — official grader smoke (design + status)

Goal: prove the official SWE-bench grader **discriminates** — 12 fixed tasks resolve with the gold patch and stay
unresolved with no patch — with **no model calls** and **no benchmark-test modification**.

## Prepared (deterministic, credential-free)
- 12 tasks across **12 distinct repositories** (dev-only sources), `artifacts/r22/grader_smoke_manifest.json`.
- `artifacts/r22/gold_predictions.jsonl` (each task's official gold patch → expected **resolved**).
- `artifacts/r22/nopatch_predictions.jsonl` (empty patch → expected **unresolved**).
- Verifier: `scripts/r22_grader_smoke.py --verify` checks `gold_resolved == 12/12` and `nopatch_resolved == 0/12`.

## Execution (`.github/workflows/ci-r22-grader-smoke.yml`)
Runs `swebench==5.0.2` `run_evaluation` on both prediction files on a Docker-capable GitHub Actions runner, then
verifies discrimination. This is the **official** harness (clean-room: the SWE-ContextBench eval code, which has no
license, is NOT vendored).

## Status: PREPARED — execution pending a Docker-capable runner
- The 12 tasks are curated from SWE-ContextBench, which mixes SWE-bench **Lite / Multilingual / Verified**. The
  stock harness invocation grades against one `--dataset_name`; instances from other subsets (or without a prebuilt
  image) will not grade under a single Verified pass, and full Docker image provisioning across subsets exceeds the
  available CI budget here.
- This is a **resource/infra limitation, not a fundamental technical block**: with per-subset dataset routing +
  Docker images, the smoke runs as written. It is therefore **not** declared `R22_GRADER_TECHNICAL_BLOCK`.
- Consequence: grader-smoke **green is not yet demonstrated**; every other credential-free gate is green (see the
  final return). Recommended: run `ci-r22-grader-smoke` on a Docker runner with per-instance images, or narrow the
  12 tasks to the SWE-bench_Verified subset only.
