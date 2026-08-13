# Production readiness report (honest; two columns per §20)

**NOT production-ready.** P1 + P1.1 are CI-validated (ci-postgres green) against an ephemeral PostgreSQL service; P2-P8 remain.

| gate | IMPLEMENTATION / CI STATUS | COMPANY-STAGING CERTIFICATION |
|---|---|---|
| A end-to-end | **PARTIAL** — local component-chain; full HTTP/worker/DB E2E is P5 | PENDING |
| B tenant & repo security | **PARTIAL (advanced)** — FORCE-RLS org + RESTRICTIVE private-owner isolation, **tenant-consistent composite FKs (DB-level cross-org block)**, NOBYPASSRLS roles + **min-privilege matrix**, transaction-local context, pool-leak, guessed-UUID + malformed fail-closed — **CI-validated**. Real company OIDC / repo authz pending (P3). | PENDING |
| C contract governance | **PARTIAL** — **immutable contract versions via TRIGGERS** + optimistic version + supersession-cycle CHECK, transactional outbox (claim/retry/quarantine) CI-validated; persistent promotion is P6 | PENDING |
| D sandbox | **NOT MET** — KubernetesJobSandbox not implemented; subprocess sandbox refused in prod (tested); kind lifecycle P6 | PENDING |
| E reliability | **PARTIAL (advanced)** — PostgreSQL job idempotency, two-worker SKIP-LOCKED single-claim, lease recovery, dead-letter, append-only audit — CI-validated; provider/Qdrant failure recovery later | PENDING |
| F recovery | **NOT MET** — backup/restore is P8 | PENDING |
| G operations | **NOT MET** — OTel/dashboards/runbooks/load are P7/P8 | PENDING |

**Version `0.2.0.dev1`. No rc1.** ci-postgres validates persistence + tenant isolation on ephemeral
PostgreSQL; this is NOT company-staging certification. Follow-up: pin the PostgreSQL image by digest.

## P2.1 + P3 update (HEAD afccf42)

Green workflows: `ci`, `ci-postgres`, `ci-qdrant`, `ci-mem0`, `ci-oidc` (+ `ci-qdrant-outage`). Both the
PostgreSQL and Qdrant images are digest-pinned; qdrant-client is pinned to a server-compatible minor.

- **B canonical/index (advanced):** durable Qdrant alias routing (fail-closed readiness, atomic swap);
  21-step validated search reloading every hit from PostgreSQL with explicit rejection reasons; index
  schema v1 reference payload (no canonical text); pre-swap full-reindex validation + instant rollback;
  expanded read-only drift detector.
- **Governed Mem0:** REAL mem0ai under infer=False proven to make **zero** LLM calls (`ci-mem0`); private/
  shared physically separated; content reloaded from PostgreSQL; prose never injected.
- **E reliability (advanced):** actual Qdrant container outage → replay to exactly one point
  (`ci-qdrant-outage`); append-only `index_audit_events`; outbox lease heartbeat; stale/reordered index
  events never overwrite the current point.
- **P3 auth:** production OIDC/JWKS (RS256/optional ES256, rotation, TTL cache, fail-closed, alg=none &
  symmetric rejected in staging/prod), per-endpoint scope enforcement, and GitHub-App repository
  authorization (server-derived permissions, ref→immutable commit, path/branch limits, no creds in the
  decision) — all CI-validated against local fixtures / a mocked GitHub API.

**Company certification remains PENDING for every gate. P4–P8 not implemented. PR #1 stays DRAFT.**

## P3.1 + P4 update

Additional green workflows: `ci-artifacts` (postgres + MinIO) and `ci-solar` (fake server). Delivered and
CI-validated: versioned canonical codec + safe retrieval projection + private-recall re-authorization +
pinned embedder; OIDC network/JWK/claim hardening; server-owned repository task policy; the artifact store
(8-state lifecycle, retention/legal-hold, physical-delete-after-confirmation, reconciliation) on both local
and S3/MinIO; and the async Solar provider (resilience/circuit/concurrency/accounting/redaction).
**P5 (runnable HTTP→worker E2E) is not started; Gate A stays PARTIAL until it passes. P6–P8 not implemented.**
