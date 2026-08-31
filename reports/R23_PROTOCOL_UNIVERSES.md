# R23-B0 — Two separate protocol universes

R23-R (author streaming) and R23-X (chronological product-like) are **never mixed in one mean**.

## R23-R — `AUTHOR_PROTOCOL_REPRODUCTION` (streaming)
500-instance universe; empty memory at run start; online accumulation after each completed instance; **3
result-independent frozen orders**; a task sees only earlier-in-order completed tasks (no self-memory); same reader
for solving + extraction; temperature 0; extraction cost inside the fixed budget. **No public chronology imposed**
(the predecessor used shuffled orders, not source-before-target chronology — adding chronology here would change the
method). Orders: `author_stream_order_{0,1,2}.json` (seeds 20230/20231/20232), lock
`author_stream_order_lock.json`. Order shas `de4d8c18…`, `463d078d…`, `6ad7a228…`; each a verified 500-permutation.
Scale labels: `EXACT_REPRODUCTION` (500 × all 3 orders) vs `SCALED_PROTOCOL_REPLICATION` (fewer) vs
`COMPONENT_REPRODUCTION` (isolated ablations) — a 60/120 subset is never "exact".

## R23-X — `CHRONOLOGICAL_PRODUCT_LIKE_EXPERIMENT`
Requires **source fix available < target work begins**, source≠target, source_user≠target_user (when defined),
source patch/test absent from the target prompt, target gold/test absent from every memory, exact/answer-adjacent
duplicates excluded, no silent-pass on unknown timestamps. Later holds the SemanticSubtaskAtoms, observed/oracle
graphs, overlap audit, source×query factorial, abstention, wrong-atom safety.

Eligibility graph (`chronological_eligibility_graph.json`): target_start_at = `issue_created_at` (known 500/500);
source_available_at = `fix_pr_merge_at` = **UNKNOWN** in the enriched parquet → **0 confirmed `TEMPORALLY_ELIGIBLE`
edges** yet. A provisional created_at-ordering upper bound is **124,750** ordered pairs (of 249,500 possible) — this
is issue-creation ordering, an **UPPER BOUND, not eligibility**. B0 builds only the orders + the eligibility-graph
structure; **no source–target pair is selected by any similarity in B0** (§7) — semantic applicability/overlap come
only after R23-A0 (atoms) and R23-G0 (graphs).
