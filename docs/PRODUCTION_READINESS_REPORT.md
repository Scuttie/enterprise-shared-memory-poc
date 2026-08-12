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
