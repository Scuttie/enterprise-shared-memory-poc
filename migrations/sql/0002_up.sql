-- P1.1 hardening. Runs after 0001. Adds missing tables, tenant-consistent composite FKs, real
-- immutability triggers, optimistic version, CHECK constraints, dedicated SECURITY DEFINER owner, and
-- minimum-privilege grants.

-- ------------------------------------------------------------------ missing tables
CREATE TABLE teams (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id), name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (org_id, name));
CREATE TABLE team_memberships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id), team_id UUID NOT NULL REFERENCES teams(id),
  user_id UUID NOT NULL REFERENCES users(id), role TEXT NOT NULL DEFAULT 'member',
  UNIQUE (org_id, team_id, user_id));
CREATE TABLE promotion_decisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id), candidate_id UUID, outcome TEXT NOT NULL,
  failed_gate TEXT, reason TEXT, evidence_hash TEXT, decided_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE replay_evidence (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id), contract_version_id UUID REFERENCES memory_contract_versions(id),
  replay_kind TEXT NOT NULL, success BOOLEAN NOT NULL, detail_json JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE artifacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id), job_id UUID REFERENCES solve_jobs(id),
  kind TEXT NOT NULL, object_key TEXT NOT NULL, content_hash TEXT, retention_class TEXT NOT NULL DEFAULT 'default',
  legal_hold BOOLEAN NOT NULL DEFAULT false, deletion_state TEXT NOT NULL DEFAULT 'ACTIVE',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());

DO $$
DECLARE t TEXT;
BEGIN
  FOR t IN SELECT unnest(ARRAY['teams','team_memberships','promotion_decisions','replay_evidence','artifacts'])
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format($f$CREATE POLICY org_isolation ON %I USING
      (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
      WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid)$f$, t);
    EXECUTE format('GRANT SELECT, INSERT ON %I TO api_service', t);
  END LOOP;
END $$;

-- ------------------------------------------------------------------ parent unique keys for composite FKs
ALTER TABLE users ADD CONSTRAINT users_org_id_uq UNIQUE (org_id, id);
ALTER TABLE repositories ADD CONSTRAINT repositories_org_id_uq UNIQUE (org_id, id);
ALTER TABLE task_execution_policies ADD CONSTRAINT tep_org_id_uq UNIQUE (org_id, id);
ALTER TABLE memory_contracts ADD CONSTRAINT mc_org_id_uq UNIQUE (org_id, id);
ALTER TABLE memory_contract_versions ADD CONSTRAINT mcv_org_id_uq UNIQUE (org_id, id);
ALTER TABLE private_episodes ADD CONSTRAINT pe_org_id_uq UNIQUE (org_id, id);
ALTER TABLE solve_jobs ADD CONSTRAINT sj_org_id_uq UNIQUE (org_id, id);
ALTER TABLE solve_attempts ADD CONSTRAINT sa_org_id_uq UNIQUE (org_id, id);

-- ------------------------------------------------------------------ tenant-consistent composite FKs
ALTER TABLE repository_permissions ADD CONSTRAINT rp_repo_ten_fk FOREIGN KEY (org_id, repository_id) REFERENCES repositories(org_id, id);
ALTER TABLE task_execution_policies ADD CONSTRAINT tep_repo_ten_fk FOREIGN KEY (org_id, repository_id) REFERENCES repositories(org_id, id);
ALTER TABLE private_episodes ADD CONSTRAINT pe_user_ten_fk FOREIGN KEY (org_id, owner_user_id) REFERENCES users(org_id, id);
ALTER TABLE private_episodes ADD CONSTRAINT pe_repo_ten_fk FOREIGN KEY (org_id, repository_id) REFERENCES repositories(org_id, id);
ALTER TABLE memory_contracts ADD CONSTRAINT mc_repo_ten_fk FOREIGN KEY (org_id, repository_id) REFERENCES repositories(org_id, id);
ALTER TABLE memory_contract_versions ADD CONSTRAINT mcv_contract_ten_fk FOREIGN KEY (org_id, contract_id) REFERENCES memory_contracts(org_id, id);
ALTER TABLE contract_sources ADD CONSTRAINT cs_version_ten_fk FOREIGN KEY (org_id, contract_version_id) REFERENCES memory_contract_versions(org_id, id);
ALTER TABLE contract_sources ADD CONSTRAINT cs_episode_ten_fk FOREIGN KEY (org_id, private_episode_id) REFERENCES private_episodes(org_id, id);
ALTER TABLE solve_jobs ADD CONSTRAINT sj_user_ten_fk FOREIGN KEY (org_id, submitter_user_id) REFERENCES users(org_id, id);
ALTER TABLE solve_jobs ADD CONSTRAINT sj_repo_ten_fk FOREIGN KEY (org_id, repository_id) REFERENCES repositories(org_id, id);
ALTER TABLE solve_jobs ADD CONSTRAINT sj_policy_ten_fk FOREIGN KEY (org_id, task_policy_id) REFERENCES task_execution_policies(org_id, id);
ALTER TABLE solve_attempts ADD CONSTRAINT sa_job_ten_fk FOREIGN KEY (org_id, job_id) REFERENCES solve_jobs(org_id, id);
ALTER TABLE retrieval_decisions ADD CONSTRAINT rd_job_ten_fk FOREIGN KEY (org_id, job_id) REFERENCES solve_jobs(org_id, id);
ALTER TABLE outcome_observations ADD CONSTRAINT oo_job_ten_fk FOREIGN KEY (org_id, job_id) REFERENCES solve_jobs(org_id, id);
ALTER TABLE outcome_observations ADD CONSTRAINT oo_attempt_ten_fk FOREIGN KEY (org_id, attempt_id) REFERENCES solve_attempts(org_id, id);

