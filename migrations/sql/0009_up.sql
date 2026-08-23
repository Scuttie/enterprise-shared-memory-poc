-- P5.1 §2,§3: auditable memory-injection provenance on retrieval_candidates. `injected` now means the exact
-- compiled view was placed in the backend payload; we persist the injected-view hash and its prompt position,
-- plus BOTH the index-claimed owner and the authoritative PostgreSQL canonical owner so cross-user leakage is
-- computed from the real owner (never inferred from the authenticated user). Runs after 0008; 0001-0008 frozen.

ALTER TABLE retrieval_candidates ADD COLUMN index_owner_id UUID;
ALTER TABLE retrieval_candidates ADD COLUMN canonical_owner_id UUID;
ALTER TABLE retrieval_candidates ADD COLUMN injected_view_hash TEXT;
ALTER TABLE retrieval_candidates ADD COLUMN injected_position INTEGER;
