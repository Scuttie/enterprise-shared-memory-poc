# R23-F0 — Author-method reproducibility (arXiv:2602.21611)

**Status: `CLEAN_ROOM_REIMPLEMENTATION`.** The author code is **not released** (paper: "we will release … upon
acceptance"), so there is no official artifact to reproduce byte-for-byte and no author result artifact to
recompute. Details absent from the paper are **assumptions**, recorded in `artifacts/r23/reproduction_deviations.json`
— never labelled "author settings".

## What is fixed from the paper (`artifacts/r23/author_method_spec.json`)
- Categories `{Analyze, Reproduce, Edit, Verify}`; memory triple `m=(z,d,e)`; category hard-filter → forced
  semantic Top-1; per-subtask extraction (success pattern / failure-avoidance); streaming (empty start, add after a
  target finishes, no self-reuse, extraction in-budget); SWE-bench Verified; temperature 0; 3 shuffled orders;
  Avg. Pass@1 (+ Best@3).

## Reproduction arms (map to A's ablations)
`AR0` Vanilla · `AR1` Structured-only (+1.0) · `AR2` Instance-level/ReasoningBank · `AR3` **author full method**
(+2.3…+6.8, mean +4.7) · `AR4` No-category-filter (+1.6) · `AR5` Raw-trajectory (+1.2). Estimands `R-Q1=AR3−AR0`,
`R-Q2=AR3−AR2`, `R-Q3=AR3−AR1`.

## Deviations to pin in R23-R0 (not yet fixed)
scaffold repo/commit + system prompt + tool schema; embedding/similarity model; extractor & transition prompt text
(clean-room, not verbatim author); reader backbone (from the reader-band pilot, same model for solver + extractor);
exact step/token budgets (after the R23 token audit); Best@3 vs Avg.Pass@1 (primary = Avg.Pass@1).

This track validates whether the **category-aligned** author effect reproduces in our independent implementation +
selected reader. It is **not** a novelty claim. R23-X (the semantic-graph factorial + oracle gate) is a separate
track that can run even if AR3 does not reproduce — the reproduction outcome is reported honestly either way.
