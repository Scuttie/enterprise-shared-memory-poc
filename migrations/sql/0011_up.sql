-- P5.1 §5: expand the server-owned task policy so a non-toy, frozen coding task is fully described server-side
-- (the client may still specify only task_id + desired ref). All edit/test information stays server-owned; the
-- hidden test is referenced by manifest id, never inlined into anything the backend sees. Runs after 0010.

ALTER TABLE task_execution_policies ADD COLUMN family_id TEXT;
ALTER TABLE task_execution_policies ADD COLUMN domain TEXT;
ALTER TABLE task_execution_policies ADD COLUMN repository_fixture_id TEXT;
ALTER TABLE task_execution_policies ADD COLUMN target_path TEXT;
ALTER TABLE task_execution_policies ADD COLUMN public_test_entry TEXT;
ALTER TABLE task_execution_policies ADD COLUMN hidden_test_manifest_id TEXT;
ALTER TABLE task_execution_policies ADD COLUMN runtime TEXT;
ALTER TABLE task_execution_policies ADD COLUMN timeout_seconds INTEGER;
ALTER TABLE task_execution_policies ADD COLUMN allowed_import_changes JSONB NOT NULL DEFAULT '[]';
ALTER TABLE task_execution_policies ADD COLUMN allowed_new_files JSONB NOT NULL DEFAULT '[]';
ALTER TABLE task_execution_policies ADD COLUMN source_world_id TEXT;
ALTER TABLE task_execution_policies ADD COLUMN target_world_id TEXT;
ALTER TABLE task_execution_policies ADD COLUMN policy_version INTEGER;
