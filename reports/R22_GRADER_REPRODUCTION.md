# R22 §3 (G0/G0.1) — mixed official-grader reproduction: PASS

The official SWE-bench grader **discriminates 12/12** on the frozen mixed smoke after routing to the enriched
`SWE-bench/*` datasets (image taken from the row). No model calls, no test modification.

## Result (run 32801365294, enriched datasets)
| Gate | Required | Actual |
| --- | --- | --- |
| gold resolved | 12/12 | **12/12** |
| no-patch unresolved | 12/12 | **12/12** (0 resolved) |
| infrastructure failures | 0 | **0** |
| result completeness | 24/24 | **24/24** |
| official tests modified | 0 | **0** |

All 12 instances resolve with the gold patch and stay unresolved with no patch, across 3 subsets / 6 languages:
Verified+Lite python (astropy, sympy, seaborn) and Multilingual go/java/ruby/rust/php (caddy, prometheus, lucene,
gson, rubocop, tokio, axum, ruff, php-cs-fixer).

## Root cause of the earlier failure (resolved)
The 3 python instances had been routed to **legacy `princeton-nlp/*`** rows, which lack the enriched
`image`/`eval_script`/`log_parser`/`eval_type` fields swebench 5.0.2 requires → `KeyError:'image'`. Re-routing to
the enriched `SWE-bench/*` datasets (pinned; 12/12 EXACT_CORE_MATCH with the legacy rows) supplies the `image`
field from the row and the python instances now grade correctly. It was a dataset-schema compatibility issue, not a
harness defect.

## Verdict: mixed grader gate PASS → `R22_GRADER_READY_AWAITING_PAID_APPROVAL`
Credential-free CI = **8/8 green**. P1/P2 are NOT started (paid approval absent). See
`reports/R22_PAID_EXECUTION_PLAN.md` for the model-specific P1/P2 hard-cap table and the required approval variables.
