# Production readiness report (honest; two columns per §20)

**NOT production-ready.** P1 is CI-validated against an ephemeral PostgreSQL service; P2-P8 remain.

| gate | IMPLEMENTATION / CI STATUS | COMPANY-STAGING CERTIFICATION |
|---|---|---|
| A end-to-end | **PARTIAL** — local component-chain; full HTTP/worker/DB E2E is P5 | PENDING |
| B tenant & repo security | **PARTIAL (advanced)** — PostgreSQL FORCE-RLS org + RESTRICTIVE private-owner isolation, NOBYPASSRLS runtime roles, transaction-local tenant context, pool-leak test, guessed-UUID + malformed-context fail-closed — **CI-validated (ci-postgres green)**. JWT + task-policy + private-egress from P0-fix-2. Real company OIDC / repo authorization pending (P3). | PENDING |
| C contract governance | **PARTIAL** — immutable contract versions (unique version+hash), transactional outbox (composite-version identity, atomicity, dedup, quarantine) CI-validated; persistent promotion is P6 | PENDING |
| D sandbox | **NOT MET** — KubernetesJobSandbox not implemented; subprocess sandbox refused in prod (tested); kind lifecycle P6 | PENDING |
| E reliability | **PARTIAL (advanced)** — PostgreSQL job idempotency, two-worker SKIP-LOCKED single-claim, lease recovery, dead-letter, append-only audit — CI-validated; provider/Qdrant failure recovery later | PENDING |
| F recovery | **NOT MET** — backup/restore is P8 | PENDING |
| G operations | **NOT MET** — OTel/dashboards/runbooks/load are P7/P8 | PENDING |

**Version `0.2.0.dev1`. No rc1.** ci-postgres validates persistence + tenant isolation on ephemeral
PostgreSQL; this is NOT company-staging certification. Follow-up: pin the PostgreSQL image by digest.
