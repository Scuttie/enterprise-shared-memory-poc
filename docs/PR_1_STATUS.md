# Production service v0.2 — CI-first infrastructure implementation [DRAFT]

**Do not merge.** Draft PR tracking the v0.2 production-service build. Head advances with each milestone.

## Status
- current head: P0-fix-2 (see commits)
- tests at P0-fix-2: **73** (53 v0.1 + 20 service), all green in `ci`
- **Gate A = PARTIAL**: local component-chain integration only — NOT full HTTP API / durable job /
  worker / DB end-to-end. Full E2E arrives at P5.
- P1–P8 (Postgres/RLS/Alembic, Qdrant/Mem0, MinIO/S3, OIDC-JWKS, async API+worker, promotion, K8s
  sandbox, observability, Helm, backup/restore, load) are implemented and validated **through GitHub
  Actions service containers**, not on the local host.
- **Company-staging certification remains PENDING** for all gates; CI validation != company security
  certification.

## P0-fix-2 (this head)
- Server-owned `TaskExecutionPolicy` — client cannot dictate target_file/test_entry/signature/paths.
- `PrivateExecutionViewCompiler` — real egress boundary (ownership + secret/PII scan + repo/path scope),
  replaces newline-strip/truncation.
- JWT now requires iss/aud/exp/sub/org_id and rejects malformed scope claims.

Version stays `0.2.0.dev1`. No `v0.2.0-rc1`. See `docs/PRODUCTION_READINESS_REPORT.md`.
