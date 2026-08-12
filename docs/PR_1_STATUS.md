# Production service v0.2 — CI-first infrastructure implementation [DRAFT]

**Do not merge.** Draft PR tracking the v0.2 production-service build.

## Status
- HEAD `aca9484`. **ci, ci-postgres, and ci-qdrant are all GREEN.**
- P0-fix-2, P1, P1.1, P2-0, P2-preflight, **P2-start**, **P2 (Qdrant/Mem0)**: CI-validated.
  PostgreSQL image **digest-pinned**; Qdrant image **digest-pinned** (`sha256:241edb9d…`).

### P2-start (migration 0005) — COMPLETE
Live-lease job heartbeat (an expired lease can't be revived by the old worker), `claim_next_outbox_event`
skips exhausted events and auto-quarantines exhausted-expired ones, `retry_outbox_event` enforces backoff
bounds (0..86400) and **server-side** secret sanitisation, and an outbox lease-state CHECK constraint
(PROCESSING ⇄ lease set; PENDING/PROCESSED/QUARANTINED ⇄ lease null). Hash-frozen SQL; `alembic current`
head is 0005.

### P2 (Qdrant/Mem0 Postgres-authoritative indexing) — COMPLETE
New package `src/enterprise_memory/indexing/`. **PostgreSQL is authoritative**; Qdrant/Mem0 are replaceable
candidate indexes whose payloads and embedded text are **never** authoritative and are **never** injected
into a coding model.
- **Validated search (13 steps, explicit rejection reasons):** the vector store is a candidate generator
  only; every hit is reloaded from PostgreSQL and returned as the canonical row. Rejections:
  `not_in_postgres`, `hash_mismatch`, `wrong_org`, `not_owner`, `not_current_version`, `deprecated`,
  `no_read_permission`, `scope_mismatch`.
- **Physical private/shared separation:** two collections (`enterprise_private_v1`/`enterprise_shared_v1`)
  + `*_current` aliases + store-side org/owner filter — a private point can never surface in a shared search.
- **Governed Mem0:** `infer=False` hardcoded, **hidden LLM calls = 0** (proven by a stub; real Mem0 behind
  the `mem0` extra). Reference payloads only.
- **Durable projection:** outbox index worker (index/deprecate/delete/supersede) claims via the SECURITY
  DEFINER dispatcher (lease token) and completes only after the index mutation. A **Qdrant outage** leaves
  the event PENDING (retried, never marked processed) and **replays** on recovery.
- **Drift detector** (missing/stale/orphan vs canonical current set) and **full reindex + atomic alias swap
  + instantaneous rollback** (the live collection is never mutated).
- **DeterministicTestEmbedder** makes it all reproducible with no model, key, or network.
- `.github/workflows/ci-qdrant.yml`: digest-pinned postgres + qdrant services, **hermetic** — no
  `UPSTAGE_API_KEY`, no company database/Qdrant/identity, no torch/mem0/model-download/network.
  `tests/qdrant/` = 24 tests (embeddings, adapter, separation, governed-mem0, validated-search, worker,
  outage/replay, drift, reindex) — all green.
- Scripts: `scripts/index_drift_check.py`, `scripts/index_rebuild.py`. Report:
  `reports/P2_QDRANT_DEPENDENCY_AUDIT.md`. Provenance/notices/lock updated (`qdrant` extra).

### Scope / gates
- **Gate A = PARTIAL** (full HTTP/worker E2E is P5). Gate B/C/E advanced (CI-validated).
- P3-P8 not implemented. Company-staging certification PENDING. Version `0.2.0.dev1`; no rc/beta tag.
