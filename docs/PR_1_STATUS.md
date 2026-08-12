# Production service v0.2 — CI-first infrastructure implementation [DRAFT]

**Do not merge.** Draft PR tracking the v0.2 production-service build.

## Status
- head before Qdrant P2 = 6241f1e.
- P0-fix-2, P1, P1.1, P2-0, **P2-preflight**: CI-validated (ci + ci-postgres GREEN). PostgreSQL image
  **digest-pinned**. P2-preflight is **COMPLETE** (outbox lease tokens, minimal SECURITY DEFINER
  search_path, dedicated index-worker dispatch role + ACL, API outbox-mutation lockdown, job heartbeat
  bounds, adversarial supersession-cycle tests).
- **Qdrant/Mem0 P2 now IN PROGRESS**: P2-start DB closure (migration 0005 — live-lease heartbeat,
  exhausted-outbox auto-quarantine, backoff bounds, server-side error sanitisation, lease-state CHECK
  constraints), then physically-separated private/shared Qdrant indexes + governed Mem0 infer=False +
  PostgreSQL canonical reload + outbox index worker + drift/reindex + ci-qdrant.
- **Gate A = PARTIAL** (full HTTP/worker E2E is P5). Gate B/C/E advanced (CI-validated).
- P3-P8 not implemented. Company-staging certification PENDING. Version `0.2.0.dev1`; no rc1.
