# R22-P0.9 — Full dev-pool gradeability audit

Per-target gradeability of the 55 unique dev targets (40 ORIGINAL_P2 + 15 DEV_RESERVE) under the OFFICIAL SCB evaluator (GOLD + NOOP-BASELINE). Verdict derived from downloaded shard artifacts with the complete raw evidence set re-verified byte-for-byte against the download tree.

<!-- P09_RESULTS_START -->
## Results — 55-target dev-pool gradeability audit
Audit: **INCOMPLETE** — endpoint `R22_P09_GRADEABILITY_AUDIT_INCOMPLETE`. GRADEABLE<55 is the scientific result, not an infra failure; the audit fails closed only when INCOMPLETE. A clean audit holds only GRADEABLE / UNGRADEABLE_SELECTOR / UNGRADEABLE_GOLD (each carries the full 8-file raw evidence set per condition).

**GRADEABLE: 43/55** (original-40: 31/40, reserve-15: 12/15)

| label | count |
|---|---|
| GRADEABLE | 43 |
| UNGRADEABLE_SELECTOR | 0 |
| UNGRADEABLE_GOLD | 10 |
| UNGRADEABLE_CASE_IMAGE | 0 |
| UNGRADEABLE_TOOLCHAIN | 0 |
| INFRA_FAILURE | 0 |
| UNKNOWN | 0 |

| completeness gate | value |
|---|---|
| summary files | 53/55 |
| total cells | 106/110 |
| duplicate targets | 0 |
| missing cells | 4 |
| digest mismatch | 0 |
| missing raw evidence | 0 |
| INFRA_FAILURE | 0 |
| UNKNOWN | 0 |

Raw evidence files required per EXECUTED condition: run_instance.log, test_output.txt, report.json, summary_report.json, stdout.log, stderr.log, dataset.json, prediction.json

GRADEABLE by language: {"java": 3, "rust": 2, "python": 34, "go": 4}
GRADEABLE by subset: {"SWEContextBench Multilingual": 9, "SWEContextBench Verified": 19, "SWEContextBench Lite": 15}
GRADEABLE by repository: {"apache/lucene": 1, "astral-sh/ruff": 1, "astropy/astropy": 6, "caddyserver/caddy": 2, "google/gson": 2, "mwaskom/seaborn": 1, "prometheus/prometheus": 2, "pydata/xarray": 4, "sympy/sympy": 23, "tokio-rs/tokio": 1}

Failed gates: ['unique_targets_55', 'target_set_equals_manifest', 'summary_files_55', 'total_cells_110', 'no_missing_cells']
<!-- P09_RESULTS_END -->
