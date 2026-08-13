-- P4 §8: production artifact record + durable object-store lifecycle state machine. Runs after 0006. The
-- frozen SQL bodies of 0001-0006 are untouched.

ALTER TABLE artifacts ADD COLUMN byte_size BIGINT;
ALTER TABLE artifacts ADD COLUMN content_type TEXT;
ALTER TABLE artifacts ADD COLUMN artifact_class TEXT;
ALTER TABLE artifacts ADD COLUMN retain_until TIMESTAMPTZ;
ALTER TABLE artifacts ADD COLUMN encryption_mode TEXT NOT NULL DEFAULT 'sse-s3';
ALTER TABLE artifacts ADD COLUMN created_by UUID;
ALTER TABLE artifacts ADD COLUMN logical_deletion_at TIMESTAMPTZ;
ALTER TABLE artifacts ADD COLUMN physical_deletion_at TIMESTAMPTZ;
ALTER TABLE artifacts ADD COLUMN metadata_json JSONB NOT NULL DEFAULT '{}';
ALTER TABLE artifacts ADD COLUMN optimistic_version INTEGER NOT NULL DEFAULT 1;

-- content-addressed key is unique per tenant (idempotent upload; never overwrite a key with new content)
ALTER TABLE artifacts ADD CONSTRAINT artifacts_org_key_uq UNIQUE (org_id, object_key);

-- durable lifecycle state machine (the object store write and the DB row are not one distributed txn)
ALTER TABLE artifacts ALTER COLUMN deletion_state SET DEFAULT 'PENDING_UPLOAD';
ALTER TABLE artifacts ADD CONSTRAINT artifacts_state_chk CHECK (deletion_state IN
  ('PENDING_UPLOAD','AVAILABLE','UPLOAD_FAILED','DELETE_REQUESTED','LOGICALLY_DELETED',
   'PHYSICAL_DELETE_PENDING','PHYSICALLY_CONFIRMED','DELETE_FAILED','ACTIVE'));
ALTER TABLE artifacts ADD CONSTRAINT artifacts_class_chk CHECK (artifact_class IS NULL OR artifact_class IN
  ('repository_snapshot','sanitized_model_request','sanitized_model_response','parsed_patch','applied_patch',
   'public_test_output','sandbox_result','promotion_evidence','audit_export'));

-- api_service already has SELECT,INSERT on artifacts (0002); the lifecycle transitions need UPDATE too.
GRANT UPDATE ON artifacts TO api_service;
