# Production service v0.2 — CI-first infrastructure implementation [DRAFT]

**Do not merge.** Draft PR tracking the v0.2 production-service build.

## Status
- P0-fix-2: green (73 tests).
- **P1 (this push): PostgreSQL persistence + Alembic + RLS + durable jobs + transactional outbox** —
  implemented; validated via the new `ci-postgres` GitHub Actions workflow (PostgreSQL service container).
- **Gate A = PARTIAL** (full HTTP/worker E2E is P5).
- **Gate B advances**: PostgreSQL FORCE-RLS tenant/private isolation + no-BYPASSRLS runtime roles +
  transaction-local tenant context + pool-leak test — implemented and CI-validated. Real company OIDC /
  repository authorization remains pending.
- **Gate C**: durable immutable contract versions + transactional outbox implemented; persistent
  promotion remains P6.
- **Gate E**: PostgreSQL job idempotency + two-worker SKIP-LOCKED claim + lease recovery implemented.
- P2–P8 not implemented. Company-staging certification PENDING. Version `0.2.0.dev1`; no rc1.
