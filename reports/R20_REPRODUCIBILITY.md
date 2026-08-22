# R20 Reproducibility

- Frozen before run: `artifacts/r20/freeze.json` (master), task/source_pair/prompt/model_harness/analysis/power/
  card/index/router_policy locks (content-hash sealed; `ci-experiment-seal`, `ci-r20-freeze`).
- Task set: 248 untouched (hash bb401907), disjoint from R19-observed 60. Arms precomputed
  (`scripts/r20_build_arms.py`); analysis deterministic (`scripts/r20_analysis.py`, `r20_result.json`).
- R19/R1-R18 unchanged; reader/harness/tool budget identical across arms; no optional stopping; no N expansion.
