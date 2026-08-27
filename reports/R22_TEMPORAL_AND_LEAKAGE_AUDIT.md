# R22 §4 — temporal + leakage audit and repository-level split (pre-model, sealed)

Computed by `experiments/r22/benchmark_adapter.py` over the MIT dataset only. No model calls. All exclusions were
made **before** any model result exists (§4: "결과를 본 뒤 pair를 제외하지 않는다").

## Leakage / eligibility classification (376 relationship pairs)
| Class | Count | Meaning |
| --- | ---: | --- |
| **CLEAN_RELATED** | **111** | source-before-target (by `created_at`), patch hashes differ, no target-id/URL/test in source, hunk overlap < 0.60 → **primary pool** |
| NEAR_DUPLICATE | 3 | normalized hunk overlap ≥ 0.60 → oracle-sensitivity only, excluded from main |
| TARGET_ADJACENT | 16 | target instance-id/PR-number or FAIL_TO_PASS text present in source memory → excluded |
| TARGET_PATCH_MATCH | 1 | source patch == target patch → excluded |
| TEMPORAL_INVALID | 245 | source `created_at` **not** before target `created_at` → excluded |
| UNKNOWN | 0 | missing row / unparseable time |

### Honest caveat on temporal check
Temporal ordering uses each instance's `created_at` (PR/issue creation) as the proxy for "source resolved before
target". This is conservative and **over-excludes**: 245/376 pairs fail source-before-target by `created_at`. A more
precise check (§4.2 optional GitHub metadata: source merge timestamp vs target issue/PR creation) could reclassify
some of these; that lookup is a follow-up. The primary pool is intentionally the conservative CLEAN_RELATED = 111.

## Repository-level split (§4, deterministic, sealed)
Method: CLEAN_RELATED only → union-find over source/target repositories to form relation components →
SHA-256 ordering of components → assign whole components until ~25% of CLEAN pairs are in dev → the rest to main.
The relation graph **never crosses** the split (whole components move together).

| Split | Repositories | Pairs |
| --- | ---: | ---: |
| development | 16 | 53 |
| held-out main | 18 | 58 |
| **repository overlap** | **0** | — |
| **relation-graph crossing pairs** | — | **0** |

- `artifacts/r22/dev_manifest.json`, `main_manifest.json`, `partition_log.json`.
- **main manifest sealed**: `seal_sha256 = 4250513cfcefe098748f5ac9a2e684097ce472e84426689397b21230558118fe`
  (over sorted main repos + sorted target ids). The main workflow must refuse to run if this seal changes.

## Note on pool size
CLEAN_RELATED = 111 pairs (53 dev / 58 main) is a **small** primary pool. Both ITT (all targets) and COVERED
(targets with a verified source) estimands will be reported at main time; the small N is recorded now, not adjusted
after seeing results.
