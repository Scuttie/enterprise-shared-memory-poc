-- P2-0 canonical-integrity + dispatcher/outbox hardening. Runs after 0002. Frozen SQL body of 0001/0002
-- is untouched.

-- ------------------------------------------------------------------ same-contract current version (§3)
ALTER TABLE memory_contract_versions ADD CONSTRAINT mcv_org_contract_id_uq UNIQUE (org_id, contract_id, id);
ALTER TABLE memory_contracts DROP CONSTRAINT mc_current_fk;
-- memory_contracts.id IS the contract_id; the current version must belong to THIS contract (and org)
ALTER TABLE memory_contracts ADD CONSTRAINT mc_current_same_contract_fk
  FOREIGN KEY (org_id, id, current_version_id)
  REFERENCES memory_contract_versions(org_id, contract_id, id);

-- ------------------------------------------------------------------ supersession integrity (§4)
ALTER TABLE memory_contract_versions ADD CONSTRAINT mcv_supersede_same_contract_fk
  FOREIGN KEY (org_id, contract_id, supersedes_version_id)
  REFERENCES memory_contract_versions(org_id, contract_id, id);

-- recursive cycle validation on insert (defense in depth; immutability + insert ordering already make
-- multi-node cycles unconstructable, since a version cannot reference one that does not yet exist).
CREATE OR REPLACE FUNCTION mcv_no_cycle() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE cur UUID; depth INT := 0;
BEGIN
  cur := NEW.supersedes_version_id;
  WHILE cur IS NOT NULL LOOP
    IF cur = NEW.id THEN RAISE EXCEPTION 'supersession cycle detected at %', NEW.id; END IF;
    depth := depth + 1;
    IF depth > 10000 THEN RAISE EXCEPTION 'supersession chain too deep'; END IF;
    SELECT supersedes_version_id INTO cur FROM public.memory_contract_versions WHERE id = cur;
  END LOOP;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION mcv_no_cycle() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER mcv_cycle_check AFTER INSERT ON memory_contract_versions
  FOR EACH ROW EXECUTE FUNCTION mcv_no_cycle();

-- ------------------------------------------------------------------ tenant-consistent references for P1.1 tables (§5)
ALTER TABLE teams ADD CONSTRAINT teams_org_id_uq UNIQUE (org_id, id);
ALTER TABLE team_memberships ADD CONSTRAINT tm_team_ten_fk FOREIGN KEY (org_id, team_id) REFERENCES teams(org_id, id);
ALTER TABLE team_memberships ADD CONSTRAINT tm_user_ten_fk FOREIGN KEY (org_id, user_id) REFERENCES users(org_id, id);
ALTER TABLE replay_evidence ADD CONSTRAINT re_version_ten_fk FOREIGN KEY (org_id, contract_version_id) REFERENCES memory_contract_versions(org_id, id);
ALTER TABLE artifacts ADD CONSTRAINT art_job_ten_fk FOREIGN KEY (org_id, job_id) REFERENCES solve_jobs(org_id, id);
ALTER TABLE promotion_decisions ADD CONSTRAINT pd_reviewer_ten_fk FOREIGN KEY (org_id, decided_by) REFERENCES users(org_id, id);
-- audited actor references (nullable -> NULL allowed; when present must be a same-org user)
ALTER TABLE memory_contract_versions ADD CONSTRAINT mcv_creator_ten_fk FOREIGN KEY (org_id, created_by) REFERENCES users(org_id, id);
ALTER TABLE audit_events ADD CONSTRAINT ae_actor_ten_fk FOREIGN KEY (org_id, actor_user_id) REFERENCES users(org_id, id);
ALTER TABLE deletion_requests ADD CONSTRAINT dr_requester_ten_fk FOREIGN KEY (org_id, requested_by) REFERENCES users(org_id, id);

-- ------------------------------------------------------------------ hardened SECURITY DEFINER claim (§6)
DROP FUNCTION IF EXISTS claim_next_job(TEXT, INTEGER);
CREATE FUNCTION claim_next_job(p_worker TEXT, p_lease_seconds INTEGER)
RETURNS TABLE (job_id UUID, org_id UUID, submitter_user_id UUID, task_policy_id UUID, spec_json JSONB, attempt_number INTEGER)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE v public.solve_jobs%ROWTYPE;
BEGIN
  IF p_worker IS NULL OR length(p_worker) = 0 THEN RAISE EXCEPTION 'empty worker id'; END IF;
  IF p_lease_seconds < 1 OR p_lease_seconds > 3600 THEN RAISE EXCEPTION 'lease seconds out of bounds'; END IF;
  -- expired jobs whose attempt budget is exhausted become DEAD_LETTER (never reclaimed indefinitely)
  UPDATE public.solve_jobs SET state='DEAD_LETTER', lease_owner=NULL, lease_expires_at=NULL, updated_at=now()
   WHERE lease_expires_at IS NOT NULL AND lease_expires_at < now() AND attempts >= max_attempts
     AND state NOT IN ('SUCCEEDED','FAILED','CANCELLED','DEAD_LETTER');
  SELECT * INTO v FROM public.solve_jobs j
   WHERE ((j.state='QUEUED' AND j.next_attempt_at<=now())
          OR (j.lease_expires_at IS NOT NULL AND j.lease_expires_at<now()
              AND j.state NOT IN ('SUCCEEDED','FAILED','CANCELLED','DEAD_LETTER')))
     AND j.attempts < j.max_attempts AND j.cancel_requested_at IS NULL
   ORDER BY j.next_attempt_at FOR UPDATE SKIP LOCKED LIMIT 1;
  IF NOT FOUND THEN RETURN; END IF;
  UPDATE public.solve_jobs SET attempts=attempts+1, lease_owner=p_worker,
         lease_expires_at=now()+make_interval(secs=>p_lease_seconds), heartbeat_at=now(),
         state='RETRIEVING', updated_at=now() WHERE id=v.id;
  INSERT INTO public.solve_attempts(org_id, job_id, attempt_number, worker_id)
   VALUES(v.org_id, v.id, v.attempts+1, p_worker);
  RETURN QUERY SELECT v.id, v.org_id, v.submitter_user_id, v.task_policy_id, v.spec_json, v.attempts+1;
END $$;
ALTER FUNCTION claim_next_job(TEXT, INTEGER) OWNER TO job_dispatcher_owner;
REVOKE ALL ON FUNCTION claim_next_job(TEXT, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claim_next_job(TEXT, INTEGER) TO worker_service;