-- ------------------------------------------------------------------ real immutability (triggers, not just uniqueness)
CREATE OR REPLACE FUNCTION reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'row is immutable (%.% is append-only evidence)', TG_TABLE_SCHEMA, TG_TABLE_NAME; END $$;
CREATE TRIGGER mcv_immutable BEFORE UPDATE OR DELETE ON memory_contract_versions FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER oo_immutable BEFORE UPDATE OR DELETE ON outcome_observations FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER rd_immutable BEFORE UPDATE OR DELETE ON retrieval_decisions FOR EACH ROW EXECUTE FUNCTION reject_mutation();

-- ------------------------------------------------------------------ optimistic version + current-version integrity
ALTER TABLE memory_contracts ADD COLUMN optimistic_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE memory_contracts ADD CONSTRAINT mc_current_fk FOREIGN KEY (org_id, current_version_id) REFERENCES memory_contract_versions(org_id, id);
ALTER TABLE memory_contract_versions ADD CONSTRAINT mcv_no_self_supersede CHECK (supersedes_version_id IS DISTINCT FROM id);

-- ------------------------------------------------------------------ job CHECK constraints
ALTER TABLE solve_jobs ADD CONSTRAINT sj_state_chk CHECK (state IN
  ('QUEUED','RETRIEVING','GENERATING','TESTING','REPAIRING','SUCCEEDED','FAILED','CANCELLED','DEAD_LETTER'));
ALTER TABLE solve_jobs ADD CONSTRAINT sj_attempts_chk CHECK (attempts >= 0);
ALTER TABLE solve_jobs ADD CONSTRAINT sj_maxatt_chk CHECK (max_attempts >= 1);
ALTER TABLE outbox_events ADD CONSTRAINT ob_attempts_chk CHECK (attempts >= 0 AND max_attempts >= 1);

-- ------------------------------------------------------------------ SECURITY DEFINER hardening (§7)
GRANT SELECT, UPDATE ON solve_jobs TO job_dispatcher_owner;
GRANT INSERT ON solve_attempts TO job_dispatcher_owner;
ALTER FUNCTION claim_next_job(TEXT, INTEGER) OWNER TO job_dispatcher_owner;
REVOKE ALL ON FUNCTION claim_next_job(TEXT, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claim_next_job(TEXT, INTEGER) TO worker_service;
REVOKE ALL ON FUNCTION audit_no_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION reject_mutation() FROM PUBLIC;

-- ------------------------------------------------------------------ minimum-privilege grants (§11)
REVOKE ALL ON organisations FROM api_service;
GRANT SELECT ON organisations TO api_service;
REVOKE ALL ON memory_contract_versions FROM api_service;
GRANT SELECT, INSERT ON memory_contract_versions TO api_service;
REVOKE ALL ON outcome_observations, retrieval_decisions FROM api_service;
GRANT SELECT, INSERT ON outcome_observations, retrieval_decisions TO api_service;
REVOKE DELETE ON outbox_events FROM api_service;
