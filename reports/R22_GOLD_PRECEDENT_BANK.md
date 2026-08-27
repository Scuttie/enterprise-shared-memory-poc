# R22 §3 — GOLD_PRECEDENT bank (deterministic, no model calls)

Built by `experiments/r22/gold_precedent_bank.py` from official source gold patches + tests for the CLEAN_RELATED
source tasks. `USER_SUCCESS` (reader-solved) bank is **not** built here — it requires paid model calls.

## Coverage (`artifacts/r22/gold_precedent_manifest.json`)
| Metric | Value |
| --- | ---: |
| source tasks | 88 |
| sources with ≥1 record | 88 |
| stage records total | **440** |
| by stage | COMPREHEND 88 · REPRODUCE 88 · LOCALIZE 88 · EDIT 88 · VERIFY 88 |
| symbol extraction coverage | 0.35 |
| API extraction coverage | 0.025 |
| operation-type extraction coverage | 0.20 |
| verification coverage | 0.40 |
| UNKNOWN semantic-field fraction | 0.40 |
| leakage sentinel | PASS |

## Honesty notes
- Semantic fields (`violated_contract`, `root_cause`, `non_applicability`) are set to **UNKNOWN** wherever not
  deterministically derivable — never guessed (an LLM extractor would fill these in the paid `USER_SUCCESS` path).
- Low API coverage (2.5%) reflects that many gold patches don't add imports; symbol coverage (35%) reflects
  Python-oriented regex extraction over a multilingual set — recorded honestly, not inflated.
- The gold **raw diff** is exposed only via `OracleRawDiffView` (a patch reference id, `restricted: O3_ONLY`) and
  is never placed in the SearchIndexView or the default ExecutionView.
- GOLD_PRECEDENT is an **upper-bound / schema-quality** bank for the O3 oracle arm; it is **not** the product's
  primary memory (that is `USER_SUCCESS`, paid) and its results are never mixed with USER_SUCCESS.

Artifacts: `artifacts/r22/gold_precedent_bank.json`, `gold_precedent_manifest.json`.
