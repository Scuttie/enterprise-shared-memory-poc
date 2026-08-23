# P2 — Qdrant / Mem0 dependency & governance audit

Scope: the P2 milestone adds a **PostgreSQL-authoritative** vector-index layer under
`src/enterprise_memory/indexing/`. Qdrant and Mem0 are **replaceable candidate indexes**. Their payloads and
their embedded text are never authoritative memory and are never injected into a coding model.

## Dependencies added
| dependency | pin | license | why |
|---|---|---|---|
| qdrant-client | `>=1.9,<2.0` (runner: 1.19.0) | Apache-2.0 | vector candidate index client (local mode in CI, URL mode in prod) |
| postgres (image) | `16.4@sha256:e62fbf9d…` | PostgreSQL License | authoritative store (shared with ci-postgres) |
| qdrant/qdrant (image) | `v1.12.4@sha256:241edb9d…` (digest-pinned) | Apache-2.0 | real vector server exercised in ci-qdrant |

`ci-qdrant` installs **only** `.[dev,postgres,qdrant]` — no `torch`, no `mem0ai`, no `sentence-transformers`,
no model download, no network egress, and **no `UPSTAGE_API_KEY`, company database, company Qdrant, or
company identity**. It is fully hermetic.

## Governance guarantees (and how each is tested)
- **PostgreSQL is authoritative.** `validated_search` treats the vector store purely as a candidate
  generator; every candidate is reloaded from PostgreSQL and the *canonical* row is what a caller receives.
  The index payload holds ids + `content_hash` only — never canonical text.
  (`tests/qdrant/test_validated_search.py`, `test_qdrant_adapter.py::test_payload_has_no_raw_text`.)
- **13-step validation with explicit rejection reasons:** scope → org → owner → exists-in-PG → org →
  owner → hash-match → current-version → not-deprecated → repo-read-permission. Each failure maps to a
  `RejectionReason` (`not_in_postgres`, `hash_mismatch`, `wrong_org`, `not_owner`, `not_current_version`,
  `deprecated`, `no_read_permission`, `scope_mismatch`).
- **Physical private/shared separation:** two collections (`enterprise_private_v1`, `enterprise_shared_v1`),
  never one collection with a scope column, plus a store-side org/owner filter.
  (`test_separation.py`, `test_qdrant_adapter.py`.)
- **Governed Mem0 (`infer=False`, hidden LLM calls = 0):** the wrapper hardcodes `infer=False` and exposes
  reference payloads only; the real Mem0 path stays behind the `mem0` extra. Proven in CI with a stub that
  raises on `infer=True` and counts inference calls (asserts 0). (`test_mem0_governed.py`.)
- **Durable projection via the outbox:** the index worker claims events through the SECURITY DEFINER
  dispatcher (lease token), applies index/deprecate/delete/supersede, and only then completes the lease.
  A **Qdrant outage** leaves the event `PENDING` (retried, never marked processed) and it **replays** on
  recovery. (`test_index_worker.py`, `test_outage_replay.py`.)
- **Drift detection** (missing / stale / orphan vs the canonical current set) and **full reindex with atomic
  alias swap + instantaneous rollback** (the live collection is never mutated). (`test_drift.py`,
  `test_reindex.py`, `scripts/index_drift_check.py`, `scripts/index_rebuild.py`.)

## Reproducibility
`DeterministicTestEmbedder` (sha256 bag-of-tokens, L2-normalised) makes indexing/search/drift/reindex
reproducible with no model or key. Its provenance (model id, dim, algorithm digest) and the qdrant-client
version are stamped into drift/reindex reports so an embedder or client swap is detectable.

## Follow-ups
- Done: `qdrant/qdrant` is digest-pinned (`sha256:241edb9d…`, resolved on the runner in ci-qdrant run
  31574181758). The resolve-digest step remains for future re-pins.
- The client (1.19) warns on the server (1.12.4) minor-version gap; `check_compatibility=False` is set so
  the warning never becomes a hard failure. A future bump can align the server minor if desired.
