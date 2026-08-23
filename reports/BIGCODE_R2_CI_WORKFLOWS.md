# BigCode-R2 — CI Workflows (§19)

All runs execute the **production service path inside the official BigCodeBench eval image**
(`bigcodebench/bigcodebench-evaluate:v0.2.4`, Python 3.10) on GitHub-hosted runners. The repo was made **public**
so Actions minutes are unlimited/free; a pre-flight secret scan was clean and `SOLAR_API_KEY` lives only as a
GitHub secret (never committed). Each memory-injecting run also sets `ARTIFACT_PER_JOB=1` and the Solar retry
envs (`SOLAR_MAX_ATTEMPTS=12`, `SOLAR_TOTAL_DEADLINE=480`, Retry-After-honoring backoff).

| Workflow | Trigger | Shape | Purpose | Output |
|---|---|---|---|---|
| `ci-bigcode-grader.yml` | `[run-bcb-grader]` | 1 job | Verify official grader + dataset content-hash `98e377a8…` in the eval image | DEPENDENCY_AUDIT |
| `ci-bigcode-smoke.yml` | `[run-bcb-smoke]` | 1 job | End-to-end service→grader smoke (backend/embedder/artifacts) | (integration proof) |
| `ci-bigcode-source-bank.yml` | `[run-bcb-source-bank]` | 1 job | Build USER_SUCCESS + GOLD_VERIFIED banks (24 source users) | source_bank.json (134 verified) |
| `ci-bigcode-discovery.yml` | `[run-bcb-discovery]` | 3-chunk matrix + combine | 14-cell format screen on the **discovery** split | selected_policy.json (F1_PLAIN) |
| `ci-bigcode-calibration.yml` | `[run-bcb-calibration]` | 3-chunk + combine | C1–C6 instrument gates | CALIBRATION (96.4%, VALID) |
| `ci-bigcode-main.yml` | `[run-bcb-main]` | **20-chunk matrix, max-parallel 5**, 2 workers/chunk | Confirmatory main M0–M7, N=500, interleaved | main_results.json (E1 null) |
| `ci-bigcode-safety.yml` | `[run-bcb-safety]` | 3-chunk + combine | §13 wrong-memory subset S0–S4 on RESERVE tasks | safety_results.json |
| `ci-r1-causal-audit.yml` | `[run-r1-audit]` | 1 job | Re-audit R1 claims / evidence-based patch classifier (§1) | R1 correction |

## Execution notes (why this shape)
- **Chunking** (`CHUNK=i/n`) strides the target list; **interleaved submission** completes paired arms evenly so
  a mid-run stop still yields balanced pairs. Throughput ≈ 164 s/job at 2 workers/chunk.
- **Concurrency** capped at 2 workers/chunk and max-parallel 5 to stay under Solar's 429 rate limit; the retry
  envs absorb the rest. This drove chunk-0 success 90% → 100%.
- **Combine** steps (`scripts/bigcode_r2_*_combine.py`) union raw chunk artifacts and run the identical frozen
  analysis over the full split — no per-chunk analysis is trusted.
- **Infra transience:** the main matrix run `31860928312` had 19/20 chunks succeed; chunk 8 was lost to three
  consecutive runner shutdowns (exit 143) despite `gh run rerun --failed` retries — a deterministic infra
  preemption of that one long chunk, not a code/grader fault (all 19 sibling chunks passed). N=475 accepted
  final (≥ the 470 power target); see BIGCODE_R2_MAIN_RESULTS.md.
