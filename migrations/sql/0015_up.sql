-- TRIMEM-CODER V1 canonical graph memory.
-- PostgreSQL remains authoritative.  Vector stores receive only reference metadata.
-- Every graph child repeats (org_id, namespace, graph_kind, owner_user_id); a trigger checks
-- those values against the graph header and RLS applies the same private-owner rule.

CREATE TABLE trimem_graphs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  namespace TEXT NOT NULL CHECK (length(btrim(namespace)) BETWEEN 1 AND 200),
  graph_kind TEXT NOT NULL CHECK (graph_kind IN
    ('SHORT_TERM_WORKING','USER_EPISODIC','USER_SEMANTIC','ORGANISATION_SEMANTIC')),
  owner_user_id UUID REFERENCES users(id),
  repository_id UUID REFERENCES repositories(id),
  solve_job_id UUID REFERENCES solve_jobs(id),
  graph_state TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (graph_state IN ('ACTIVE','SEALED','ARCHIVED')),
  schema_version TEXT NOT NULL DEFAULT 'enterprise_memory/trimem-graph/1.0.0',
  ingested_at TIMESTAMPTZ NOT NULL,
  event_time TIMESTAMPTZ,
  source_available_at TIMESTAMPTZ,
  last_accessed_at TIMESTAMPTZ,
  last_used_at TIMESTAMPTZ,
  last_verified_at TIMESTAMPTZ,
  valid_from TIMESTAMPTZ,
  valid_until TIMESTAMPTZ,
  review_id TEXT,
  reviewer_id TEXT,
  reviewed_at TIMESTAMPTZ,
  review_authority TEXT CHECK (review_authority IN ('HUMAN_REVIEW','TRUSTED_DOCUMENT')),
  review_policy_version TEXT,
  review_evidence_hash TEXT,
  content_hash TEXT NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
  UNIQUE (org_id, namespace, id),
  CONSTRAINT trimem_graph_owner_scope CHECK (
    (graph_kind = 'ORGANISATION_SEMANTIC' AND owner_user_id IS NULL)
    OR
    (graph_kind IN ('SHORT_TERM_WORKING','USER_EPISODIC','USER_SEMANTIC') AND owner_user_id IS NOT NULL)
  ),
  CONSTRAINT trimem_working_job_required CHECK
    (graph_kind <> 'SHORT_TERM_WORKING' OR solve_job_id IS NOT NULL),
  CONSTRAINT trimem_valid_range CHECK
    (valid_from IS NULL OR valid_until IS NULL OR valid_until >= valid_from),
  CONSTRAINT trimem_shared_graph_reviewed CHECK (
    graph_kind <> 'ORGANISATION_SEMANTIC'
    OR (review_id IS NOT NULL AND reviewer_id IS NOT NULL AND reviewed_at IS NOT NULL
        AND review_authority IN ('HUMAN_REVIEW','TRUSTED_DOCUMENT')
        AND review_policy_version IS NOT NULL AND review_evidence_hash IS NOT NULL)
  )
);

CREATE TABLE trimem_graph_nodes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  namespace TEXT NOT NULL CHECK (length(btrim(namespace)) BETWEEN 1 AND 200),
  graph_id UUID NOT NULL,
  graph_kind TEXT NOT NULL CHECK (graph_kind IN
    ('SHORT_TERM_WORKING','USER_EPISODIC','USER_SEMANTIC','ORGANISATION_SEMANTIC')),
  owner_user_id UUID,
  repository_id UUID REFERENCES repositories(id),
  node_type TEXT NOT NULL CHECK (node_type IN
    ('Task','Subtask','Episode','SemanticRule','Repository','File','Symbol','API','Error',
     'Test','Operation','Outcome','User','Version')),
  lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (lifecycle_state IN ('ACTIVE','ARCHIVED','TOMBSTONED')),
  canonical_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  payload_hash TEXT NOT NULL CHECK (payload_hash ~ '^sha256:[0-9a-f]{64}$'),
  archived_at TIMESTAMPTZ,
  archive_reason TEXT,
  archived_from_content_hash TEXT
    CHECK (archived_from_content_hash IS NULL
      OR archived_from_content_hash ~ '^sha256:[0-9a-f]{64}$'),
  ingested_at TIMESTAMPTZ NOT NULL,
  event_time TIMESTAMPTZ,
  source_available_at TIMESTAMPTZ,
  last_accessed_at TIMESTAMPTZ,
  last_used_at TIMESTAMPTZ,
  last_verified_at TIMESTAMPTZ,
  valid_from TIMESTAMPTZ,
  valid_until TIMESTAMPTZ,
  review_id TEXT,
  reviewer_id TEXT,
  reviewed_at TIMESTAMPTZ,
  review_authority TEXT CHECK (review_authority IN ('HUMAN_REVIEW','TRUSTED_DOCUMENT')),
  review_policy_version TEXT,
  review_evidence_hash TEXT,
  vector_index_schema_version INTEGER,
  vector_collection_scope TEXT CHECK (vector_collection_scope IN ('private','shared')),
  embedding_model_id TEXT,
  embedding_revision TEXT,
  embedding_dimension INTEGER CHECK (embedding_dimension IS NULL OR embedding_dimension > 0),
  content_hash TEXT NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
  UNIQUE (org_id, namespace, graph_id, id),
  UNIQUE (org_id, namespace, id),
  CONSTRAINT trimem_node_graph_fk FOREIGN KEY (org_id, namespace, graph_id)
    REFERENCES trimem_graphs(org_id, namespace, id),
  CONSTRAINT trimem_node_owner_scope CHECK (
    (graph_kind = 'ORGANISATION_SEMANTIC' AND owner_user_id IS NULL)
    OR (graph_kind IN ('SHORT_TERM_WORKING','USER_EPISODIC','USER_SEMANTIC') AND owner_user_id IS NOT NULL)
  ),
  CONSTRAINT trimem_node_kind_compatibility CHECK (
    NOT (graph_kind = 'USER_EPISODIC' AND node_type = 'SemanticRule')
    AND NOT (graph_kind IN ('USER_SEMANTIC','ORGANISATION_SEMANTIC') AND node_type = 'Episode')
  ),
  CONSTRAINT trimem_node_archive_provenance CHECK (
    (lifecycle_state = 'ACTIVE' AND archived_at IS NULL AND archive_reason IS NULL
      AND archived_from_content_hash IS NULL)
    OR (lifecycle_state <> 'ACTIVE' AND archived_at IS NOT NULL AND archive_reason IS NOT NULL
      AND archived_from_content_hash IS NOT NULL)
  ),
  CONSTRAINT trimem_node_valid_range CHECK
    (valid_from IS NULL OR valid_until IS NULL OR valid_until >= valid_from),
  CONSTRAINT trimem_shared_node_reviewed CHECK (
    graph_kind <> 'ORGANISATION_SEMANTIC'
    OR (review_id IS NOT NULL AND reviewer_id IS NOT NULL AND reviewed_at IS NOT NULL
        AND review_authority IN ('HUMAN_REVIEW','TRUSTED_DOCUMENT')
        AND review_policy_version IS NOT NULL AND review_evidence_hash IS NOT NULL)
  ),
  CONSTRAINT trimem_node_vector_protocol CHECK (
    (vector_index_schema_version IS NULL AND vector_collection_scope IS NULL
      AND embedding_model_id IS NULL AND embedding_revision IS NULL AND embedding_dimension IS NULL)
    OR
    (vector_index_schema_version = 2
      AND graph_kind <> 'SHORT_TERM_WORKING'
      AND ((graph_kind = 'USER_EPISODIC' AND node_type = 'Episode' AND vector_collection_scope = 'private')
        OR (graph_kind = 'USER_SEMANTIC' AND node_type = 'SemanticRule' AND vector_collection_scope = 'private')
        OR (graph_kind = 'ORGANISATION_SEMANTIC' AND node_type = 'SemanticRule'
            AND vector_collection_scope = 'shared')))
  )
);

