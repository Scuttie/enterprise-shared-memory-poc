# BigCode-R2 Discovery Protocol (§7–§8, §18)

The selection RULE (`experiments/bigcode_r2/discovery.py::select_policy`) was committed (f0faa55) BEFORE any
discovery model call. Discovery is DESCRIPTIVE (no confirmatory p-value) and runs only on the 120
MEMORY_DISCOVERY tasks (disjoint from source/dev/calibration/main).

## Fractional cell set (14 cells + NO_MEMORY baseline)
Formats F0 MINIMAL_HINT / F1 PLAIN_LESSON / F2 API_CARD / F3 GOVERNED_COMPACT / F4 RAW_VERIFIED_TRACE
(`render.py`). Retrieval policies P0 fixed-true-relevant / P1 prod-top1+abstain / P2 prod-top3 / P3
always-top1 / P4 shuffled-matched.
- F0–F4 under P0 (fixed true-relevant source).
- F0–F4 under P4 (shuffled-matched — the relevance control).
- F1/F2/F3 under P1 (deployable retrieval).
- F2 under P2 (top-3) vs F2/P1 (top-1).
Memory content = the verified USER_SUCCESS source facts; relevance labels are evaluator-side over the verified
sources (§6.1), never exposed to prompt/query/backend.

## Predeclared selection (§8) — lexicographic, NOT minimum p-value
1. hard safety must pass: target/test leakage 0, cross-user private leakage 0, invalid-state injection 0.
2. maximise `Pass@1(RELEVANT_FIXED,F) − Pass@1(SHUFFLED_MATCHED,F)` over formats F.
3. among formats within 0.01 of the best relevance effect: minimise memory-induced loss rate.
4. among those within 0.01: minimise mean injected tokens.
5. final deterministic tie-break: lexicographic format/policy id.
The full per-cell calculation and the single selected policy are persisted to
`artifacts/bigcode_r2/selected_policy.json` and frozen for the confirmatory main.
