# Production service v0.2 — CI-first infrastructure implementation [DRAFT]

**Do not merge.** Draft PR tracking the v0.2 production-service build. base = main.

## Head & CI
- HEAD: latest on `codex/production-service-v0.2` (see PR commits; docs synced at `739a773`).
- **Green (all 9):** `ci`, `ci-postgres`, `ci-qdrant`, `ci-qdrant-outage`, `ci-mem0`, `ci-oidc`,
  `ci-artifacts`, `ci-solar`, **`ci-e2e`** (real HTTP → durable job → separate worker → SUCCEEDED).
- PostgreSQL / Qdrant / MinIO images pinned; qdrant-client pinned to a server-compatible minor.

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

### P3.1/P2.2 — COMPLETE (green)
Versioned canonical codec (`contracts/codec.py`, schema `enterprise_memory/1.0.0`); safe target-free
retrieval projection (provenance/hidden-tests/identities never enter Qdrant/Mem0 text); private-recall
re-authorization (current repo-read + path permission; owner alone insufficient; revoked-permission
rejection); pinned embedder (revision/trust/dimension enforced, provenance recorded); OIDC network/JWK/claim
hardening (HTTPS+port+redirect policy, bounded fetch, duplicate/empty JWKS, per-JWK kty/use/key_ops,
single-flight refresh, claim type checks); repository ref/installation policy (server-owned `RepositoryTaskPolicy`,
ref↔branch binding, full commit SHA + tree required, POSIX path normalization, client-chosen installation
rejected).

### P4.1 — COMPLETE (green)
- **Artifact integrity:** existing S3 object accepted only on matching hash-metadata **and** size (missing
  metadata → read-back verify or fail closed); post-write verification (exists + size + hash-metadata +
  read-back hash + tenant-prefixed key) before AVAILABLE, failure → UPLOAD_FAILED + audit, no presign;
  read-only **bidirectional reconciliation** (`store.list_keys`) + separate explicit `repair()`; full deletion
  chain AVAILABLE→DELETE_REQUESTED→LOGICALLY_DELETED→PHYSICAL_DELETE_PENDING→PHYSICALLY_CONFIRMED|DELETE_FAILED
  (retention/legal-hold block physical delete; object verified absent before confirm); **chained** append-only
  artifact audit.
- **Solar closure:** one absolute logical deadline bounding every attempt + sleep; per-attempt `AttemptRecord`
  + a final `LogicalModelCall` on **every** outcome (attached to the raised error); Retry-After/jitter clamped
  (0..max, never negative); malformed-200 → accounted `ParserError` (not a transport retry); bounded/LRU
  per-org limiter; provider interface conformance test.

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

### P5 — COMPLETE (green: `ci-e2e`)
The full **authenticated HTTP → durable PostgreSQL job → separate worker process → SUCCEEDED** path is
CI-validated end-to-end (`ci-e2e`: digest-pinned Postgres + Qdrant + MinIO, local JWKS/OIDC + offline
GitHub-App + fake execution backend + controlled local sandbox; API and solve worker run as SEPARATE
processes; tests talk to the API over real HTTP):
- **Legacy insecure PoC quarantined** (`create_offline_demo_app`, refused in ci/staging/production); the sole
  production app is `service.app.create_app`. Regression tests: the `/v1/solve` schema forbids
  org/user/patch/test_passed/editable_paths.
- **15 `/v1` endpoints**, each bearer → OIDC verify → IdentityContext → exact route scope → tenant tx →
  server-owned repository/task policy → audit. `POST /v1/solve` is durable (202; server-owned task policy +
  modify authz + ref binding + immutable commit/tree; idempotency; no model/sandbox work in the handler).
- **Pluggable `CodingExecutionBackend`** (Fake/Direct/ExternalHarness) — the worker is not hard-wired to Solar.
- **Separate worker pipeline**: claim lease + heartbeat + stage deadline → immutable snapshot artifact → dual
  private/shared `validated_search` (canonical reload) → retrieval evidence → ≤2 compact governed views →
  backend → patch parse + edit-policy validation → controlled sandbox → outcome / private episode /
  candidate-extraction outbox / audit → **atomic finalize**. `cross_user_private_injection_count == 0` is
  **computed** from candidate owners.
- **Positive E2E** (HTTP + separate worker, idempotency, full DB evidence, ordered events), **negative matrix**
  (no/bad/expired token, wrong iss/aud, missing scope, body-identity spoof, no-modify, ref mismatch, unknown
  policy, cross-tenant job hidden, foreign private memory, missing search scope), and **crash recovery** (a
  crashed worker's lease reclaimed by an independent worker; exactly one terminal result; separate attempts;
  stale worker cannot finalize) — all green. OpenAPI snapshot (`openapi_v1.json`) checked.

P5 foundation (also green): preflight §1 (artifact existing-AVAILABLE integrity verification; per-org audit
chain serialized with `pg_advisory_xact_lock` — no fork) + **alembic 0008** (solve-job snapshot columns +
RLS-forced, tenant-FK'd `job_events` / `model_calls` / `retrieval_candidates`).

## Status — two distinct claims (do not conflate)
1. **P5 service plumbing** = **PASS in credential-free CI with fake repository/execution providers.** The
   authenticated HTTP → durable job → separate worker → governed retrieval → backend → sandbox → durable
   result path is green in `ci-e2e` using a fake execution backend, offline repository provider, file JWKS,
   and a controlled local sandbox. This is a plumbing claim, not an efficacy or real-provider claim.
2. **Multi-user experiment readiness** = **NOT YET PASS.** Before the frozen experiment can be trusted, P5.1
   closes: real private-view injection (DB `injected` must equal the backend payload byte-for-byte),
   real-owner cross-user leakage computation, lease-loss/cancellation/atomic-finalisation correctness, a
   non-toy frozen executable coding bank, a company-harness adapter boundary, and a preregistered freeze.
   P5.1-A (injection + real-owner leakage) is the first of these commits.

## Gates (single table)
| Gate | Status | Note |
|------|--------|------|
| A (end-to-end service) | PASS in CI (fake providers) | `ci-e2e` green; efficacy not claimed |
| B (tenant/RLS isolation) | PARTIAL-advanced | RLS + canonical validation CI-validated |
| C (canonical governance) | PARTIAL-advanced | versioning/outbox/index-state validated; reviewed promotion is P6 |
| D (production sandbox) | NOT MET | K8s sandbox is P6 |
| E (durability/recovery) | PARTIAL-advanced | durable job/outbox + Qdrant outage replay validated |
| F / G | NOT MET | — |
| Experiment readiness | NOT YET PASS | P5.1 in progress |
| Company certification | PENDING (every gate) | — |

## Reproducibility pinning
- PostgreSQL and Qdrant images are digest-pinned in `ci-e2e`.
- The `ci-e2e` MinIO image is currently `latest` and is **NOT digest-pinned**; it will be pinned by immutable
  digest in P5.1-D, before any experiment freeze.

## Green workflows (all 9)
`ci`, `ci-postgres`, `ci-qdrant`, `ci-qdrant-outage`, `ci-mem0`, `ci-oidc`, `ci-artifacts`, `ci-solar`, `ci-e2e`.

## Scope
- P6–P8 not implemented (reviewed promotion + K8s sandbox = P6; OTel/ops = P7; backup/DR = P8). Company
  certification **PENDING** for every gate.
- Version `0.2.0.dev1`; no rc/beta tag. PR remains **DRAFT**; **do not merge**.
