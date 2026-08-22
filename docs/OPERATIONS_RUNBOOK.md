# Operations Runbook

## Health checks
`GET /healthz` (liveness), `GET /readyz` (DB + index reachable). `make smoke` runs an end-to-end check.

## Migrations
`alembic upgrade head` (head = `0014`). Each migration verifies a frozen SQL sha256 before executing; downgrades
are intentionally unsupported for the experience layer.

## Qdrant / Mem0 reindex
Replay `EXPERIENCE_INDEX` outbox events to rebuild the vector index from canonical PostgreSQL cards. The index is
disposable; canonical content is never reconstructed from vector text.

## Outbox replay
`EXPERIENCE_INDEX | EXPERIENCE_DEPRECATE | EXPERIENCE_DELETE | EXPERIENCE_SUPERSEDE | OUTCOME_CREDIT_RECOMPUTE`
are idempotent; re-run the worker to drain a backlog.

## Backup / restore
PostgreSQL is authoritative — back it up (PITR recommended). Qdrant can be rebuilt by reindex, so it is not part of
the authoritative backup set.

## Audit export
`GET /v1/memory-audit/{request_id}` (scope `memory:admin`); audit rows are append-only.

## Disabling memory globally
Set `MEMORY_POLICY_MODE=off` (no retrieval/injection) or `shadow` (decisions only, no injection). Effective without
a redeploy where the setting is read per-request.

## Incident response
1. Set `MEMORY_POLICY_MODE=off`. 2. Quarantine suspect cards via `POST /v1/experience-cards/{id}/quarantine`.
3. Export the audit for the affected `request_id`s. 4. Reindex after remediation.
