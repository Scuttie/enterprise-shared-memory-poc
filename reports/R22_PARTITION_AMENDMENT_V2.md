# R22 §1.1–1.4 — data orientation + partition amendment v2 (pre-model, deterministic)

No model result exists yet, so a power-only, deterministic amendment is permitted. **v1 and its seal are kept**
(not deleted); this is a pre-run amendment recorded in full.

## §1.1 Duplicate base IDs (93)
All 93 duplicate base `instance_id`s are **`EXACT_DUPLICATE_ROW`** (identical full-row hash). They are deduped
deterministically (keep first) — 93 extra rows dropped. None was a legitimate one-source-many-targets relation, so
no real task was removed. `artifacts/r22/duplicate_audit.json`.

## §1.2 Repositories: 57 vs 51
57 raw repo strings → **53 canonical** after owner/case normalization. The dataset card's **51** counts distinct
canonical repositories in the **base experience pool**; 57 counted raw strings across base+related including
related-only repos and case variants. Full map: `artifacts/r22/repository_alias_map.json`.
> One-sentence answer: *51 = distinct base-pool repositories; 57 = raw base+related strings before canonicalization
> (which collapse to 53).*

## §1.3 Temporal re-audit (leakage-first ordering)
Re-classifying with leakage checked **before** temporal (so leakage is never hidden by a temporal exclusion):

| Class | v1 | v2 |
| --- | ---: | ---: |
| CLEAN_RELATED (primary) | 111 | **126** |
| TARGET_PATCH_MATCH (source==target patch) | 1 | **37** |
| NEAR_DUPLICATE (hunk overlap ≥0.60) | 3 | **75** |
| TEMPORAL_REORIENTED_VALID (sensitivity only) | — | 123 |
| TEMPORAL_INVALID | 245 | 15 |

The 37 patch-matches and 75 near-duplicates were previously masked inside "temporal-invalid" — surfacing them is a
**leakage-safety improvement**. Reorientation (123) is recorded **separately** and is **not** merged into the
primary pool, because the dataset fixes source/target roles (base=experience, related=target), so §1.3's
"relation semantics not directional" condition is not satisfied. Chronology uses `created_at` as a conservative
proxy; precise merge-time reorientation is a documented follow-up. `artifacts/r22/temporal_reaudit.json`,
`reoriented_sensitivity.json`.

## §1.4 Split v2 (CLEAN_RELATED primary, canonical repos)
| Split | Repositories | Pairs |
| --- | ---: | ---: |
| development | 14 | 58 |
| held-out main | 18 | 68 |
| repository overlap | **0** | — |
| relation-graph crossing | — | **0** |

- main v2 sealed: `dd79f3d2af349bc7e4461222206150611bc046b121d8e2d39b18c65669152ddc`.
- v1 manifests + seal retained (`dev_manifest.json`, `main_manifest.json`); v2 supersedes for use, does not delete v1.