CREATE TABLE trimem_graph_edges (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  namespace TEXT NOT NULL CHECK (length(btrim(namespace)) BETWEEN 1 AND 200),
  graph_id UUID NOT NULL,
  graph_kind TEXT NOT NULL CHECK (graph_kind IN
    ('SHORT_TERM_WORKING','USER_EPISODIC','USER_SEMANTIC','ORGANISATION_SEMANTIC')),
  owner_user_id UUID,
  edge_type TEXT NOT NULL CHECK (edge_type IN
    ('DECOMPOSES_TO','DEPENDS_ON','TOUCHES','CALLS','OBSERVED','APPLIED','VERIFIED_BY',
     'PRODUCED','SUPPORTED_BY','CONTRADICTED_BY','DERIVED_FROM','PROMOTED_TO',
     'SUPERSEDES','VALID_FOR')),
  source_node_id UUID NOT NULL,
  target_node_id UUID NOT NULL,
  lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (lifecycle_state IN ('ACTIVE','ARCHIVED','TOMBSTONED')),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  ingested_at TIMESTAMPTZ NOT NULL,
  event_time TIMESTAMPTZ,
  source_available_at TIMESTAMPTZ,
  last_accessed_at TIMESTAMPTZ,
  last_used_at TIMESTAMPTZ,
  last_verified_at TIMESTAMPTZ,
  valid_from TIMESTAMPTZ,
  valid_until TIMESTAMPTZ,
  review_id TEXT,
  reviewer_id TEXT,
  reviewed_at TIMESTAMPTZ,
  review_authority TEXT CHECK (review_authority IN ('HUMAN_REVIEW','TRUSTED_DOCUMENT')),
  review_policy_version TEXT,
  review_evidence_hash TEXT,
  content_hash TEXT NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
  UNIQUE (org_id, namespace, graph_id, id),
  CONSTRAINT trimem_edge_graph_fk FOREIGN KEY (org_id, namespace, graph_id)
    REFERENCES trimem_graphs(org_id, namespace, id),
  CONSTRAINT trimem_edge_source_fk FOREIGN KEY (org_id, namespace, graph_id, source_node_id)
    REFERENCES trimem_graph_nodes(org_id, namespace, graph_id, id),
  CONSTRAINT trimem_edge_target_fk FOREIGN KEY (org_id, namespace, graph_id, target_node_id)
    REFERENCES trimem_graph_nodes(org_id, namespace, graph_id, id),
  CONSTRAINT trimem_edge_no_self CHECK (source_node_id <> target_node_id),
  CONSTRAINT trimem_edge_owner_scope CHECK (
    (graph_kind = 'ORGANISATION_SEMANTIC' AND owner_user_id IS NULL)
    OR (graph_kind IN ('SHORT_TERM_WORKING','USER_EPISODIC','USER_SEMANTIC') AND owner_user_id IS NOT NULL)
  ),
  CONSTRAINT trimem_edge_valid_range CHECK
    (valid_from IS NULL OR valid_until IS NULL OR valid_until >= valid_from),
  CONSTRAINT trimem_shared_edge_reviewed CHECK (
    graph_kind <> 'ORGANISATION_SEMANTIC'
    OR (review_id IS NOT NULL AND reviewer_id IS NOT NULL AND reviewed_at IS NOT NULL
        AND review_authority IN ('HUMAN_REVIEW','TRUSTED_DOCUMENT')
        AND review_policy_version IS NOT NULL AND review_evidence_hash IS NOT NULL)
  )
);

CREATE TABLE trimem_semantic_supports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  namespace TEXT NOT NULL CHECK (length(btrim(namespace)) BETWEEN 1 AND 200),
  graph_id UUID NOT NULL,
  graph_kind TEXT NOT NULL CHECK (graph_kind IN ('USER_SEMANTIC','ORGANISATION_SEMANTIC')),
  owner_user_id UUID,
  semantic_node_id UUID NOT NULL,
  source_episode_id UUID,
  source_evidence_hash TEXT NOT NULL,
  contributor_hash TEXT,
  ingested_at TIMESTAMPTZ NOT NULL,
  event_time TIMESTAMPTZ,
  source_available_at TIMESTAMPTZ,
  last_accessed_at TIMESTAMPTZ,
  last_used_at TIMESTAMPTZ,
  last_verified_at TIMESTAMPTZ,
  valid_from TIMESTAMPTZ,
  valid_until TIMESTAMPTZ,
  review_id TEXT,
  reviewer_id TEXT,
  reviewed_at TIMESTAMPTZ,
  review_authority TEXT CHECK (review_authority IN ('HUMAN_REVIEW','TRUSTED_DOCUMENT')),
  review_policy_version TEXT,
  review_evidence_hash TEXT,
  content_hash TEXT NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
  UNIQUE (org_id, namespace, id),
  CONSTRAINT trimem_support_graph_fk FOREIGN KEY (org_id, namespace, graph_id)
    REFERENCES trimem_graphs(org_id, namespace, id),
  CONSTRAINT trimem_support_node_fk FOREIGN KEY (org_id, namespace, graph_id, semantic_node_id)
    REFERENCES trimem_graph_nodes(org_id, namespace, graph_id, id),
  CONSTRAINT trimem_support_episode_fk FOREIGN KEY (org_id, namespace, source_episode_id)
    REFERENCES trimem_graph_nodes(org_id, namespace, id),
  CONSTRAINT trimem_support_owner_scope CHECK (
    (graph_kind = 'ORGANISATION_SEMANTIC' AND owner_user_id IS NULL AND source_episode_id IS NULL)
    OR (graph_kind = 'USER_SEMANTIC' AND owner_user_id IS NOT NULL)
  ),
  CONSTRAINT trimem_support_valid_range CHECK
    (valid_from IS NULL OR valid_until IS NULL OR valid_until >= valid_from),
  CONSTRAINT trimem_shared_support_reviewed CHECK (
    graph_kind <> 'ORGANISATION_SEMANTIC'
    OR (review_id IS NOT NULL AND reviewer_id IS NOT NULL AND reviewed_at IS NOT NULL
        AND review_authority IN ('HUMAN_REVIEW','TRUSTED_DOCUMENT')
        AND review_policy_version IS NOT NULL AND review_evidence_hash IS NOT NULL)
  )
);

