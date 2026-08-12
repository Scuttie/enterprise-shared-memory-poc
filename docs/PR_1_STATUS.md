# Production service v0.2 — CI-first infrastructure implementation [DRAFT]

**Do not merge.** Draft PR tracking the v0.2 production-service build.

## Status
- P0-fix-2: green.
- **P1 + P1.1: PostgreSQL persistence, Alembic, RLS, durable jobs, transactional outbox — CI-VALIDATED
  (ci and ci-postgres GREEN).** P1.1 closed the P1 gaps: frozen hash-verified migrations + irreversible
  safe downgrades; missing tables (teams/team_memberships/promotion_decisions/replay_evidence/artifacts);
  tenant-consistent composite FKs (cross-org insert fails at the DB constraint, not just RLS); real
  immutability TRIGGERS on contract-versions/outcomes/retrieval; optimistic version; supersession-cycle
  CHECK; dedicated NOLOGIN/NOSUPERUSER/BYPASSRLS SECURITY DEFINER owner with REVOKE PUBLIC + ACL tests;
  full Postgres job repo (heartbeat/transition/cancel/dead-letter) + outbox repo (claim/retry/quarantine);
  TRUE concurrent claim + 8-way concurrent idempotency; minimum-privilege grants + privilege matrix.
- **Gate A = PARTIAL** (full HTTP/worker E2E is P5).
- **Gate B advanced**: RLS + composite-FK tenant isolation + roles + private ownership — CI-validated.
- **Gate C advanced**: immutable contract versions + transactional outbox — CI-validated.
- **Gate E advanced**: durable jobs/leases/idempotency/outbox — CI-validated.
- P2 (Qdrant/Mem0) is the next milestone (now unblocked — P1.1 green). P3-P8 not started.
- Company-staging certification PENDING. Version `0.2.0.dev1`; no rc1. Follow-up: pin PostgreSQL image by digest.
