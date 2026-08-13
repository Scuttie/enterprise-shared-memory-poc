-- P5.1 §4.3: idempotent terminal evidence. Exactly one terminal OutcomeObservation per job, so a reclaimed
-- attempt or a retry can never write a duplicate terminal outcome. (private_episodes idempotency is provided
-- by a deterministic per-job episode id + ON CONFLICT DO NOTHING; the candidate outbox event is idempotent by
-- its existing (event_type,aggregate_type,aggregate_id,aggregate_version) unique key.) Runs after 0009.

ALTER TABLE outcome_observations ADD CONSTRAINT oo_job_uniq UNIQUE (org_id, job_id);