CREATE TABLE trimem_memory_access_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  namespace TEXT NOT NULL CHECK (length(btrim(namespace)) BETWEEN 1 AND 200),
  graph_id UUID NOT NULL,
  graph_kind TEXT NOT NULL CHECK (graph_kind IN
    ('SHORT_TERM_WORKING','USER_EPISODIC','USER_SEMANTIC','ORGANISATION_SEMANTIC')),
  owner_user_id UUID,
  node_id UUID NOT NULL,
  actor_user_id UUID NOT NULL REFERENCES users(id),
  access_type TEXT NOT NULL CHECK (access_type IN ('SEARCHED','BROWSED','INJECTED','USED','VERIFIED')),
  event_time TIMESTAMPTZ NOT NULL,
  injected_byte_count BIGINT NOT NULL DEFAULT 0 CHECK (injected_byte_count >= 0),
  injected_hash TEXT,
  evidence_ref TEXT,
  content_hash TEXT NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
  UNIQUE (org_id, namespace, id),
  CONSTRAINT trimem_access_graph_fk FOREIGN KEY (org_id, namespace, graph_id)
    REFERENCES trimem_graphs(org_id, namespace, id),
  CONSTRAINT trimem_access_node_fk FOREIGN KEY (org_id, namespace, graph_id, node_id)
    REFERENCES trimem_graph_nodes(org_id, namespace, graph_id, id),
  CONSTRAINT trimem_access_owner_scope CHECK (
    (graph_kind = 'ORGANISATION_SEMANTIC' AND owner_user_id IS NULL)
    OR (graph_kind IN ('SHORT_TERM_WORKING','USER_EPISODIC','USER_SEMANTIC') AND owner_user_id IS NOT NULL)
  ),
  CONSTRAINT trimem_access_injection_accounting CHECK (
    (access_type = 'INJECTED' AND injected_hash IS NOT NULL)
    OR (access_type <> 'INJECTED' AND injected_hash IS NULL AND injected_byte_count = 0)
  )
);

CREATE TABLE trimem_graph_checkpoints (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  namespace TEXT NOT NULL CHECK (length(btrim(namespace)) BETWEEN 1 AND 200),
  graph_id UUID NOT NULL,
  graph_kind TEXT NOT NULL DEFAULT 'SHORT_TERM_WORKING'
    CHECK (graph_kind = 'SHORT_TERM_WORKING'),
  owner_user_id UUID NOT NULL,
  sequence_no BIGINT NOT NULL CHECK (sequence_no >= 0),
  graph_content_hash TEXT NOT NULL CHECK (graph_content_hash ~ '^sha256:[0-9a-f]{64}$'),
  active_node_id UUID,
  evidence_ref TEXT,
  evidence_hash TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  content_hash TEXT NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
  UNIQUE (org_id, namespace, id),
  UNIQUE (org_id, namespace, graph_id, sequence_no),
  CONSTRAINT trimem_checkpoint_graph_fk FOREIGN KEY (org_id, namespace, graph_id)
    REFERENCES trimem_graphs(org_id, namespace, id),
  CONSTRAINT trimem_checkpoint_active_node_fk FOREIGN KEY (org_id, namespace, graph_id, active_node_id)
    REFERENCES trimem_graph_nodes(org_id, namespace, graph_id, id),
  CONSTRAINT trimem_checkpoint_evidence_pair CHECK
    ((evidence_ref IS NULL AND evidence_hash IS NULL) OR (evidence_ref IS NOT NULL AND evidence_hash IS NOT NULL))
);

CREATE TABLE trimem_policy_transitions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  namespace TEXT NOT NULL CHECK (length(btrim(namespace)) BETWEEN 1 AND 200),
  graph_id UUID NOT NULL,
  graph_kind TEXT NOT NULL DEFAULT 'SHORT_TERM_WORKING'
    CHECK (graph_kind = 'SHORT_TERM_WORKING'),
  owner_user_id UUID NOT NULL,
  candidate_node_id UUID NOT NULL,
  action TEXT NOT NULL CHECK (action IN
    ('FORGET','MOVE_TO_EPISODIC','MOVE_TO_SEMANTIC_CANDIDATE')),
  actor TEXT NOT NULL CHECK (actor IN ('DOUBLE_DQN','HEURISTIC','MANUAL','SYSTEM')),
  target_graph_kind TEXT CHECK (target_graph_kind IN ('USER_EPISODIC','USER_SEMANTIC')),
  state_features_hash TEXT,
  reward DOUBLE PRECISION,
  delayed_credit_ref TEXT,
  event_time TIMESTAMPTZ NOT NULL,
  content_hash TEXT NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
  UNIQUE (org_id, namespace, id),
  CONSTRAINT trimem_transition_graph_fk FOREIGN KEY (org_id, namespace, graph_id)
    REFERENCES trimem_graphs(org_id, namespace, id),
  CONSTRAINT trimem_transition_node_fk FOREIGN KEY (org_id, namespace, graph_id, candidate_node_id)
    REFERENCES trimem_graph_nodes(org_id, namespace, graph_id, id),
  CONSTRAINT trimem_policy_cannot_publish_shared CHECK (target_graph_kind IS DISTINCT FROM 'ORGANISATION_SEMANTIC'),
  CONSTRAINT trimem_policy_target_matches_action CHECK (
    (action = 'FORGET' AND target_graph_kind IS NULL)
    OR (action = 'MOVE_TO_EPISODIC' AND target_graph_kind = 'USER_EPISODIC')
    OR (action = 'MOVE_TO_SEMANTIC_CANDIDATE' AND target_graph_kind = 'USER_SEMANTIC')
  )
);

CREATE TABLE trimem_semantic_strengths (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  namespace TEXT NOT NULL CHECK (length(btrim(namespace)) BETWEEN 1 AND 200),
  graph_id UUID NOT NULL,
  graph_kind TEXT NOT NULL CHECK (graph_kind IN ('USER_SEMANTIC','ORGANISATION_SEMANTIC')),
  owner_user_id UUID,
  semantic_node_id UUID NOT NULL,
  support DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (support >= 0),
  successful_reuse DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (successful_reuse >= 0),
  independent_user_evidence DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (independent_user_evidence >= 0),
  recent_verification DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (recent_verification >= 0),
  negative_transfer DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (negative_transfer >= 0),
  contradiction DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (contradiction >= 0),
  version_staleness DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (version_staleness >= 0),
  strength_score DOUBLE PRECISION GENERATED ALWAYS AS
    (support + successful_reuse + independent_user_evidence + recent_verification
      - negative_transfer - contradiction - version_staleness) STORED,
  updated_at TIMESTAMPTZ NOT NULL,
  content_hash TEXT NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
  UNIQUE (org_id, namespace, id),
  UNIQUE (org_id, namespace, graph_id, semantic_node_id),
  CONSTRAINT trimem_strength_graph_fk FOREIGN KEY (org_id, namespace, graph_id)
    REFERENCES trimem_graphs(org_id, namespace, id),
  CONSTRAINT trimem_strength_node_fk FOREIGN KEY (org_id, namespace, graph_id, semantic_node_id)
    REFERENCES trimem_graph_nodes(org_id, namespace, graph_id, id),
  CONSTRAINT trimem_strength_owner_scope CHECK (
    (graph_kind = 'ORGANISATION_SEMANTIC' AND owner_user_id IS NULL)
    OR (graph_kind = 'USER_SEMANTIC' AND owner_user_id IS NOT NULL)
  )
);

