# P0 correction audit (§1)

The previous increment over-stated **Gate A** as "PASS (local/fakes)". Corrected via this new commit
(history not rewritten).

## Why Gate A was PARTIAL, not PASS
The earlier test invoked `SolveOrchestrator` directly and did not traverse the HTTP API, did not create
or lease a durable job, used no worker process, did not persist an OutcomeObservation/PrivateEpisode,
did not enqueue candidate extraction, did not inject private retrieval, and hard-coded `private_leak=False`.

## Corrections made in this commit (all tested, offline)
- Gate A relabelled **PARTIAL** everywhere; the test is now the "local component-chain integration test".
- **Removed the benchmark dependency**: patch parser/applicator moved to `enterprise_memory/patches/`;
  production code imports no `benchmarks`/`research` (verified).
- **Async I/O interfaces** (§2.1): all external-I/O Protocols + local providers + orchestrator + identity
  + jobs converted to async; the blocking sandbox runs via `asyncio.to_thread`.
- **Real private-memory ownership** (§2.3): private items are ownership-checked and sanitised before
  injection; a non-owner item is **blocked** and counted; `cross_user_private_injection_count` is
  computed (0 by construction) and a non-zero value is a hard failure — no hard-coded `private_leak`.
- **`can_modify` required for solve** (§2.4); editable paths come from server policy, not the request body.
- **Local persistence** (§2.5, partial): OutcomeObservation persisted to an outcome store, audit emitted,
  candidate/private-episode outbox event published. Transactional Postgres persistence remains P1.
- **Strict configuration** (§3): enum-validated fields, `ci` mode, complete production diagnostic list,
  identical-collection rejection, unsafe-staging flag.

## Still NOT done (P1-P8) — requires infrastructure absent from this environment
Postgres+Alembic+RLS, Qdrant/MinIO/OIDC-JWKS-server, Kubernetes/kind, Helm, Docker Compose, real Solar
provider, async FastAPI + worker processes, promotion wiring, OpenTelemetry, backup/restore, load/soak.
This environment has no Docker/Postgres/Qdrant/MinIO/kind/Helm, so those stages can be authored but NOT
validated here; they are not claimed as passing.
