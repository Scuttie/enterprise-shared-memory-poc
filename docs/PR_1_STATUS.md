# Production service v0.2 — CI-first infrastructure implementation [DRAFT]

**Do not merge.** Draft PR tracking the v0.2 production-service build.

## Status
- P0-fix-2, P1, P1.1: green.
- **P2-0 (canonical-integrity + dispatcher/outbox preflight): CI-VALIDATED (ci + ci-postgres GREEN).**
  Same-contract current-version FK; supersession same-contract FK + cycle trigger; P1.1-table tenant FKs
  (cross-org insert fails at the DB constraint); hardened SECURITY DEFINER claim (fixed search_path, lease
  bounds, empty-worker/cancel/exhausted->DEAD_LETTER, dedicated NOLOGIN owner + REVOKE PUBLIC); terminal-
  lease clearing; deterministic error redaction; outbox lease-owner enforcement; **PostgreSQL image pinned
  by digest**.
- **Gate A = PARTIAL** (full HTTP/worker E2E is P5).
- **Gate B / C / E advanced** (RLS + canonical integrity + durable jobs/outbox — CI-validated).
- **P2 (Qdrant/Mem0 index + outbox index worker + drift/reindex + ci-qdrant) is the NEXT milestone**
  (now unblocked — P2-0 green). Not started. P3-P8 not implemented.
- Company-staging certification PENDING. Version `0.2.0.dev1`; no rc1.