-- A durable namespace claim closes the count-then-write freshness race between
-- benchmark workers.  The exact task/config hashes bind a namespace to one arm.
CREATE TABLE trimem_namespace_claims (
  org_id UUID NOT NULL REFERENCES organisations(id),
  namespace TEXT NOT NULL CHECK (length(btrim(namespace)) BETWEEN 1 AND 200),
  owner_user_id UUID NOT NULL REFERENCES users(id),
  experiment_id TEXT NOT NULL,
  split TEXT NOT NULL,
  arm_id TEXT NOT NULL,
  task_order_hash TEXT NOT NULL CHECK (task_order_hash ~ '^sha256:[0-9a-f]{64}$'),
  config_hash TEXT NOT NULL CHECK (config_hash ~ '^sha256:[0-9a-f]{64}$'),
  run_nonce UUID NOT NULL,
  next_sequence_index BIGINT NOT NULL DEFAULT 0 CHECK (next_sequence_index >= 0),
  claim_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (claim_status IN ('ACTIVE','CLOSED')),
  claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, namespace),
  UNIQUE (org_id, namespace, run_nonce),
  UNIQUE (run_nonce)
);

-- PostgreSQL owns the durable intent to mirror one canonical node into Qdrant.
-- A committed PENDING row survives a vector-service outage; reconciliation may
-- mark it INDEXED only after reloading and hash-checking the canonical node.
CREATE TABLE trimem_vector_index_outbox (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL REFERENCES organisations(id),
  namespace TEXT NOT NULL CHECK (length(btrim(namespace)) BETWEEN 1 AND 200),
  graph_id UUID NOT NULL,
  graph_kind TEXT NOT NULL CHECK (graph_kind IN
    ('USER_EPISODIC','USER_SEMANTIC','ORGANISATION_SEMANTIC')),
  owner_user_id UUID,
  node_id UUID NOT NULL,
  operation TEXT NOT NULL DEFAULT 'UPSERT' CHECK (operation IN ('UPSERT','DELETE')),
  canonical_content_hash TEXT NOT NULL
    CHECK (canonical_content_hash ~ '^sha256:[0-9a-f]{64}$'),
  prior_content_hash TEXT
    CHECK (prior_content_hash IS NULL OR prior_content_hash ~ '^sha256:[0-9a-f]{64}$'),
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING','INDEXED','CANCELLED')),
  attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  last_error TEXT CHECK (last_error IS NULL OR length(last_error) <= 500),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  indexed_at TIMESTAMPTZ,
  UNIQUE (org_id, namespace, node_id, canonical_content_hash),
  CONSTRAINT trimem_outbox_node_fk
    FOREIGN KEY (org_id, namespace, graph_id, node_id)
    REFERENCES trimem_graph_nodes(org_id, namespace, graph_id, id),
  CONSTRAINT trimem_outbox_owner_scope CHECK (
    (graph_kind = 'ORGANISATION_SEMANTIC' AND owner_user_id IS NULL)
    OR (graph_kind IN ('USER_EPISODIC','USER_SEMANTIC') AND owner_user_id IS NOT NULL)
  ),
  CONSTRAINT trimem_outbox_status_shape CHECK (
    (status = 'PENDING' AND indexed_at IS NULL)
    OR (status = 'INDEXED' AND indexed_at IS NOT NULL AND last_error IS NULL)
    OR (status = 'CANCELLED' AND indexed_at IS NULL AND last_error IS NULL)
  ),
  CONSTRAINT trimem_outbox_operation_shape CHECK (
    (operation = 'UPSERT' AND prior_content_hash IS NULL)
    OR (operation = 'DELETE' AND prior_content_hash IS NOT NULL
      AND prior_content_hash <> canonical_content_hash)
  )
);

-- Crash-safe benchmark/session cursor journal.  The claim CAS and immutable
-- envelope insert are committed by one repository transaction.
CREATE TABLE trimem_session_checkpoints (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL REFERENCES organisations(id),
  namespace TEXT NOT NULL CHECK (length(btrim(namespace)) BETWEEN 1 AND 200),
  owner_user_id UUID NOT NULL REFERENCES users(id),
  run_nonce UUID NOT NULL,
  next_sequence_index BIGINT NOT NULL CHECK (next_sequence_index >= 0),
  checkpoint_schema TEXT NOT NULL CHECK (length(btrim(checkpoint_schema)) BETWEEN 1 AND 200),
  checkpoint_payload JSONB NOT NULL CHECK (jsonb_typeof(checkpoint_payload) = 'object'),
  checkpoint_digest TEXT NOT NULL CHECK (checkpoint_digest ~ '^sha256:[0-9a-f]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, namespace, run_nonce, next_sequence_index),
  CONSTRAINT trimem_session_checkpoint_envelope CHECK (
    checkpoint_payload->>'schema' = checkpoint_schema
    AND checkpoint_payload->>'namespace' = namespace
    AND checkpoint_payload->>'run_nonce' = run_nonce::text
    AND checkpoint_payload->>'next_sequence_index' ~ '^(0|[1-9][0-9]*)$'
    AND (checkpoint_payload->>'next_sequence_index')::bigint = next_sequence_index
  ),
  CONSTRAINT trimem_session_checkpoint_claim_fk
    FOREIGN KEY (org_id, namespace, run_nonce)
    REFERENCES trimem_namespace_claims(org_id, namespace, run_nonce)
);

-- Durable exact-once receipt for canonical lifecycle bundle application.  It
-- closes the crash window after PostgreSQL commit but before the task-local
-- checkpoint is written.  The payload contains canonical identifiers/hashes,
-- never execution content.
CREATE TABLE trimem_lifecycle_operation_receipts (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL REFERENCES organisations(id),
  namespace TEXT NOT NULL CHECK (length(btrim(namespace)) BETWEEN 1 AND 200),
  owner_user_id UUID NOT NULL REFERENCES users(id),
  bundle_digest TEXT NOT NULL CHECK (bundle_digest ~ '^sha256:[0-9a-f]{64}$'),
  receipt_payload JSONB NOT NULL CHECK (jsonb_typeof(receipt_payload) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, namespace, id),
  CONSTRAINT trimem_lifecycle_receipt_identity CHECK (
    receipt_payload->>'operation_id' = id::text
    AND receipt_payload->>'bundle_digest' = bundle_digest
    AND receipt_payload->>'namespace' = namespace
  )
);

-- Org-visible, content-free promotion attestations.  No private episode,
-- node, user, task, or canonical-content identifier is stored here.
CREATE TABLE trimem_promotion_evidence (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL REFERENCES organisations(id),
  namespace TEXT NOT NULL CHECK (length(btrim(namespace)) BETWEEN 1 AND 200),
  evidence_hash TEXT NOT NULL CHECK (evidence_hash ~ '^sha256:[0-9a-f]{64}$'),
  contributor_hash TEXT NOT NULL CHECK (contributor_hash ~ '^sha256:[0-9a-f]{64}$'),
  source_kind TEXT NOT NULL CHECK (source_kind = 'VERIFIED_EPISODE'),
  source_outcome TEXT NOT NULL CHECK (source_outcome = 'passed'),
  verified BOOLEAN NOT NULL CHECK (verified),
  public_evidence_hash TEXT NOT NULL CHECK (public_evidence_hash ~ '^sha256:[0-9a-f]{64}$'),
  verifier_hash TEXT NOT NULL CHECK (verifier_hash ~ '^sha256:[0-9a-f]{64}$'),
  extraction_hash TEXT NOT NULL CHECK (extraction_hash ~ '^sha256:[0-9a-f]{64}$'),
  attestation_hash TEXT NOT NULL CHECK (attestation_hash ~ '^sha256:[0-9a-f]{64}$'),
  verified_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, namespace, evidence_hash, contributor_hash),
  UNIQUE (org_id, namespace, attestation_hash)
);

