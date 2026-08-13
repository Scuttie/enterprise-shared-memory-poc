-- P5.2 §2/§9/G7: per-job raw + applied patch, persisted durably for experiment jobs so negative-memory (S1/S4)
-- adoption can be classified programmatically from artifacts (not inferred from Pass@1). Runs after 0012.

CREATE TABLE job_patches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  job_id UUID NOT NULL REFERENCES solve_jobs(id),
  raw_patch TEXT, applied_patch TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, job_id));

ALTER TABLE job_patches ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_patches FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON job_patches USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
ALTER TABLE job_patches ADD CONSTRAINT jp_job_ten_fk FOREIGN KEY (org_id, job_id) REFERENCES solve_jobs(org_id, id);
GRANT SELECT, INSERT ON job_patches TO api_service, worker_service;
