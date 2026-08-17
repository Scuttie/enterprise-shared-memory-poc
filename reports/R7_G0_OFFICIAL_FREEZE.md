# R7 §1 — G0 Exact Official Freeze

Pins the SWE-PolyBench Verified instrument to exact, hashed, immutable revisions **before** any paid call.
Everything below is from the pinned artifacts, verified 2026-08-17. Authoritative outputs:
`artifacts/swe_polybench_r7/official_manifest.json`, `configs/swe_polybench_r7/instrument_lock.json`.

## Pinned revisions
| item | value |
|---|---|
| Official repo + evaluator | `github.com/amazon-science/SWE-PolyBench` @ **`9c836c5d7f3cb991934132b77d29e6941d912a07`** |
| Verified dataset | `AmazonScience/SWE-PolyBench_Verified` @ HF revision **`b3fca77b637379f0c01ad86d18753a7ac1998b53`** |
| Dataset file | `test.csv`, sha256 **`0c8138e73c34fa29a5276b675b146b72d78ce001fcc4560d76302c908b4808a5`** (12,410,402 bytes) |
| License | MIT (code + dataset) |

## Assertions on the pinned revision — ALL PASS
- `len(dataset) == 382` ✅
- Per language: **Java 69 / JavaScript 100 / Python 113 / TypeScript 100** ✅ (sums to 382)
- `instance_id` unique ✅ (382 distinct)
- `base_commit` length == 40 for all rows ✅
- `patch` / `test_patch` / `F2P` / `P2P` present (0 missing) ✅
- `created_at` present 382/382 ✅ (enables the §5 strict-chronology source rule)

## Recorded descriptive facts
- `task_category`: Bug Fix 299 / Feature 70 / Refactoring 13 (for §8 per-category stratification).
- Columns include the structural metadata (`is_func_only`, `num_func_changes`, `modified_nodes`) that the
  **corrected** design uses ONLY evaluator-side for relevance labelling — never injected into agent context
  (v2 correction 1; the target-derived localization arm is removed from all efficacy endpoints).
- The manifest stores all 382 instance IDs, per-language ID lists, and a per-instance content sha256
  (`instance_id|base_commit|patch|test_patch|F2P|P2P`) so any later drift is detectable (§11 hard stop).

## Documentation-only discrepancy
The HF **dataset-card text says 394**; the pinned `test.csv` (and live viewer) is **382**. Per protocol the
pinned rows/IDs are authoritative; 394 is recorded as stale card text only. Verified N was resolved
**programmatically** (`len == 382` at revision `b3fca77`), as the corrected prereg required.

## Verdict
**G0 dataset freeze PASS.** No official test was modified; gold `patch`/`test_patch` and F2P/P2P are pinned for
evaluator-side use only and will never be exposed to the agent. Next: **§2 multi-language GHCR image + grader
smoke** (2 each Java/Python/JS/TS) — the execution-side half of G0 — which requires Docker and runs in CI.
