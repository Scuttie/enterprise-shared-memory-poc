-- P5.1 §8: server-assigned experiment arm + retrieval policy. The arm is chosen from a frozen manifest and
-- stored on the server-owned task policy; the client request never carries an arm. The retrieval policy
-- (scopes / max injected / oracle) drives the worker; the backend never receives a human-readable arm label.
-- Runs after 0011.

ALTER TABLE task_execution_policies ADD COLUMN retrieval_policy JSONB;
ALTER TABLE task_execution_policies ADD COLUMN experiment_id TEXT;
ALTER TABLE task_execution_policies ADD COLUMN experiment_arm TEXT;

ALTER TABLE solve_jobs ADD COLUMN experiment_id TEXT;
ALTER TABLE solve_jobs ADD COLUMN experiment_arm TEXT;
