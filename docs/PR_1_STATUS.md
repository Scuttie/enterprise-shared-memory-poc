# Production service v0.2 — CI-first infrastructure implementation [DRAFT]

**Do not merge.** Draft PR tracking the v0.2 production-service build. base = main.

## Head & CI
- HEAD `afccf42`.
- **Green:** `ci`, `ci-postgres`, `ci-qdrant`, `ci-mem0`, `ci-oidc` (+ `ci-qdrant-outage`).
- PostgreSQL image digest-pinned; Qdrant image digest-pinned; qdrant-client pinned to a server-compatible
  minor (version check ON).

## Milestones (CI-validated)
P1, P1.1, P2-0 (alembic 0003), P2-preflight (0004), P2-start (0005), **P2** core candidate indexing,
**P2.1** operational closure (0006), **P3** OIDC / scopes / repository authorization.

### P2.1 — operational closure
- **Durable alias routing:** `enterprise_private_current` / `enterprise_shared_current` are the authoritative
  pointer; reads/writes target the alias; swap is one atomic delete+create; readiness is fail-closed
  (bootstrap, verify singular resolution, raise on ambiguity); a fresh/reconnected client sees the current
  alias. No process-local routing state.
- **Expanded payload (schema v1) + complete loaders + 21-step validated search:** authenticated identity
  required for both scopes; ordered gates each with an explicit rejection reason (schema, kind, org, owner,
  existence, permission, repository, version, contract, hash, current, promoted, valid_from, valid_until,
  superseded, path scope, retrieval-text hash). PostgreSQL is authoritative; index text is never returned.
- **Pre-swap full-reindex validation:** shadow built, validated (count, exact id-set, hashes, tenant/owner,
  scope/kind, schema, representative search); alias swaps only on a full pass; a corrupt shadow never swaps;
  instant rollback.
- **Expanded drift detector** (missing/stale/orphan/invalid-schema/wrong-collection/deprecated/superseded/
  expired-searchable/duplicate/alias-health), read-only.
- **Real mem0ai infer=False** (not a stub): spied LLM transport proves **hidden LLM calls = 0**; embeddings
  counted; private/shared physical separation; canonical reloaded from PostgreSQL; prose never injected
  (`ci-mem0`).
- **Actual Qdrant process outage/recovery:** a dedicated workflow stops/starts the real container; the event
  stays PENDING and replays to exactly one point (`ci-qdrant-outage`). The simulated adapter-failure test is
  retained.
- **Event ordering + audit + heartbeat (0006):** a stale/reordered index event never overwrites the current
  point; every processed/retried event is recorded in append-only `index_audit_events`; `heartbeat_outbox_event`
  extends a live lease (owner+token enforced).

### P3 — OIDC / scopes / repository authorization
- **OIDC/JWKS:** RS256 (optional ES256); alg=none & symmetric rejected in staging/prod; JWKS-by-kid with
  rotation, TTL cache, fail-closed fetch; issuer/audience, exp required, nbf/iat bounded leeway, future-iat &
  oversized-token rejected; sub/org_id required. Local threaded JWKS fixture in CI; identity comes only from
  verified claims, never request-body.
- **Endpoint scopes:** per-endpoint minimum scope enforced from token scopes; admin is not implicit.
- **Repository authorization (GitHub App mock):** installation approval, repo membership, read/modify from
  server permissions, ref→immutable commit + tree, branch/path restrictions, host-path-traversal rejection,
  short-lived credentials never in the access decision; client cannot define its own permissions/paths/commit.

## Gates (implementation)
- **A = PARTIAL** — full HTTP/job/worker E2E is P5.
- **B = PARTIAL-advanced** — RLS + canonical index validation CI-validated.
- **C = PARTIAL-advanced** — canonical versioning/outbox/index-state validated; persistent promotion is P6.
- **E = PARTIAL-advanced** — durable job/outbox + Qdrant outage replay validated; full worker/provider recovery later.
- **Company certification: PENDING for every gate.**

### P3.1/P2.2 — COMPLETE (green)
Versioned canonical codec (`contracts/codec.py`, schema `enterprise_memory/1.0.0`); safe target-free
retrieval projection (provenance/hidden-tests/identities never enter Qdrant/Mem0 text); private-recall
re-authorization (current repo-read + path permission; owner alone insufficient; revoked-permission
rejection); pinned embedder (revision/trust/dimension enforced, provenance recorded); OIDC network/JWK/claim
hardening (HTTPS+port+redirect policy, bounded fetch, duplicate/empty JWKS, per-JWK kty/use/key_ops,
single-flight refresh, claim type checks); repository ref/installation policy (server-owned `RepositoryTaskPolicy`,
ref↔branch binding, full commit SHA + tree required, POSIX path normalization, client-chosen installation
rejected).

### P4 — COMPLETE (green)
- **Artifact store** (alembic 0007 + `artifacts/`): PostgreSQL-authoritative metadata + 8-state durable
  lifecycle; `LocalArtifactStore` + `S3ArtifactStore` (private bucket, SSE-configurable, SHA-256 verified,
  content-addressed, no overwrite-with-different-content, presigned GET only); retention + legal hold block
  deletion; physical deletion confirmed only after the object is verified absent; reconciliation. `ci-artifacts`
  (postgres + MinIO) green.
- **Async Solar provider** (`providers/`): one httpx client/process; key via `SecretProvider` (never in
  exceptions/logs/artifacts); timeouts, bounded retries (408/429/5xx/transport only), backoff+jitter+bounded
  Retry-After, stable logical_request_id, per-org+global concurrency, circuit breaker w/ half-open recovery,
  accounting record, redaction sanitizer. `ci-solar` (fake server) green; optional gated `solar-integration`.

### P5 — NOT STARTED (remaining to reach the valid endpoint)
Real authenticated FastAPI `/v1` surface (18 endpoints), durable job submission, a separate worker process
running the full solve pipeline (repo snapshot → dual retrieval → execution-view compiler → model call →
sandbox → patch validation → outcome/private-episode/audit persistence), the HTTP→worker E2E, the negative
E2E suite, and `ci-e2e`. **Gate A stays PARTIAL until the P5 E2E passes.**

## Green workflows
`ci`, `ci-postgres`, `ci-qdrant`, `ci-qdrant-outage`, `ci-mem0`, `ci-oidc`, `ci-artifacts`, `ci-solar`.

## Scope
- P5 in progress / not yet green; P6–P8 not implemented. Company certification **PENDING** for every gate.
- Version `0.2.0.dev1`; no rc/beta tag. PR remains **DRAFT**; **do not merge**.
