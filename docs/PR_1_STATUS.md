# Production service v0.2 — CI-first infrastructure implementation [DRAFT]

**Do not merge.** Draft PR tracking the v0.2 production-service build.

## Status
- head before P2 = eb30fc4.
- P0-fix-2, P1, P1.1, **P2-0**: CI-validated (ci + ci-postgres GREEN). PostgreSQL image **digest-pinned**.
- **P2 (Postgres-authoritative Qdrant/Mem0 indexing) in progress**: P2-preflight (revision 0004 —
  lease-token outbox claims, minimal SECURITY DEFINER search_path, dedicated index-worker role + ACL,
  adversarial supersession-cycle tests, job heartbeat lease bounds), then Qdrant/Mem0 adapters, canonical
  reload, outbox index worker, drift/reindex, ci-qdrant.
- **Gate A = PARTIAL** (full HTTP/worker E2E is P5). Gate B/C/E advanced (CI-validated).
- P3-P8 not implemented. Company-staging certification PENDING. Version `0.2.0.dev1`; no rc1.
