# Integration status (honest)

This branch (`codex/production-service-v0.2`) is an **early production-service increment**, NOT a
staging-ready candidate yet. It delivers the P0 foundation + self-contained P4/P5/P6 logic with real
tests; the infrastructure-dependent stages (Postgres/RLS, OIDC/JWKS, Kubernetes sandbox, S3, Qdrant
production path, observability, backup/restore, load/soak) are **not yet implemented or not runnable**
without company infrastructure.

## Implemented AND tested here (offline)
- Service interfaces (Protocols) + `AppSettings` + `ServiceContainer` + DI (`build_container`).
- **Production-mode startup refusal** of dev backends / SQLite / static identity / local sandbox /
  plaintext secrets / non-https endpoints (unit-tested).
- **Generalised typed execution-view compiler** (ExecutionDirective IR + plugin registry + literal
  output + REFUSED_UNSUPPORTED + control-plane refusal) extending the v0.1 pilot compiler.
- Durable **job state machine** + in-memory JobRepository (transitions, idempotency, lease recovery).
- **Transactional outbox** semantics (idempotent apply + poison quarantine).
- **JWT identity validation** (issuer/audience/exp/nbf/signature/scopes, fail-closed) + identity-derived
  repository authorization.
- **Local component-chain integration** via `SolveOrchestrator` (Gate A = PARTIAL, not full end-to-end): auth -> authz -> separate
  private/shared retrieval -> canonical reload -> gates -> compile literal view -> FakeSolar -> sandbox
  -> outcome + audit; invalid contracts inject NO model-facing text; no client patch is trusted.

## NOT wired end-to-end yet (requires company infrastructure; not runnable here)
Postgres registry + Alembic migrations + **row-level security**; OIDC/JWKS RS256 with a real IdP;
GitHub App repository provider; **Kubernetes Job sandbox** (+ escape suite); S3 artifact store; Qdrant
production outbox indexing; asynchronous worker process; OpenTelemetry traces/metrics/dashboards;
backup/restore + disaster recovery; load/soak/failure-injection. These are specified and interface-
stubbed; they are not implemented as runnable adapters in this increment. These gaps are stated in the
release notes and the readiness report -- not hidden.
