-- P5 §6: solve-job identity/policy/ref snapshot + job events + model calls + retrieval evidence. Runs
-- after 0007. The frozen SQL bodies of 0001-0007 are untouched.

ALTER TABLE solve_jobs ADD COLUMN installation_id BIGINT;
ALTER TABLE solve_jobs ADD COLUMN requested_ref TEXT;
ALTER TABLE solve_jobs ADD COLUMN resolved_commit_sha TEXT;
ALTER TABLE solve_jobs ADD COLUMN resolved_tree_sha TEXT;
ALTER TABLE solve_jobs ADD COLUMN task_policy_version INTEGER;
ALTER TABLE solve_jobs ADD COLUMN instruction_hash TEXT;
ALTER TABLE solve_jobs ADD COLUMN identity_snapshot JSONB NOT NULL DEFAULT '{}';
ALTER TABLE solve_jobs ADD COLUMN backend_type TEXT;
ALTER TABLE solve_jobs ADD COLUMN cross_user_private_injection_count INTEGER;

CREATE TABLE job_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  job_id UUID NOT NULL REFERENCES solve_jobs(id),
  seq INTEGER NOT NULL, state TEXT, event_type TEXT NOT NULL,
  detail_json JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (job_id, seq));

CREATE TABLE model_calls (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  job_id UUID NOT NULL REFERENCES solve_jobs(id),
  logical_request_id TEXT NOT NULL, backend_type TEXT NOT NULL,
  requested_model TEXT, returned_model TEXT, attempts INTEGER NOT NULL DEFAULT 0,
  input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, total_latency DOUBLE PRECISION,
  final_status TEXT NOT NULL, redaction_status TEXT, detail_json JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE retrieval_candidates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  job_id UUID NOT NULL REFERENCES solve_jobs(id),
  scope TEXT NOT NULL, canonical_id TEXT, canonical_version_id TEXT, content_hash TEXT,
  private_owner_id UUID, accepted BOOLEAN NOT NULL, rejection_reason TEXT,
  injected BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now());

-- RLS
DO $$ DECLARE t TEXT; BEGIN
  FOR t IN SELECT unnest(ARRAY['job_events','model_calls','retrieval_candidates']) LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format($f$CREATE POLICY org_isolation ON %I USING
      (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
      WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid)$f$, t);
  END LOOP;
END $$;

-- tenant-consistent composite FKs (org_id, job_id) -> solve_jobs(org_id, id)
ALTER TABLE job_events ADD CONSTRAINT je_job_ten_fk FOREIGN KEY (org_id, job_id) REFERENCES solve_jobs(org_id, id);
ALTER TABLE model_calls ADD CONSTRAINT mc_job_ten_fk FOREIGN KEY (org_id, job_id) REFERENCES solve_jobs(org_id, id);
ALTER TABLE retrieval_candidates ADD CONSTRAINT rc_job_ten_fk FOREIGN KEY (org_id, job_id) REFERENCES solve_jobs(org_id, id);

-- grants
GRANT SELECT, INSERT ON job_events, model_calls, retrieval_candidates TO api_service, worker_service;
GRANT INSERT ON private_episodes TO worker_service;
GRANT SELECT, INSERT, UPDATE ON artifacts TO worker_service;
GRANT SELECT ON repository_permissions, team_memberships, repositories TO worker_service;