-- Header ownership is checked against canonical users/repos/jobs in the same tenant.
CREATE FUNCTION trimem_validate_graph_header() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND
     (NEW.id, NEW.org_id, NEW.namespace, NEW.graph_kind, NEW.owner_user_id)
       IS DISTINCT FROM (OLD.id, OLD.org_id, OLD.namespace, OLD.graph_kind, OLD.owner_user_id) THEN
    RAISE EXCEPTION 'trimem graph identity/partition is immutable';
  END IF;
  IF NEW.owner_user_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM users u WHERE u.id = NEW.owner_user_id AND u.org_id = NEW.org_id
  ) THEN
    RAISE EXCEPTION 'trimem graph owner is not in organisation';
  END IF;
  IF NEW.repository_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM repositories r WHERE r.id = NEW.repository_id AND r.org_id = NEW.org_id
  ) THEN
    RAISE EXCEPTION 'trimem graph repository is not in organisation';
  END IF;
  IF NEW.solve_job_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM solve_jobs j
      WHERE j.id = NEW.solve_job_id AND j.org_id = NEW.org_id
        AND (NEW.owner_user_id IS NULL OR j.submitter_user_id = NEW.owner_user_id)
        AND (NEW.repository_id IS NULL OR j.repository_id = NEW.repository_id)
  ) THEN
    RAISE EXCEPTION 'trimem graph solve job is outside owner/repository partition';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trimem_graph_header_guard BEFORE INSERT OR UPDATE ON trimem_graphs
  FOR EACH ROW EXECUTE FUNCTION trimem_validate_graph_header();

-- Outbox references are immutable and must repeat the exact canonical node
-- partition/hash.  Status/attempt/error timestamps are the only mutable fields.
CREATE FUNCTION trimem_validate_vector_outbox() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
  node_graph_id UUID;
  node_kind TEXT;
  node_owner UUID;
  node_hash TEXT;
  node_state TEXT;
  node_archived_from TEXT;
BEGIN
  IF TG_OP = 'INSERT' AND (NEW.status <> 'PENDING' OR NEW.attempts <> 0) THEN
    RAISE EXCEPTION 'new trimem vector outbox intent must be pending and unattempted';
  END IF;
  IF TG_OP = 'UPDATE' AND
     (NEW.id, NEW.org_id, NEW.namespace, NEW.graph_id, NEW.graph_kind,
      NEW.owner_user_id, NEW.node_id, NEW.operation, NEW.canonical_content_hash,
      NEW.prior_content_hash)
       IS DISTINCT FROM
     (OLD.id, OLD.org_id, OLD.namespace, OLD.graph_id, OLD.graph_kind,
      OLD.owner_user_id, OLD.node_id, OLD.operation, OLD.canonical_content_hash,
      OLD.prior_content_hash) THEN
    RAISE EXCEPTION 'trimem vector outbox identity is immutable';
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.status IN ('INDEXED','CANCELLED') THEN
    RAISE EXCEPTION 'completed trimem vector outbox intent is terminal';
  END IF;
  IF TG_OP = 'UPDATE' AND NEW.attempts < OLD.attempts THEN
    RAISE EXCEPTION 'trimem vector outbox attempts cannot decrease';
  END IF;
  SELECT graph_id, graph_kind, owner_user_id, content_hash, lifecycle_state,
         archived_from_content_hash
    INTO node_graph_id, node_kind, node_owner, node_hash, node_state,
         node_archived_from
    FROM trimem_graph_nodes
    WHERE org_id = NEW.org_id AND namespace = NEW.namespace AND id = NEW.node_id;
  IF NOT FOUND OR node_graph_id IS DISTINCT FROM NEW.graph_id
     OR node_kind IS DISTINCT FROM NEW.graph_kind
     OR node_owner IS DISTINCT FROM NEW.owner_user_id
     OR (NEW.operation = 'UPSERT' AND NEW.status <> 'CANCELLED' AND
       (node_state <> 'ACTIVE' OR node_hash IS DISTINCT FROM NEW.canonical_content_hash))
     OR (NEW.operation = 'UPSERT' AND NEW.status = 'CANCELLED' AND
       (node_state NOT IN ('ARCHIVED','TOMBSTONED')
        OR node_archived_from IS DISTINCT FROM NEW.canonical_content_hash))
     OR (NEW.operation = 'DELETE' AND
       (node_state NOT IN ('ARCHIVED','TOMBSTONED')
        OR node_hash IS DISTINCT FROM NEW.canonical_content_hash
        OR node_archived_from IS DISTINCT FROM NEW.prior_content_hash)) THEN
    RAISE EXCEPTION 'trimem vector outbox intent does not match canonical node state';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trimem_vector_outbox_guard
  BEFORE INSERT OR UPDATE ON trimem_vector_index_outbox
  FOR EACH ROW EXECUTE FUNCTION trimem_validate_vector_outbox();

