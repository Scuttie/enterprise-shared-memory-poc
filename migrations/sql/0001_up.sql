-- P1 initial production schema. Run by the migration owner AFTER roles are bootstrapped.
-- Tenant isolation is enforced by FORCE ROW LEVEL SECURITY + transaction-local app.org_id/app.user_id.
-- gen_random_uuid() is built-in on PostgreSQL 13+.

-- ------------------------------------------------------------------ identity / repos
CREATE TABLE organisations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  external_key TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  external_subject TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, external_subject)
);
CREATE TABLE repositories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  external_repo_id TEXT NOT NULL,
  provider TEXT NOT NULL DEFAULT 'github',
  default_branch TEXT NOT NULL DEFAULT 'main',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, external_repo_id)
);
CREATE TABLE repository_permissions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  repository_id UUID NOT NULL REFERENCES repositories(id),
  subject_type TEXT NOT NULL, subject_id UUID NOT NULL,
  can_read BOOLEAN NOT NULL DEFAULT true, can_modify BOOLEAN NOT NULL DEFAULT false,
  path_globs TEXT[] NOT NULL DEFAULT '{}', branch_globs TEXT[] NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE task_execution_policies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  repository_id UUID NOT NULL REFERENCES repositories(id),
  task_key TEXT NOT NULL,
  editable_paths TEXT[] NOT NULL, target_symbol TEXT NOT NULL, exact_signature TEXT NOT NULL,
  test_bundle_ref TEXT NOT NULL, maximum_changed_lines INTEGER NOT NULL DEFAULT 12,
  timeout_seconds INTEGER NOT NULL DEFAULT 20, language TEXT NOT NULL DEFAULT 'python',
  allowed_refs TEXT[] NOT NULL DEFAULT '{main}', version INTEGER NOT NULL DEFAULT 1,
  active BOOLEAN NOT NULL DEFAULT true,
  UNIQUE (org_id, repository_id, task_key)
);

-- ------------------------------------------------------------------ memory objects
CREATE TABLE private_episodes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  owner_user_id UUID NOT NULL REFERENCES users(id),
  repository_id UUID REFERENCES repositories(id),
  task_id TEXT, source_commit TEXT,
  canonical_json JSONB NOT NULL, content_hash TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'success', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE memory_contracts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  repository_id UUID REFERENCES repositories(id),
  current_version_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE memory_contract_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contract_id UUID NOT NULL REFERENCES memory_contracts(id),
  org_id UUID NOT NULL REFERENCES organisations(id),
  version_number INTEGER NOT NULL,
  canonical_json JSONB NOT NULL, content_hash TEXT NOT NULL,
  governance_state TEXT NOT NULL DEFAULT 'promoted',
  valid_from TIMESTAMPTZ, valid_until TIMESTAMPTZ,
  supersedes_version_id UUID REFERENCES memory_contract_versions(id),
  created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  optimistic_version INTEGER NOT NULL DEFAULT 1,
  UNIQUE (contract_id, version_number), UNIQUE (contract_id, content_hash)
);
CREATE TABLE contract_sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  contract_version_id UUID NOT NULL REFERENCES memory_contract_versions(id),
  private_episode_id UUID REFERENCES private_episodes(id),
  evidence_type TEXT, evidence_hash TEXT
);

-- ------------------------------------------------------------------ solve / outcome
CREATE TABLE solve_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  submitter_user_id UUID NOT NULL REFERENCES users(id),
  repository_id UUID NOT NULL REFERENCES repositories(id),
  task_policy_id UUID REFERENCES task_execution_policies(id),
  logical_request_id TEXT NOT NULL, idempotency_key TEXT,
  state TEXT NOT NULL DEFAULT 'QUEUED', spec_json JSONB NOT NULL DEFAULT '{}',
  attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
  lease_owner TEXT, lease_expires_at TIMESTAMPTZ, heartbeat_at TIMESTAMPTZ,
  next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(), cancel_requested_at TIMESTAMPTZ,
  error_class TEXT, error_detail_sanitized TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, idempotency_key)
);
CREATE TABLE solve_attempts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  job_id UUID NOT NULL REFERENCES solve_jobs(id),
  attempt_number INTEGER NOT NULL, worker_id TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'RETRIEVING',
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ, detail_json JSONB NOT NULL DEFAULT '{}',
  UNIQUE (job_id, attempt_number)
);
CREATE TABLE retrieval_decisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  job_id UUID NOT NULL REFERENCES solve_jobs(id),
  canonical_json JSONB NOT NULL, content_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE outcome_observations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  job_id UUID NOT NULL REFERENCES solve_jobs(id),
  attempt_id UUID REFERENCES solve_attempts(id),
  pass1 INTEGER, exec1 INTEGER, pass2 INTEGER,
  injected_memories JSONB NOT NULL DEFAULT '[]', usage_json JSONB NOT NULL DEFAULT '{}',
  latency_json JSONB NOT NULL DEFAULT '{}', parser_status TEXT, content_hash TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------ audit / outbox / deletion / idempotency
