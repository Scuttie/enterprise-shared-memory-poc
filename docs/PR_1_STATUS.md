# Production service v0.2 — CI-first infrastructure implementation [DRAFT]

**Do not merge.** Draft PR tracking the v0.2 production-service build.

## Status
- HEAD `8683b63`. **ci, ci-postgres, ci-qdrant GREEN.**
- Milestones CI-validated: P1, P1.1, P2-0 (alembic 0003), P2-preflight (0004), P2-start (0005),
  P2 core candidate-indexing. PostgreSQL image digest-pinned; Qdrant image digest-pinned.

### P2 core (accepted) — with honest scope
PostgreSQL is authoritative; Qdrant/Mem0 are replaceable candidate indexes whose payloads/text are never
authoritative and never injected into a coding model. Validated search reloads every hit from PostgreSQL.
Accurate status of the current P2 core (operational hardening tracked as **P2.1, in progress**):
- **Alias routing:** *process-local switch implemented; durable alias closure in P2.1.*
- **Qdrant outage handling:** *simulated adapter write-failure replay* (actual container stop/restart is P2.1).
- **Mem0 governance:** *wrapper/stub audit shows infer=False and zero LLM calls; real mem0ai audit pending P2.1.*
- **Drift:** *basic missing / stale-hash / orphan detector* (expanded categories in P2.1).
- Physical private/shared collections exist; 13-step validated search with explicit rejection reasons;
  outbox index worker (index/deprecate/delete/supersede); full reindex + process-local pointer swap/rollback.

### In progress
- **P2.1** operational closure: durable alias routing, pre-swap full-reindex validation, complete
  payload/version/validity/path checks, real mem0ai infer=False integration (ci-mem0), expanded drift,
  actual Qdrant process outage/recovery.
- **P3** OIDC/JWKS + endpoint scope enforcement + repository authorization (GitHub App mock) + ci-oidc.

### Scope / gates
- **Gate A = PARTIAL** (full HTTP/worker E2E is P5). Gate B/C/E PARTIAL-advanced (CI-validated).
- P3–P8 not implemented. Company-staging certification PENDING for every gate.
- Version `0.2.0.dev1`; no rc/beta tag. PR remains DRAFT; do not merge.