CREATE FUNCTION trimem_validate_promotion_evidence() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM trimem_graph_nodes n
    WHERE n.org_id = NEW.org_id AND n.namespace = NEW.namespace
      AND n.graph_kind = 'USER_EPISODIC' AND n.node_type = 'Episode'
      AND n.owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid
      AND n.lifecycle_state = 'ACTIVE' AND n.payload_hash = NEW.evidence_hash
      AND n.canonical_payload->>'verified' = 'true'
      AND n.canonical_payload->>'source_outcome' = 'passed'
      AND n.canonical_payload#>>'{provenance,contributor_hash}' = NEW.contributor_hash
      AND n.canonical_payload#>>'{provenance,public_evidence_hash}' = NEW.public_evidence_hash
      AND n.canonical_payload#>>'{provenance,verifier_hash}' = NEW.verifier_hash
      AND n.canonical_payload#>>'{provenance,extraction_hash}' = NEW.extraction_hash
      AND n.last_verified_at = NEW.verified_at
  ) THEN
    RAISE EXCEPTION 'promotion evidence has no matching verified private episode';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trimem_promotion_evidence_guard
  BEFORE INSERT ON trimem_promotion_evidence
  FOR EACH ROW EXECUTE FUNCTION trimem_validate_promotion_evidence();

-- All child rows must exactly repeat the graph's security partition.
CREATE FUNCTION trimem_enforce_graph_partition() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
  header_namespace TEXT;
  header_kind TEXT;
  header_owner UUID;
  header_state TEXT;
BEGIN
  SELECT namespace, graph_kind, owner_user_id, graph_state
    INTO header_namespace, header_kind, header_owner, header_state
    FROM trimem_graphs
    WHERE org_id = NEW.org_id AND namespace = NEW.namespace AND id = NEW.graph_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'trimem graph header is unavailable';
  END IF;
  IF NEW.namespace IS DISTINCT FROM header_namespace
     OR NEW.graph_kind IS DISTINCT FROM header_kind
     OR NEW.owner_user_id IS DISTINCT FROM header_owner THEN
    RAISE EXCEPTION 'trimem child partition does not match graph header';
  END IF;
  IF header_state <> 'ACTIVE' AND TG_TABLE_NAME <> 'trimem_memory_access_events' THEN
    RAISE EXCEPTION 'only access audit may append to a sealed or archived trimem graph';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER trimem_node_partition_guard BEFORE INSERT OR UPDATE ON trimem_graph_nodes
  FOR EACH ROW EXECUTE FUNCTION trimem_enforce_graph_partition();
CREATE TRIGGER trimem_edge_partition_guard BEFORE INSERT OR UPDATE ON trimem_graph_edges
  FOR EACH ROW EXECUTE FUNCTION trimem_enforce_graph_partition();
CREATE TRIGGER trimem_support_partition_guard BEFORE INSERT OR UPDATE ON trimem_semantic_supports
  FOR EACH ROW EXECUTE FUNCTION trimem_enforce_graph_partition();
CREATE TRIGGER trimem_access_partition_guard BEFORE INSERT OR UPDATE ON trimem_memory_access_events
  FOR EACH ROW EXECUTE FUNCTION trimem_enforce_graph_partition();
CREATE TRIGGER trimem_checkpoint_partition_guard BEFORE INSERT OR UPDATE ON trimem_graph_checkpoints
  FOR EACH ROW EXECUTE FUNCTION trimem_enforce_graph_partition();
CREATE TRIGGER trimem_transition_partition_guard BEFORE INSERT OR UPDATE ON trimem_policy_transitions
  FOR EACH ROW EXECUTE FUNCTION trimem_enforce_graph_partition();
CREATE TRIGGER trimem_strength_partition_guard BEFORE INSERT OR UPDATE ON trimem_semantic_strengths
  FOR EACH ROW EXECUTE FUNCTION trimem_enforce_graph_partition();

CREATE FUNCTION trimem_validate_support_source() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE source_owner UUID; source_kind TEXT; source_type TEXT; source_payload_hash TEXT;
BEGIN
  IF NEW.source_episode_id IS NULL THEN RETURN NEW; END IF;
  SELECT owner_user_id, graph_kind, node_type, payload_hash
    INTO source_owner, source_kind, source_type, source_payload_hash
    FROM trimem_graph_nodes
    WHERE org_id = NEW.org_id AND namespace = NEW.namespace AND id = NEW.source_episode_id;
  IF NOT FOUND OR source_kind <> 'USER_EPISODIC' OR source_type <> 'Episode'
     OR source_owner IS DISTINCT FROM NEW.owner_user_id
     OR source_payload_hash IS DISTINCT FROM NEW.source_evidence_hash THEN
    RAISE EXCEPTION 'semantic support source is outside the private episode partition';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trimem_support_source_guard BEFORE INSERT OR UPDATE ON trimem_semantic_supports
  FOR EACH ROW EXECUTE FUNCTION trimem_validate_support_source();

CREATE FUNCTION trimem_validate_semantic_target() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE target_type TEXT; target_kind TEXT; target_owner UUID;
BEGIN
  SELECT node_type, graph_kind, owner_user_id INTO target_type, target_kind, target_owner
    FROM trimem_graph_nodes
    WHERE org_id = NEW.org_id AND namespace = NEW.namespace
      AND graph_id = NEW.graph_id AND id = NEW.semantic_node_id;
  IF NOT FOUND OR target_type <> 'SemanticRule'
     OR target_kind IS DISTINCT FROM NEW.graph_kind
     OR target_owner IS DISTINCT FROM NEW.owner_user_id THEN
    RAISE EXCEPTION 'semantic metadata target is not a rule in the same partition';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trimem_support_semantic_target_guard BEFORE INSERT OR UPDATE ON trimem_semantic_supports
  FOR EACH ROW EXECUTE FUNCTION trimem_validate_semantic_target();
CREATE TRIGGER trimem_strength_semantic_target_guard BEFORE INSERT OR UPDATE ON trimem_semantic_strengths
  FOR EACH ROW EXECUTE FUNCTION trimem_validate_semantic_target();

-- Strength is cumulative evidence state.  Replacement may only advance its
-- exact semantic target and monotonic component counters; stale retry data can
-- never lower a score component or rebind the row to another rule.
CREATE FUNCTION trimem_validate_strength_monotonic() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
  IF (NEW.id, NEW.org_id, NEW.namespace, NEW.graph_id, NEW.graph_kind,
      NEW.owner_user_id, NEW.semantic_node_id)
       IS DISTINCT FROM
     (OLD.id, OLD.org_id, OLD.namespace, OLD.graph_id, OLD.graph_kind,
      OLD.owner_user_id, OLD.semantic_node_id) THEN
    RAISE EXCEPTION 'trimem semantic strength identity is immutable';
  END IF;
  IF NEW.updated_at < OLD.updated_at
     OR NEW.support < OLD.support
     OR NEW.successful_reuse < OLD.successful_reuse
     OR NEW.independent_user_evidence < OLD.independent_user_evidence
     OR NEW.recent_verification < OLD.recent_verification
     OR NEW.negative_transfer < OLD.negative_transfer
     OR NEW.contradiction < OLD.contradiction
     OR NEW.version_staleness < OLD.version_staleness THEN
    RAISE EXCEPTION 'trimem semantic strength components are monotonic';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trimem_strength_monotonic_guard BEFORE UPDATE ON trimem_semantic_strengths
  FOR EACH ROW EXECUTE FUNCTION trimem_validate_strength_monotonic();

