-- P6/R19 §5: utility-aware shared-memory experience layer. 13 tenant-owned tables; PostgreSQL authoritative.
-- Every table: org_id, ENABLE+FORCE RLS, org_isolation policy (app.org_id), content hashes, UTC timestamps,
-- audit linkage, minimum-privilege grants. Version tables are append-only (no UPDATE grant => immutable rows).
-- Runs after 0013. Qdrant/Mem0 are indices only; canonical content lives here and is reloaded before use.

-- ============================ canonical experience ============================
CREATE TABLE experience_cards (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  card_key TEXT NOT NULL,
  current_version_id UUID,
  governance_state TEXT NOT NULL DEFAULT 'candidate'
    CHECK (governance_state IN ('candidate','probation','promoted','deprecated','quarantined','deleted')),
  bank TEXT NOT NULL CHECK (bank IN ('HISTORICAL_VERIFIED','USER_SUCCESS')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  UNIQUE (org_id, card_key));
ALTER TABLE experience_cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE experience_cards FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON experience_cards USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
GRANT SELECT, INSERT, UPDATE ON experience_cards TO api_service, worker_service;

CREATE TABLE experience_card_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  card_id UUID NOT NULL,
  schema_version INT NOT NULL DEFAULT 1,
  -- provenance
  source_type TEXT NOT NULL,
  source_task_id TEXT,
  source_repository TEXT,
  source_commit TEXT,
  source_issue_id TEXT,
  source_author_id TEXT,
  source_timestamp TIMESTAMPTZ,
  source_outcome TEXT CHECK (source_outcome IN ('passed','failed','unknown')),
  source_verifier_hash TEXT,
  -- neutral/governance content
  symptom_signature TEXT,
  root_cause TEXT,
  fault_localization TEXT,
  affected_symbols JSONB NOT NULL DEFAULT '[]'::jsonb,
  affected_apis JSONB NOT NULL DEFAULT '[]'::jsonb,
  repository_convention TEXT,
  preconditions TEXT,
  non_applicability TEXT,
  -- execution view
  repair_strategy TEXT,
  ordered_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
  patch_pattern TEXT,
  validation_strategy TEXT,
  common_failure TEXT,
  -- scope
  version_scope TEXT,
  path_scope TEXT,
  language TEXT,
  framework TEXT,
  -- evidence + governance
  evidence_hashes JSONB NOT NULL DEFAULT '[]'::jsonb,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  governance_state TEXT NOT NULL DEFAULT 'candidate'
    CHECK (governance_state IN ('candidate','probation','promoted','deprecated','quarantined','deleted')),
  valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_until TIMESTAMPTZ,
  supersedes_version_id UUID,
  content_hash TEXT NOT NULL,
  request_id TEXT,
  actor_id_hash TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  UNIQUE (org_id, card_id, id),
  CONSTRAINT ecv_card_ten_fk FOREIGN KEY (org_id, card_id) REFERENCES experience_cards(org_id, id),
  -- supersession may only target another version OF THE SAME CARD in the same tenant
  CONSTRAINT ecv_supersede_same_card_fk FOREIGN KEY (org_id, card_id, supersedes_version_id)
    REFERENCES experience_card_versions(org_id, card_id, id),
  CONSTRAINT ecv_no_self_supersede CHECK (supersedes_version_id IS NULL OR supersedes_version_id <> id));
ALTER TABLE experience_card_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE experience_card_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON experience_card_versions USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
-- immutable: no UPDATE / DELETE grant
GRANT SELECT, INSERT ON experience_card_versions TO api_service, worker_service;

-- current-version pointer must reference a version OF THIS CARD (same org + card_id = card.id)
ALTER TABLE experience_cards ADD CONSTRAINT ec_current_same_card_fk
  FOREIGN KEY (org_id, id, current_version_id) REFERENCES experience_card_versions(org_id, card_id, id);

