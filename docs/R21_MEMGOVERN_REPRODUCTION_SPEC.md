# R21 — MemGovern Exact-Reproduction Spec (clean-room boundary)

Goal: (A) recompute the author's published SWE-bench Verified positive from their artifacts; (B) independently
reproduce it live; (C) identify the causal component; (D) bridge the minimal lift-producing component to the
company service and verify a real lift on the official grader; (E) hand company evidence over.

Three results are kept strictly separate and never conflated:
`AUTHOR_ARTIFACT_RECOMPUTATION` · `INDEPENDENT_EXACT_REPRODUCTION` · `COMPANY_NATIVE_BRIDGE`.

Gates: no upstream code/data in this repo; live stages require `UPSTREAM_RESEARCH_USE_APPROVED=1` +
`MAX_LIVE_REPRO_BUDGET_USD`; exact model/config/task recovered before any model call; official SWE-bench Verified
grader only; ITT; target gold/tests never in memory/context. See `reports/R21_UPSTREAM_PROVENANCE_AUDIT.md`.