CREATE FUNCTION trimem_validate_access_actor() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM users u WHERE u.id = NEW.actor_user_id AND u.org_id = NEW.org_id) THEN
    RAISE EXCEPTION 'memory access actor is outside organisation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trimem_access_actor_guard BEFORE INSERT OR UPDATE ON trimem_memory_access_events
  FOR EACH ROW EXECUTE FUNCTION trimem_validate_access_actor();

-- DECOMPOSES_TO and DEPENDS_ON together form an acyclic structural graph.
CREATE FUNCTION trimem_reject_structural_cycle() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE cycle_found BOOLEAN;
BEGIN
  IF NEW.lifecycle_state <> 'ACTIVE' OR NEW.edge_type NOT IN ('DECOMPOSES_TO','DEPENDS_ON') THEN
    RETURN NEW;
  END IF;
  WITH RECURSIVE reachable(node_id) AS (
    SELECT NEW.target_node_id
    UNION
    SELECT e.target_node_id
      FROM trimem_graph_edges e JOIN reachable r ON e.source_node_id = r.node_id
      WHERE e.org_id = NEW.org_id AND e.namespace = NEW.namespace
        AND e.graph_id = NEW.graph_id
        AND e.lifecycle_state = 'ACTIVE' AND e.edge_type IN ('DECOMPOSES_TO','DEPENDS_ON')
        AND e.id <> NEW.id
  ) SELECT EXISTS (SELECT 1 FROM reachable WHERE node_id = NEW.source_node_id) INTO cycle_found;
  IF cycle_found THEN RAISE EXCEPTION 'trimem structural cycle is forbidden'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trimem_edge_cycle_guard BEFORE INSERT OR UPDATE ON trimem_graph_edges
  FOR EACH ROW EXECUTE FUNCTION trimem_reject_structural_cycle();

-- Tenant policy is permissive; owner policy is restrictive.  Both must pass.
ALTER TABLE trimem_graphs ENABLE ROW LEVEL SECURITY;
ALTER TABLE trimem_graphs FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON trimem_graphs USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
CREATE POLICY namespace_isolation ON trimem_graphs AS RESTRICTIVE USING
  (namespace = nullif(current_setting('app.trimem_namespace', true), ''))
  WITH CHECK (namespace = nullif(current_setting('app.trimem_namespace', true), ''));