CREATE TABLE experience_sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  card_id UUID NOT NULL,
  bank TEXT NOT NULL CHECK (bank IN ('HISTORICAL_VERIFIED','USER_SUCCESS')),
  source_type TEXT NOT NULL,
  source_task_id TEXT,
  source_repository TEXT,
  source_commit TEXT,
  source_issue_id TEXT,
  source_author_id TEXT,
  source_job_id UUID,
  source_timestamp TIMESTAMPTZ,
  evidence_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  CONSTRAINT es_card_ten_fk FOREIGN KEY (org_id, card_id) REFERENCES experience_cards(org_id, id));
ALTER TABLE experience_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE experience_sources FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON experience_sources USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
GRANT SELECT, INSERT ON experience_sources TO api_service, worker_service;

CREATE TABLE experience_source_outcomes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  source_id UUID NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('passed','failed','unknown')),
  verifier_hash TEXT NOT NULL,
  evidence_hash TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  CONSTRAINT eso_src_ten_fk FOREIGN KEY (org_id, source_id) REFERENCES experience_sources(org_id, id));
ALTER TABLE experience_source_outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE experience_source_outcomes FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON experience_source_outcomes USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
GRANT SELECT, INSERT ON experience_source_outcomes TO api_service, worker_service;

-- ============================ agentic search/browse/decision ============================
CREATE TABLE memory_search_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  request_id TEXT NOT NULL,
  actor_id_hash TEXT NOT NULL,
  target_task_id TEXT,
  policy_version TEXT,
  policy_mode TEXT NOT NULL DEFAULT 'shadow'
    CHECK (policy_mode IN ('off','static_relevant','agentic_reference','utility_gated','shadow')),
  max_search_rounds INT NOT NULL DEFAULT 4,
  max_browse INT NOT NULL DEFAULT 4,
  max_injected_tokens INT NOT NULL DEFAULT 1200,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  UNIQUE (org_id, request_id));
ALTER TABLE memory_search_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_search_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON memory_search_sessions USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
GRANT SELECT, INSERT ON memory_search_sessions TO api_service, worker_service;

CREATE TABLE memory_search_queries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  session_id UUID NOT NULL,
  round_no INT NOT NULL DEFAULT 0,
  subtask TEXT CHECK (subtask IN ('comprehension','localization','modification','validation')),
  query_text_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  CONSTRAINT msq_sess_ten_fk FOREIGN KEY (org_id, session_id) REFERENCES memory_search_sessions(org_id, id));
ALTER TABLE memory_search_queries ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_search_queries FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON memory_search_queries USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
GRANT SELECT, INSERT ON memory_search_queries TO api_service, worker_service;

CREATE TABLE memory_candidates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  session_id UUID NOT NULL,
  query_id UUID NOT NULL,
  card_id UUID NOT NULL,
  version_id UUID NOT NULL,
  rank INT NOT NULL DEFAULT 0,
  similarity DOUBLE PRECISION,
  reason_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  CONSTRAINT mc_sess_ten_fk FOREIGN KEY (org_id, session_id) REFERENCES memory_search_sessions(org_id, id),
  CONSTRAINT mc_ver_ten_fk FOREIGN KEY (org_id, version_id) REFERENCES experience_card_versions(org_id, id));
ALTER TABLE memory_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_candidates FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON memory_candidates USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
GRANT SELECT, INSERT ON memory_candidates TO api_service, worker_service;

CREATE TABLE memory_browse_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  session_id UUID NOT NULL,
  candidate_id UUID NOT NULL,
  card_id UUID NOT NULL,
  version_id UUID NOT NULL,
  injected_tokens INT NOT NULL DEFAULT 0,
  injected_hash TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  CONSTRAINT mbe_cand_ten_fk FOREIGN KEY (org_id, candidate_id) REFERENCES memory_candidates(org_id, id));
ALTER TABLE memory_browse_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_browse_events FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON memory_browse_events USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
GRANT SELECT, INSERT ON memory_browse_events TO api_service, worker_service;

