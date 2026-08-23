# P5.1 — Lease loss, cancellation, and terminal atomicity audit

**Scope:** §4.1 (heartbeat/lease loss), §4.2 (cancellation), §4.3 (atomic terminal finalisation + idempotency).
Memory generated from outcomes must never be contaminated by duplicate or stale terminal writes.

## §4.1 Heartbeat / lease loss
`_heartbeat_loop` no longer swallows a failed renewal. On `PermissionError` (lease no longer owned/live) or any
renewal error it **sets a `lease_lost` event** and returns. The pipeline checks this signal at every stage
boundary (`_checkpoint`) and raises `LeaseLost`, which aborts immediately: no further model/sandbox/artifact
work, no terminal evidence, and **no `mark_failed`** — a worker that lost its lease is stale and must not write
any terminal state. `mark_failed` is additionally hardened: its FAILED `UPDATE` is guarded by
`lease_owner = :w AND state not terminal`, and the FAILED `job_event` is appended **only if that UPDATE hit one
row**, so a stale worker cannot append a terminal event to a job it no longer owns.

## §4.2 Cancellation
`_checkpoint` reads `cancel_requested_at` (and the current owner/expiry/state) before **each** expensive stage:
snapshot, retrieval, model/harness execution, patch processing, sandbox, and finalisation. A cancel raises
`Cancelled`; the worker records the terminal `CANCELLED` only via the guarded `mark_cancelled` (lease-owner
enforced). A cancelled job cannot continue merely because the worker still holds a lease.

## §4.3 Atomic terminal finalisation
`durable.finalize_success_atomic` is the single authoritative finaliser. In **one** tenant transaction it:
1. takes the SUCCEEDED transition only if this worker still owns the live lease (single winner; a stale worker
   gets rowcount 0 → `PermissionError`, nothing committed);
2. verifies required durable evidence exists — ≥1 model call, ≥5 AVAILABLE artifacts, a `retrieved` job event,
   ≥1 attempt — else `TerminalEvidenceMissing` rolls the whole transaction back (the job does **not** become
   SUCCEEDED);
3. writes the terminal OutcomeObservation, the single deterministic PrivateEpisode, the single
   candidate-extraction outbox event, the terminal audit, the computed leakage count, and the SUCCEEDED
   transition + event — together.

Object-store bytes remain governed by the artifact state machine (persisted earlier); finalisation only
verifies they are AVAILABLE.

### Idempotency by job/attempt (migration 0010)
- OutcomeObservation: `UNIQUE(org_id, job_id)` + `ON CONFLICT DO NOTHING` → no duplicate terminal outcome.
- PrivateEpisode: deterministic per-job id (`uuid5(job)`) + `ON CONFLICT DO NOTHING` → no duplicate episode.
- Candidate outbox event: idempotent by its existing `(event_type,aggregate_type,aggregate_id,version)` unique
  key (aggregate_id is the deterministic episode id) → no duplicate candidate event.

## Tests (`ci-experiment-readiness`, real PostgreSQL + Qdrant)
`tests/experiment_readiness/test_finalisation.py`:
- stale worker `mark_failed` writes no state and no terminal event;
- `mark_cancelled` guarded (non-owner no-op; owner cancels);
- finalisation fail-closed on missing evidence (rolled back, still non-terminal);
- happy path writes exactly one outcome/episode/candidate/audit bundle;
- stale-worker finalisation → `PermissionError`, non-terminal;
- two workers racing to finalise → exactly one SUCCEEDED, single evidence bundle;
- retry is idempotent (already-terminal → `PermissionError`; counts stay 1).

`tests/experiment_readiness/test_pipeline_injection.py` (real worker pipeline):
- cancellation before stages → CANCELLED, no terminal outcome;
- stolen lease → LEASE_LOST, stale worker writes nothing terminal.
