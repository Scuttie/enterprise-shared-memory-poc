# V03 Documentation Truth Audit (P6 / R19 §2)

Every user-facing claim was scanned against reality before adding product features. `docs/STATUS.yaml` is now the
single machine-readable source of truth; `scripts/check_docs_consistency.py` (wired into `ci-docs`) fails the
build when README/docs contradict it.

## Stale markers found (README + docs/, at start commit `7fddfb9`)
| Marker | Hits | Verdict |
| --- | --- | --- |
| `SQLite` (as canonical/authoritative) | 8 | **FALSE** — PostgreSQL is authoritative; Qdrant/Mem0 are replaceable indices |
| `DEMO-COMPLETE` | 2 | **SUPERSEDED** — old PoC status string |
| `3/5 gates`, `3/5` | 2 | **SUPERSEDED** — old gate scoreboard |
| `production-ready` / `production ready` | 3 | **REJECTED** — no company staging env or sign-off |
| efficacy claim: "one developer's verified experience *can help* another's task succeed" | README lede | **REFUTED** — REALBENCH R14–R18, five levers, all null |
| `R12` references in docs | 10 | historical research docs (kept as frozen research; not product claims) |

## Highest-severity correction — the efficacy claim
The prior README lede asserted that shared verified experience **helps** another developer's task succeed. Our own
controlled study refutes this: R14 (encoding), R15 (retrieval/relevance), R16 (reader strength), R17
(decoding/adaptation), R18 (aggregation/unit) are all null on SWE-bench Verified
(`reports/MEMORY_TRANSFER_SYNTHESIS.md`). Per §14 claim rules, a performance claim is only permitted if the
held-out utility-router endpoint (`H1 = A5 − A0`) passes. It has **not been run** as of this commit
(`utility_router_result: NOT_RUN`). The claim was therefore **replaced** (not appended to) with an honest framing:
the system ships as a governance/attribution platform; any performance claim is gated on STATUS.

## Corrections applied this commit
- README: title de-"PoC"'d; efficacy claim replaced with the honest, evidence-linked framing; SQLite→PostgreSQL
  authority; machine-rendered `<!-- STATUS -->` block inserted (source: STATUS.yaml).
- `docs/STATUS.yaml`: created — versions, statuses, implemented layers, `rejected_claims`, known limitations,
  required company inputs, migration head, workflow count, `utility_router_result: NOT_RUN`.
- `scripts/render_project_status.py`: renders the README status block from STATUS.yaml (idempotent, `--check`).
- `scripts/check_docs_consistency.py`: ci-docs gate — fails on SQLite-authority, unsupported efficacy claim,
  production-ready-while-not-certified, company/production conflation, migration-head drift, workflow-count drift.
- `pyproject.toml`: version `0.2.0.dev1` → `0.3.0.dev1` (§19; dev, not RC).

## Deferred to later commits (tracked, not forgotten)
- Full product-first README rewrite → V03-D0 (§14).
- ARCHITECTURE.md / COMPANY_HANDOFF.md rewrite → V03-D0 (§15).
- PR_1_STATUS.md, PRODUCTION_READINESS_REPORT.md, EVIDENCE_AND_LIMITATIONS.md regeneration from STATUS → as their
  owning phases land.

## Result
`check_docs_consistency.py` → **PASS** (README vs STATUS.yaml; alembic head 0013; workflows 54). The dangerous,
evidence-contradicted claims are removed from user-facing surfaces as the first commit of this milestone.