CREATE TABLE memory_policy_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  policy_name TEXT NOT NULL,
  version TEXT NOT NULL,
  weights JSONB NOT NULL DEFAULT '{}'::jsonb,
  reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
  coverage_floor DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  content_hash TEXT NOT NULL,
  frozen BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  UNIQUE (org_id, policy_name, version));
ALTER TABLE memory_policy_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_policy_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON memory_policy_versions USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
GRANT SELECT, INSERT ON memory_policy_versions TO api_service, worker_service;

CREATE TABLE memory_decisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  session_id UUID NOT NULL,
  candidate_id UUID NOT NULL,
  card_id UUID NOT NULL,
  version_id UUID NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('USE','ABSTAIN')),
  reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
  feature_values JSONB NOT NULL DEFAULT '{}'::jsonb,
  policy_version TEXT,
  score DOUBLE PRECISION,
  estimated_novelty DOUBLE PRECISION,
  estimated_applicability DOUBLE PRECISION,
  estimated_actionability DOUBLE PRECISION,
  estimated_risk DOUBLE PRECISION,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  CONSTRAINT md_cand_ten_fk FOREIGN KEY (org_id, candidate_id) REFERENCES memory_candidates(org_id, id));
ALTER TABLE memory_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_decisions FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON memory_decisions USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
GRANT SELECT, INSERT ON memory_decisions TO api_service, worker_service;

-- ============================ outcome credit + governance ============================
CREATE TABLE memory_outcome_credits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  target_task_id TEXT NOT NULL,
  session_id UUID,
  target_outcome TEXT CHECK (target_outcome IN ('resolved','unresolved','infra_failure','unknown')),
  outcome_class TEXT NOT NULL CHECK (outcome_class IN
    ('MEMORY_GAIN','MEMORY_LOSS','MEMORY_NEUTRAL','COMPUTE_ONLY_GAIN','UNATTRIBUTED','INFRA_FAILURE')),
  evidence_class TEXT NOT NULL CHECK (evidence_class IN
    ('EXACT_SOURCE_OPERATION_ADOPTION','PARTIAL_SOURCE_OPERATION_ADOPTION','SOURCE_API_ADOPTION',
     'SOURCE_CONTROL_FLOW_ADOPTION','UNRELATED_ERROR','NO_BEHAVIORAL_CHANGE','UNCLASSIFIED')),
  official_verifier_result BOOLEAN,
  cost JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, id));
ALTER TABLE memory_outcome_credits ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_outcome_credits FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON memory_outcome_credits USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
GRANT SELECT, INSERT ON memory_outcome_credits TO api_service, worker_service;

CREATE TABLE memory_counterfactual_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  target_task_id TEXT NOT NULL,
  memory_session_id UUID,
  no_memory_reference TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, id));
ALTER TABLE memory_counterfactual_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_counterfactual_links FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON memory_counterfactual_links USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
GRANT SELECT, INSERT ON memory_counterfactual_links TO api_service, worker_service;

CREATE TABLE memory_usage_aggregates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  card_id UUID NOT NULL,
  context_key TEXT NOT NULL,
  use_count INT NOT NULL DEFAULT 0,
  gain_count INT NOT NULL DEFAULT 0,
  loss_count INT NOT NULL DEFAULT 0,
  neutral_count INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  UNIQUE (org_id, card_id, context_key),
  CONSTRAINT mua_card_ten_fk FOREIGN KEY (org_id, card_id) REFERENCES experience_cards(org_id, id));
ALTER TABLE memory_usage_aggregates ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_usage_aggregates FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON memory_usage_aggregates USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
GRANT SELECT, INSERT, UPDATE ON memory_usage_aggregates TO api_service, worker_service;

-- searchability guard: only promoted/probation cards are ever candidate-eligible (app enforces; index supports it)
CREATE INDEX ix_ecv_searchable ON experience_card_versions (org_id, card_id)
  WHERE governance_state IN ('promoted','probation');
