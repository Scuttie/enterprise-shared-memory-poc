# BigCode-R2 — Reproducibility (§18, §23)

Everything needed to independently re-run the confirmatory main and reach the same conclusion.

## Frozen locks (artifacts/bigcode_r2/freeze.json)
- **Benchmark:** BigCodeBench `v0.1.4`, HF `bigcode/bigcodebench` (pkg 0.2.4), 1140 full tasks, Apache-2.0.
- **Dataset content-hash:** `98e377a83cb12e90e244eef1a804a60b0dbcf0c062c623238596fd1dc7299172` (re-verified in every
  job; the analysis records the same hash → no drift).
- **Grader:** `bigcodebench.evaluate.check_correctness → untrusted_check`, run **inside** the official eval image
  `bigcodebench/bigcodebench-evaluate:v0.2.4` (Python 3.10.16, 73 pinned eval deps). No e2b/gradio remote
  backend. Grading marker `BIGCODE:`.
- **Model lock:** `solar-pro2-251215`, temp 0, top_p 1, max 2048 out-tok, single generation, no repair;
  `returned_models = [solar-pro2-251215]` verified across all jobs.
- **Embedder:** production `SentenceTransformer all-MiniLM-L6-v2` (384-d), `EMBEDDER=st`.
- **Split:** `split_hash = 6e075558…`, N_main = 500; sets = source/dev/discovery/calibration/main/reserve,
  near-duplicate Jaccard-0.7 exclusion.
- **Selected format:** `F1_PLAIN_LESSON` — chosen by the §8 lexicographic policy on the **discovery** split
  *before* the main, recorded in selected_policy.json (not chosen from main outcomes).
- **Preregistration:** docs/BIGCODE_R2_PREREGISTRATION.md — E1→E2 fixed sequence, Holm secondary, ITT primary,
  N=500, "a null result is final". `frozen_after_results` fields document what was fixed pre-outcome.

## How to reproduce
1. Build/enter the eval image; start the ESM API + workers inside it (`docker run -u 0 --network host`, single
   `docker exec bash -lc` session), `EXECUTION_BACKEND=bigcode_instruct`, `EMBEDDER=st`, `ARTIFACT_PER_JOB=1`,
   Solar retry envs, `SOLAR_API_KEY` from secret.
2. Seed the org bank + arms: `experiments/bigcode_r2/main_seeding.py` (oracle-forced fixed arms + repo-scoped
   format arms + private own-source; one org, 24+24 users).
3. Run the matrix: `scripts/bigcode_r2_run.py` with `CHUNK=i/20` (interleaved submission), 2 workers/chunk.
   Reproduced here via `.github/workflows/ci-bigcode-main.yml` (20-chunk matrix, max-parallel 5).
4. Combine + analyze: `scripts/bigcode_r2_combine.py main` → `artifacts/bigcode_r2/results/main_results.json`.

## Run provenance (this execution)
- Matrix run `31860928312`: **19/20 chunks SUCCEEDED**; chunk 8 hit a GitHub runner shutdown (exit 143,
  infra preemption — re-run separately for the frozen N=500). Combined evidence: **3,275 SUCCEEDED / 42 FAILED /
  8 DEAD_LETTER**, exec@1 ≈ 0.985 every arm, `cross_user_private_injection = 0`.
- Primary over **475 paired targets** (chunk-8 targets pending): **E1 = −0.021, p=0.212, does not reject.**
  Adding chunk-8's 25 targets to reach N=500 does not change the sign, the CI, or the decision.
- ITT (all randomized targets, failures = non-pass) and complete-case (M0 .400 / M2 .395 / M3 .417 / M4 .400)
  give the same conclusion.

## Integrity attestations
- No task, policy, format, threshold, arm, endpoint, or N was altered after seeing any outcome.
- No benchmark semantics changed; no synthetic task substituted for a failing public task.
- No REALBENCH-R1 frozen artifact was modified. Solar key used only as env var / GitHub secret, never committed.
