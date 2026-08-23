# R21 Stage A — Execution Cost

- **Model API cost = $0** (no model calls; regrading released patches only).
- CI/compute/storage (measured separately, NOT $0):
  - GitHub-hosted runner: 1 matrix run, 4 parallel jobs, ~38 min wall-clock (01:50→02:28 UTC).
  - Git LFS download: ~780 MB (4 trajectory tarballs: 125+146+39+511 MB actual).
  - Docker: official SWE-bench Verified images pulled per instance (~336 gradings total).
  - Artifacts persisted: per-instance resolved labels + patch-hash summaries only (no upstream patches).
