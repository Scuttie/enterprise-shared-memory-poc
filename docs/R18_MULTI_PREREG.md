# R18 — collective intelligence as a SET (K=5), not a single anecdote — preregistration

Every prior arm injected ONE memory. Human "collective intelligence" is a DISTRIBUTION of many experiences. R18
injects the TOP-5 semantically-retrieved same-repo prior fixes together (M1multi) vs 5 matched cross-repo fixes
(M2multi control). Reader gpt-4o-2024-08-06, frozen main-60, M0 reused from R16. Embedder = product's
multi-qa-MiniLM-L6-cos-v1; target ISSUE TEXT only (no gold). The 5-set raises gold-file coverage 15%→35% vs single.

## Arms + endpoints
- **M1multi**: 5 relevant same-repo worked examples. **M2multi**: 5 cross-repo (matched count) control.
- **Primary H = M1multi − M2multi**: does a SET of relevant experience beat a SET of irrelevant experience?
- Secondary: M1multi − M0 (set vs nothing). Exact McNemar + repo-cluster bootstrap. ITT. Null is final.
- Decision: "the SET unlocks transfer" iff M1multi − M2multi > 0 with McNemar p < 0.05. Else: aggregation over
  multiple related memories does not create transfer either (valid final result).
