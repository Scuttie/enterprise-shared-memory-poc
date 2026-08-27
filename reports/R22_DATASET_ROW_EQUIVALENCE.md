# R22 §3 — legacy ↔ enriched row equivalence (frozen 12)

| Class | Count |
|---|---:|
| EXACT_CORE_MATCH_ENRICHED | 12 |

**12/12 EXACT_CORE_MATCH_ENRICHED** — the enriched SWE-bench/* rows match the legacy princeton-nlp/swe-bench rows on all core task fields (repo, base_commit, patch, test_patch, FAIL_TO_PASS, PASS_TO_PASS, problem_statement, environment_setup_commit; list fields normalized before hashing). The enriched rows add image/eval_script/log_parser/eval_type. No task content changed; only the evaluation schema is enriched.

Artifacts: artifacts/r22/legacy_enriched_row_comparison.json
