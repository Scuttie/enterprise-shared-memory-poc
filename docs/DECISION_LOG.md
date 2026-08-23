# Decision Log

## Architecture
- **PostgreSQL is authoritative; Qdrant/Mem0 are replaceable indices.** Canonical content is reloaded before use;
  vector text is never treated as truth.
- **Three projections per card** (canonical / neutral retrieval / execution view) to separate governance metadata
  from injectable content and prevent leakage.
- **Utility router gates browse, not search.** Search is metadata-only and cheap; the execution view is the
  sensitive surface, so gating happens at browse.

## Upstream license
- **MemGovern (arXiv 2601.06789): MIT badge but no LICENSE file → UNRESOLVED → REPRODUCTION_BLOCKED.** No code/data
  vendored; clean-room behavioral reference only.
- **SWE-Exp (Apache-2.0): conceptual comparator, no files reused** pending a file-level attribution + moatless
  transitive-license audit.

## Claim boundaries
- **No "shared memory improves coding performance" claim** unless the held-out router endpoint `H1 = A5 − A0`
  passes. R14–R18 are null; the product ships as a governance/attribution platform.
- **COMPANY-HANDOFF-READY ≠ COMPANY-STAGING-CERTIFIED ≠ production.** Certification needs a company staging env and
  sign-off.
- **Fixed reader across A0–A5** (gpt-4o-mini for the R19 primary run) — no per-arm model swap; no picking the
  positive reader.

## Governance
- **Frozen thresholds** (`artifacts/p6/governance_thresholds.json`) before live evaluation; no held-out tuning.
- **No force-promote**; manual review required; outcome stats affect future targets only.
