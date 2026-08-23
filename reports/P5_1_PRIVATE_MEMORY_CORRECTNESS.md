# P5.1 — Private-memory injection correctness

**Scope:** §2 (private-memory injection must match reality) and §3 (cross-user leakage from the real owner).

## The defect this closes
Before P5.1, the worker recorded a private candidate as `injected=True` while never appending a private view
to the model context (only shared views were compiled into `memory_views`). The persisted `injected` flag
therefore did not correspond to the backend payload — an experiment-invalidating condition. Cross-user leakage
was also computed as `owner = authenticated_user`, i.e. inferred from context rather than read from the
authoritative record.

## The path a private candidate now follows
Qdrant candidate → PostgreSQL canonical reload (inside `validated_search`) → authoritative canonical owner
lookup → current repository-read re-authorisation → current path-policy re-authorisation →
private-state/deletion/quarantine validation (all in `validated_search`'s 21 gates) → deterministic safe
private execution-view compilation (`PrivateExecutionViewCompiler`) → deterministic joint ranking with shared
candidates (`service/injection.py`) → selection of at most 2 total → **actual insertion into the backend
payload (`memory_views`)** → only then `injected=True`, with the injected-view hash and prompt position
persisted.

`injected=True` now means the exact compiled view string is byte-for-byte present in the backend payload. A
candidate not placed in the payload is `injected=False`. Raw private trace text is never used as the view;
provenance/source logs never appear in the payload (the id/hash live outside the model-facing text).

## Real-owner leakage
`cross_user_private_injection_count` is computed in `plan_injection` as the number of **actually-injected**
private candidates whose authoritative canonical owner (`canonical_owner_id`, carried on the validated hit
from the PostgreSQL row) differs from the authenticated user. It is never a literal and never the authenticated
user. `validated_search` gates PRIVATE candidates to the owner (payload-owner gate + canonical-owner gate), so
a legitimately accepted private hit is owner-consistent; a tampered cross-user candidate is rejected and
recorded (accepted=False) with BOTH the index-claimed owner and the authoritative canonical owner, so the
rejection is auditable. A private view for a non-owner is additionally refused at compile time
(`PrivateViewRefused: NOT_OWNER`), and `plan_injection` raises `CrossUserInjectionError` as defence-in-depth if
such a view ever reached selection.

## Persistence (migration 0009)
`retrieval_candidates` gains `index_owner_id`, `canonical_owner_id`, `injected_view_hash`, `injected_position`.
Every candidate (accepted or rejected) is persisted with its scope, both owners, accept/reject, rejection
reason, injected flag, and — when injected — the view hash and payload position.

## Tests
- `tests/unit/test_injection_plan.py` (runs in `ci`, no external deps): deterministic ranking; ≤2 total cap;
  `injected` flag equals the payload byte-for-byte; injected-view hash + position; own-owner zero leakage;
  cross-user private refused at compile (accepted=False, zero leakage); defence-in-depth
  `CrossUserInjectionError`; rejected-audit rows recorded and never injected. **9/9 pass.**
- DB-level guarantees (payload equality through the real worker; adversarial tampered cross-user Qdrant
  payload; revoked-permission and deleted/quarantined rejection) are exercised by the `ci-experiment-readiness`
  workflow (added in P5.1-D) against real PostgreSQL + Qdrant. Status recorded there.