CREATE POLICY private_owner ON trimem_graphs AS RESTRICTIVE USING
  (graph_kind = 'ORGANISATION_SEMANTIC'
    OR owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid)
  WITH CHECK (graph_kind = 'ORGANISATION_SEMANTIC'
    OR owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE trimem_graph_nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE trimem_graph_nodes FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON trimem_graph_nodes USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
CREATE POLICY namespace_isolation ON trimem_graph_nodes AS RESTRICTIVE USING
  (namespace = nullif(current_setting('app.trimem_namespace', true), ''))
  WITH CHECK (namespace = nullif(current_setting('app.trimem_namespace', true), ''));
CREATE POLICY private_owner ON trimem_graph_nodes AS RESTRICTIVE USING
  (graph_kind = 'ORGANISATION_SEMANTIC'
    OR owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid)
  WITH CHECK (graph_kind = 'ORGANISATION_SEMANTIC'
    OR owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE trimem_graph_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE trimem_graph_edges FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON trimem_graph_edges USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
CREATE POLICY namespace_isolation ON trimem_graph_edges AS RESTRICTIVE USING
  (namespace = nullif(current_setting('app.trimem_namespace', true), ''))
  WITH CHECK (namespace = nullif(current_setting('app.trimem_namespace', true), ''));
CREATE POLICY private_owner ON trimem_graph_edges AS RESTRICTIVE USING
  (graph_kind = 'ORGANISATION_SEMANTIC'
    OR owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid)
  WITH CHECK (graph_kind = 'ORGANISATION_SEMANTIC'
    OR owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE trimem_semantic_supports ENABLE ROW LEVEL SECURITY;
ALTER TABLE trimem_semantic_supports FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON trimem_semantic_supports USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
CREATE POLICY namespace_isolation ON trimem_semantic_supports AS RESTRICTIVE USING
  (namespace = nullif(current_setting('app.trimem_namespace', true), ''))
  WITH CHECK (namespace = nullif(current_setting('app.trimem_namespace', true), ''));
CREATE POLICY private_owner ON trimem_semantic_supports AS RESTRICTIVE USING
  (graph_kind = 'ORGANISATION_SEMANTIC'
    OR owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid)
  WITH CHECK (graph_kind = 'ORGANISATION_SEMANTIC'
    OR owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE trimem_memory_access_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE trimem_memory_access_events FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON trimem_memory_access_events USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
CREATE POLICY namespace_isolation ON trimem_memory_access_events AS RESTRICTIVE USING
  (namespace = nullif(current_setting('app.trimem_namespace', true), ''))
  WITH CHECK (namespace = nullif(current_setting('app.trimem_namespace', true), ''));
CREATE POLICY private_owner ON trimem_memory_access_events AS RESTRICTIVE USING
  (graph_kind = 'ORGANISATION_SEMANTIC'
    OR owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid)
  WITH CHECK (graph_kind = 'ORGANISATION_SEMANTIC'
    OR owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE trimem_graph_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE trimem_graph_checkpoints FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON trimem_graph_checkpoints USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
CREATE POLICY namespace_isolation ON trimem_graph_checkpoints AS RESTRICTIVE USING
  (namespace = nullif(current_setting('app.trimem_namespace', true), ''))
  WITH CHECK (namespace = nullif(current_setting('app.trimem_namespace', true), ''));
CREATE POLICY private_owner ON trimem_graph_checkpoints AS RESTRICTIVE USING
  (owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid)
  WITH CHECK (owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE trimem_policy_transitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE trimem_policy_transitions FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON trimem_policy_transitions USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
CREATE POLICY namespace_isolation ON trimem_policy_transitions AS RESTRICTIVE USING
  (namespace = nullif(current_setting('app.trimem_namespace', true), ''))
  WITH CHECK (namespace = nullif(current_setting('app.trimem_namespace', true), ''));
CREATE POLICY private_owner ON trimem_policy_transitions AS RESTRICTIVE USING
  (owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid)
  WITH CHECK (owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE trimem_semantic_strengths ENABLE ROW LEVEL SECURITY;
ALTER TABLE trimem_semantic_strengths FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON trimem_semantic_strengths USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
CREATE POLICY namespace_isolation ON trimem_semantic_strengths AS RESTRICTIVE USING
  (namespace = nullif(current_setting('app.trimem_namespace', true), ''))
  WITH CHECK (namespace = nullif(current_setting('app.trimem_namespace', true), ''));
CREATE POLICY private_owner ON trimem_semantic_strengths AS RESTRICTIVE USING
  (graph_kind = 'ORGANISATION_SEMANTIC'
    OR owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid)
  WITH CHECK (graph_kind = 'ORGANISATION_SEMANTIC'
    OR owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE trimem_namespace_claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE trimem_namespace_claims FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON trimem_namespace_claims USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
CREATE POLICY namespace_isolation ON trimem_namespace_claims AS RESTRICTIVE USING
  (namespace = nullif(current_setting('app.trimem_namespace', true), ''))
  WITH CHECK (namespace = nullif(current_setting('app.trimem_namespace', true), ''));
CREATE POLICY private_owner ON trimem_namespace_claims AS RESTRICTIVE USING
  (owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid)
  WITH CHECK (owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE trimem_vector_index_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE trimem_vector_index_outbox FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON trimem_vector_index_outbox USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
CREATE POLICY namespace_isolation ON trimem_vector_index_outbox AS RESTRICTIVE USING
  (namespace = nullif(current_setting('app.trimem_namespace', true), ''))
  WITH CHECK (namespace = nullif(current_setting('app.trimem_namespace', true), ''));
CREATE POLICY private_owner ON trimem_vector_index_outbox AS RESTRICTIVE USING
  (graph_kind = 'ORGANISATION_SEMANTIC'
    OR owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid)
  WITH CHECK (graph_kind = 'ORGANISATION_SEMANTIC'
    OR owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE trimem_session_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE trimem_session_checkpoints FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON trimem_session_checkpoints USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
CREATE POLICY namespace_isolation ON trimem_session_checkpoints AS RESTRICTIVE USING
  (namespace = nullif(current_setting('app.trimem_namespace', true), ''))
  WITH CHECK (namespace = nullif(current_setting('app.trimem_namespace', true), ''));
CREATE POLICY private_owner ON trimem_session_checkpoints AS RESTRICTIVE USING
  (owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid)
  WITH CHECK (owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE trimem_lifecycle_operation_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE trimem_lifecycle_operation_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON trimem_lifecycle_operation_receipts USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
CREATE POLICY namespace_isolation ON trimem_lifecycle_operation_receipts AS RESTRICTIVE USING
  (namespace = nullif(current_setting('app.trimem_namespace', true), ''))
  WITH CHECK (namespace = nullif(current_setting('app.trimem_namespace', true), ''));
CREATE POLICY private_owner ON trimem_lifecycle_operation_receipts AS RESTRICTIVE USING
  (owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid)
  WITH CHECK (owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid);

ALTER TABLE trimem_promotion_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE trimem_promotion_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON trimem_promotion_evidence USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
CREATE POLICY namespace_isolation ON trimem_promotion_evidence AS RESTRICTIVE USING
  (namespace = nullif(current_setting('app.trimem_namespace', true), ''))
  WITH CHECK (namespace = nullif(current_setting('app.trimem_namespace', true), ''));

-- Evidence, access, checkpoints, and policy decisions are append-only audit facts.
CREATE TRIGGER trimem_support_immutable BEFORE UPDATE OR DELETE ON trimem_semantic_supports
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER trimem_access_immutable BEFORE UPDATE OR DELETE ON trimem_memory_access_events
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER trimem_checkpoint_immutable BEFORE UPDATE OR DELETE ON trimem_graph_checkpoints
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER trimem_transition_immutable BEFORE UPDATE OR DELETE ON trimem_policy_transitions
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER trimem_session_checkpoint_immutable
  BEFORE UPDATE OR DELETE ON trimem_session_checkpoints
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER trimem_lifecycle_receipt_immutable
  BEFORE UPDATE OR DELETE ON trimem_lifecycle_operation_receipts
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER trimem_promotion_evidence_immutable
  BEFORE UPDATE OR DELETE ON trimem_promotion_evidence
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();

CREATE INDEX ix_trimem_graph_owner_kind ON trimem_graphs (org_id, owner_user_id, graph_kind);
CREATE INDEX ix_trimem_node_graph_active ON trimem_graph_nodes (org_id, graph_id, node_type)
  WHERE lifecycle_state = 'ACTIVE';
CREATE INDEX ix_trimem_edge_graph_source ON trimem_graph_edges (org_id, graph_id, source_node_id)
  WHERE lifecycle_state = 'ACTIVE';
CREATE INDEX ix_trimem_support_semantic ON trimem_semantic_supports (org_id, semantic_node_id);
CREATE INDEX ix_trimem_access_node_time ON trimem_memory_access_events (org_id, node_id, event_time);
CREATE INDEX ix_trimem_strength_archive ON trimem_semantic_strengths
  (org_id, graph_id, strength_score, updated_at);
CREATE INDEX ix_trimem_vector_outbox_pending ON trimem_vector_index_outbox
  (org_id, namespace, created_at, id) WHERE status = 'PENDING';
CREATE INDEX ix_trimem_session_checkpoint_latest ON trimem_session_checkpoints
  (org_id, namespace, run_nonce, next_sequence_index DESC);
CREATE INDEX ix_trimem_promotion_evidence_hash ON trimem_promotion_evidence
  (org_id, namespace, evidence_hash);

GRANT SELECT, INSERT, UPDATE ON trimem_graphs, trimem_graph_nodes, trimem_graph_edges,
  trimem_semantic_strengths, trimem_namespace_claims, trimem_vector_index_outbox
  , trimem_session_checkpoints
  TO api_service, worker_service;
GRANT SELECT, INSERT ON trimem_semantic_supports, trimem_memory_access_events,
  trimem_graph_checkpoints, trimem_policy_transitions,
  trimem_lifecycle_operation_receipts TO api_service, worker_service;
GRANT SELECT, INSERT ON trimem_promotion_evidence TO api_service, worker_service;
GRANT SELECT ON trimem_graphs, trimem_graph_nodes TO index_worker_service;
GRANT SELECT, UPDATE ON trimem_vector_index_outbox TO index_worker_service;
GRANT SELECT ON trimem_memory_access_events, trimem_policy_transitions TO audit_reader;
GRANT SELECT ON alembic_version TO api_service;

REVOKE ALL ON FUNCTION trimem_validate_graph_header() FROM PUBLIC;
REVOKE ALL ON FUNCTION trimem_validate_vector_outbox() FROM PUBLIC;
REVOKE ALL ON FUNCTION trimem_validate_promotion_evidence() FROM PUBLIC;
REVOKE ALL ON FUNCTION trimem_enforce_graph_partition() FROM PUBLIC;
REVOKE ALL ON FUNCTION trimem_validate_support_source() FROM PUBLIC;
REVOKE ALL ON FUNCTION trimem_validate_semantic_target() FROM PUBLIC;
REVOKE ALL ON FUNCTION trimem_validate_strength_monotonic() FROM PUBLIC;
REVOKE ALL ON FUNCTION trimem_validate_access_actor() FROM PUBLIC;
REVOKE ALL ON FUNCTION trimem_reject_structural_cycle() FROM PUBLIC;
