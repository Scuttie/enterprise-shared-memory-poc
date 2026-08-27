# R22-P0.9 §0 — Starting state and preservation

| item | value |
|---|---|
| repository | Scuttie/enterprise-shared-memory-poc |
| branch | codex/r22-stage-aligned-memory |
| HEAD at P0.9 start | `8141c382e7b186c67167ba1131224bf98da132f6` (local == remote, clean) |
| PR | #16 OPEN / DRAFT |
| current endpoint (R22) | `R22_SCB_GRADER_GATE_FAIL` (preserved, unchanged) |
| paid API calls | 0 (this milestone and all prior) |

## Campaign artifacts (frozen, byte-preserved)
| artifact | sha256 |
|---|---|
| artifacts/r22/scb_grader_smoke.json | `818fa7fa4c58a9beb836eb60da0e02936d87551f9c05331d0beba9d0921b9b9a` |
| artifacts/r22/scb_grader_smoke_evidence_manifest.json | `d9df39a51836059b28cf6da98f2ca792390774a2ae784c387cd4d8adc03b743f` |
| artifacts/r22/SHA256SUMS | covers the campaign + all 12 shard summaries |
| artifacts/r22/oracle_smoke_manifest.json | task_list semantic hash `9e2d24a8…` (12 targets / 84 rows) |
| artifacts/r22/oracle_dev_manifest.json | 40 oracle-dev targets |
| artifacts/r22/grader_smoke.json | historical generic G0.1 result (bytes preserved) |

## Failed instances (from the SCB campaign, run 32863011986 @ 6f55b83)
- `astral-sh__ruff-15725` — official gold unresolved (FAIL_TO_PASS 0/1; "Collected 0 test results").
- `astral-sh__ruff-16445` — official gold unresolved (FAIL_TO_PASS 0/98; "Collected 0 test results").
- Positive control `astral-sh__ruff-15997` — official gold resolved (FAIL_TO_PASS 1/1; "Collected 9 test results").

## Preservation seals (unchanged)
| seal | hash |
|---|---|
| main | `ce10ab4` |
| main seal | `dd79f3d2` |
| oracle freeze | `100d7caa` |
| paid-v2 freeze | `d0d98e51` |
| tag | `v0.3.0-rc1` |
| frozen R1–R21 | unchanged |

## Rules honored this milestone
model API calls = 0 · paid API calls = 0 · no OPENAI/DEEPSEEK key · no reader selection / P1 / P2 / P3 · official
tests not modified · upstream evaluator not modified/vendored · frozen 12 set not rewritten · the two failed rows not
replaced in place · campaign verdict not changed · no merge/tag/release/rebase/reset/force-push.
