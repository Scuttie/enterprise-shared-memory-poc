# P6 / R19 — Literature Reproduction & Attribution — Preregistration (FROZEN)

Frozen before live calls (§20). Reader **gpt-4o-mini-2024-07-18**, SWE-bench Verified, official grader, ITT.

## Reference
MemGovern (arXiv `2601.06789`, +4.65% on SWE-bench Verified, 135K governed cards). Exact reproduction is
**REPRODUCTION_BLOCKED** — license unresolved + non-redistributable bundled data
(`reports/MEMGOVERN_REPRODUCIBILITY_AUDIT.md`). The product carries a **clean-room behavioral reference** (arm A4),
never presented as MemGovern's exact numbers. SWE-Exp (Apache-2.0) is a conceptual comparator (no files reused).

## Paths
- `REFERENCE_EXTERNAL` — exact reproduction, if run, only in an isolated secret-gated job, never packaged; upstream
  pins recorded as `UNVERIFIED_PIN_IN_SECRET_GATED_REPRO_JOB` until resolved.
- `NATIVE_CLEAN_ROOM` — arm A4 on our own service; auditable, distributable under this repo's license.

## Endpoints
`L1 = A4 − A0` (does the positive agentic-memory system improve resolution), `L2 = A4 − A1` (content beyond
matched compute), `L3 = A4 − A2` (relevance beyond shuffled). Same statistics as the router prereg. Honest
positive/null/negative reporting; no company-ready efficacy claim from reproduction alone.

## Freeze
`configs/p6/literature_reproduction.yaml`, `artifacts/p6/literature_freeze.json` (`003a7706…`),
`artifacts/p6/task_manifest.json` (`bf4effca…`).
