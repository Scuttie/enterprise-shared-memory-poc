# BigCodeBench-R2 Partition Audit (§4)

Deterministic partition of the **1140** official BigCodeBench-Full task IDs, computed inside the official eval
image **before any model call** and sealed. Split hash **`6e0755582c77ea0b…`**
(`artifacts/bigcode_r2/task_partition.sha256`).

## Provenance (pinned)

| | |
|---|---|
| Universe | 1140 official tasks (`bigcode/bigcodebench` v0.1.4, package 0.2.4 in the eval image) |
| Content hash (platform-independent) | `98e377a83cb1…` |
| Official `get_bigcodebench_hash` | `acf4f1debe64…` |
| Eval image / Python | `bigcodebench/bigcodebench-evaluate:v0.2.4` / 3.10.16 |
| Grader validity (probe) | canonical 12/12 PASS, corrupted 12/12 FAIL |

## Sizes — exact

| Set | Count |
|---|---|
| SOURCE_POOL | 300 |
| RETRIEVAL_DEV | 80 |
| MEMORY_DISCOVERY | 120 |
| INSTRUMENT_CALIBRATION | 80 |
| CONFIRMATORY_MAIN | 500 |
| RESERVE | 60 |
| **Total** | **1140** |

## Hard requirements — all satisfied

- **All 15 pairwise set intersections = 0** (`overlaps_all_zero = true`).
- **source ↔ target near-duplicate pairs = 0** (prompt-token Jaccard ≥ 0.70). **20** near-duplicate tasks were
  quarantined into RESERVE so no near-dup pair spans SOURCE and any target set.
- No target reference solution or test is exposed by the partition (IDs only).

## Function-name disjointness — documented §4 adjustment

`distinct_entry_points = 1`: **BigCodeBench uses a single shared harness entry-point name (`task_func`) for
all 1140 tasks.** Literal function-name disjointness between SOURCE and target sets is therefore *inapplicable*
(every task shares the name). The reported `funcname_collision_source_target = 1` is exactly this single shared
harness name. Per §4 ("document the deterministic adjustment before model calls"), **semantic disjointness is
enforced instead via the near-duplicate exclusion above** — this is the meaningful leakage guard for a
shared-harness benchmark. This adjustment was made and sealed before any model call.

## Determinism & seal

Assignment order is `sha256("bcb-r2:" + task_id)`; near-dup representatives are the lowest such key per
cluster; extras + overflow go to RESERVE. Re-running the builder on the same dataset reproduces the split
byte-for-byte. `tests/bigcode/test_partition_seal.py` recomputes the split hash from the committed partition
and asserts every invariant (disjointness, sizes, near-dup=0, lock pinned) with no benchmark dependency.