CREATE TABLE audit_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  actor_user_id UUID, request_id TEXT, event_type TEXT NOT NULL,
  subject_type TEXT, subject_id TEXT, detail_json JSONB NOT NULL DEFAULT '{}',
  previous_hash TEXT, event_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE outbox_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  event_type TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id UUID NOT NULL,
  aggregate_version INTEGER NOT NULL, payload_json JSONB NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 5,
  next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(), lease_owner TEXT, lease_expires_at TIMESTAMPTZ,
  error_detail_sanitized TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), processed_at TIMESTAMPTZ,
  UNIQUE (event_type, aggregate_type, aggregate_id, aggregate_version)
);
CREATE TABLE deletion_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  object_type TEXT NOT NULL, object_id UUID NOT NULL, state TEXT NOT NULL DEFAULT 'REQUESTED',
  requested_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE idempotency_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  operation TEXT NOT NULL, key TEXT NOT NULL,
  result_object_type TEXT, result_object_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, operation, key)
);

-- ------------------------------------------------------------------ RLS: enable + FORCE + policies
DO $$
DECLARE t TEXT;
BEGIN
  FOR t IN SELECT unnest(ARRAY['organisations','users','repositories','repository_permissions',
      'task_execution_policies','private_episodes','memory_contracts','memory_contract_versions',
      'contract_sources','solve_jobs','solve_attempts','retrieval_decisions','outcome_observations',
      'audit_events','outbox_events','deletion_requests','idempotency_keys'])
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
  END LOOP;
END $$;

-- organisation-scoped tables: org_id must equal the transaction-local app.org_id
DO $$
DECLARE t TEXT;
BEGIN
  FOR t IN SELECT unnest(ARRAY['users','repositories','repository_permissions','task_execution_policies',
      'private_episodes','memory_contracts','memory_contract_versions','contract_sources','solve_jobs',
      'solve_attempts','retrieval_decisions','outcome_observations','audit_events','outbox_events',
      'deletion_requests','idempotency_keys'])
  LOOP
    EXECUTE format($f$CREATE POLICY org_isolation ON %I USING
      (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
      WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid)$f$, t);
  END LOOP;
END $$;
-- organisations table: id must equal app.org_id
CREATE POLICY org_self ON organisations USING (id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (id = nullif(current_setting('app.org_id', true), '')::uuid);
-- private episodes: additionally require the owner to be the transaction-local user
CREATE POLICY private_owner ON private_episodes AS RESTRICTIVE USING
  (owner_user_id = nullif(current_setting('app.user_id', true), '')::uuid);

-- ------------------------------------------------------------------ audit append-only trigger
CREATE OR REPLACE FUNCTION audit_no_mutation() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'audit_events is append-only'; END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION audit_no_mutation();

-- ------------------------------------------------------------------ SECURITY DEFINER job claim (§12)
CREATE OR REPLACE FUNCTION claim_next_job(p_worker TEXT, p_lease_seconds INTEGER)
RETURNS TABLE (job_id UUID, org_id UUID, task_policy_id UUID, spec_json JSONB, attempt_number INTEGER)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE v_job solve_jobs%ROWTYPE;
BEGIN
  SELECT * INTO v_job FROM solve_jobs j
   WHERE (j.state = 'QUEUED' AND j.next_attempt_at <= now())
      OR (j.lease_expires_at IS NOT NULL AND j.lease_expires_at < now()
          AND j.state NOT IN ('SUCCEEDED','FAILED','CANCELLED','DEAD_LETTER'))
   ORDER BY j.next_attempt_at
   FOR UPDATE SKIP LOCKED LIMIT 1;
  IF NOT FOUND THEN RETURN; END IF;
  UPDATE solve_jobs SET attempts = attempts + 1, lease_owner = p_worker,
         lease_expires_at = now() + make_interval(secs => p_lease_seconds),
         heartbeat_at = now(), state = 'RETRIEVING', updated_at = now()
   WHERE id = v_job.id;
  INSERT INTO solve_attempts (org_id, job_id, attempt_number, worker_id)
   VALUES (v_job.org_id, v_job.id, v_job.attempts + 1, p_worker);
  RETURN QUERY SELECT v_job.id, v_job.org_id, v_job.task_policy_id, v_job.spec_json, v_job.attempts + 1;
END $$;

-- ------------------------------------------------------------------ grants (roles bootstrapped earlier)
-- api_service + worker_service: NOBYPASSRLS, non-owner; RLS is the isolation boundary.
GRANT USAGE ON SCHEMA public TO api_service, worker_service, audit_reader;
DO $$
DECLARE t TEXT;
BEGIN
  FOR t IN SELECT unnest(ARRAY['organisations','users','repositories','repository_permissions',
      'task_execution_policies','private_episodes','memory_contracts','memory_contract_versions',
      'contract_sources','solve_jobs','solve_attempts','retrieval_decisions','outcome_observations',
      'outbox_events','deletion_requests','idempotency_keys'])
  LOOP
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO api_service', t);
  END LOOP;
END $$;
-- audit_events: append-only for api/worker (INSERT + SELECT, no UPDATE/DELETE); read-only for audit_reader
GRANT SELECT, INSERT ON audit_events TO api_service, worker_service;
GRANT SELECT ON audit_events TO audit_reader;
-- worker: constrained set (jobs/attempts/outcomes/outbox + claim function); RLS still applies
GRANT SELECT, UPDATE ON solve_jobs, solve_attempts TO worker_service;
GRANT SELECT, INSERT ON outcome_observations, retrieval_decisions, outbox_events TO worker_service;
GRANT SELECT ON task_execution_policies, memory_contracts, memory_contract_versions, private_episodes TO worker_service;
GRANT EXECUTE ON FUNCTION claim_next_job(TEXT, INTEGER) TO worker_service;
