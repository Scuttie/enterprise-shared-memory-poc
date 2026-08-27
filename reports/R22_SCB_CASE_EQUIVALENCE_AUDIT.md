# R22-P0.8 §3 — Official case-file coverage + frozen-row equivalence

Artifacts: `artifacts/r22/scb_case_route_manifest.json`, `artifacts/r22/scb_case_equivalence.json`
Upstream pinned commit `31bb04155f52b184bf31b220e3cff0607ac9c953`.

## Coverage — 40/40, 0 missing
Every one of the 40 frozen paid targets (reader-band/P2 dev 40 ⊇ P1 smoke 12) has an official case JSON at
`cases/<subset>/<instance_id>.json`. The narrower subset is used when a target also appears in `Full` (the union
copy):

| subset used | count |
|---|---|
| SWEContextBench Multilingual | 17 |
| SWEContextBench Verified | 15 |
| SWEContextBench Lite | 8 |
| **total** | **40** |

`ambiguous unmatched duplicates = 0`. Per-target the manifest records: `case_path`, `case_sha256`, `subset_used`,
`all_case_paths` (incl. the `Full` copy), `repo`, `base_commit`, `patch_sha256`, `test_patch_sha256`,
`f2p_canon`, `p2p_canon`, `problem_statement_sha256`, `environment_setup_commit`.

## Equivalence vs the frozen SWE-ContextBench row — 40/40
Compared each official case JSON to the frozen benchmark row (SWE-ContextBench `Related`⊕`Experience` parquet, the
same source `RealR22TaskLoader` joins):

- **byte-identical core fields: 40/40** — `repo`, `base_commit`, `patch` (sha256), `test_patch` (sha256),
  `problem_statement` (sha256) all match exactly.
- **test-set identity (FAIL_TO_PASS / PASS_TO_PASS): 40/40.**

### Serialization note (why a naïve hash first showed 23/40)
A naïve canonical hash of `FAIL_TO_PASS`/`PASS_TO_PASS` matched only 23/40 — all 17 misses were the multilingual
(non-Python) targets. Cause: the **parquet stores those two fields as a Python-`repr` string** (a single-quoted
list literal, e.g. `"['t1', 't2']"`), **not** a JSON array, so `json.loads` fails and the value is treated as one
opaque element. Parsing with `ast.literal_eval` yields the identical test set → **40/40**. This is a parquet
serialization artifact only; it is not a task discrepancy.

Decisive point: the **official evaluator grades from `cases/<subset>/<id>.json`** (via `combine_instances`), where
`FAIL_TO_PASS`/`PASS_TO_PASS` are proper JSON arrays — so grading uses the authoritative case values, which equal
the frozen benchmark's tests 40/40.

## Result
`R22_OFFICIAL_SCB_CASE_MISSING` does **not** apply — cases 40/40 present, core-row equivalent 40/40.
