# R20 Factorial Parity

Same r14 agent, reader gpt-4o-mini-2024-07-18, identical system prompt/tool budget across all six arms; arms differ
ONLY by the offline-precomputed injected memory text. Verified invariants (`ci-r20-factorial-parity`,
`source_pair_manifest.json`, `tests/unit/test_r20_freeze.py`):

- **F10.src == F11.src** (same relevant top-K), **F00.src == F01.src** (same shuffled set) — only relevance and
  router vary.
- **B1 compute parity**: neutral scaffold length-matched to F10 (mean 4362 vs 4367 chars).
- Router = frozen R19 policy (content_hash unchanged). Router ABSTAINed on 100% of cross-repo shuffled → F01 mean
  injected length = 0 (recorded; part of the router policy, §7.3).
- 60 R19-observed tasks excluded from the confirmatory set (overlap = 0).
