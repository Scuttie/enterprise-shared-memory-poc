-- P2-preflight: outbox lease tokens, minimal-search-path SECURITY DEFINER, dedicated index-worker
-- dispatch, and API outbox-mutation lockdown. Runs after 0003.

-- ------------------------------------------------------------------ §2.4 lease token
ALTER TABLE outbox_events ADD COLUMN lease_token UUID;

-- ------------------------------------------------------------------ §2.3 API cannot mutate outbox processing state
REVOKE UPDATE ON outbox_events FROM api_service;   -- api may INSERT (publish) + SELECT only

-- index roles: minimal privileges; processing happens only through the dispatcher functions below
GRANT USAGE ON SCHEMA public TO index_worker_service, index_dispatcher_owner;
GRANT SELECT ON outbox_events, memory_contracts, memory_contract_versions, private_episodes, repositories TO index_worker_service;
GRANT SELECT, UPDATE ON outbox_events TO index_dispatcher_owner;

-- ------------------------------------------------------------------ §2.2 minimal-search-path hardened claim_next_job
DROP FUNCTION IF EXISTS claim_next_job(TEXT, INTEGER);
CREATE FUNCTION claim_next_job(p_worker TEXT, p_lease_seconds INTEGER)
RETURNS TABLE (job_id UUID, org_id UUID, submitter_user_id UUID, task_policy_id UUID, spec_json JSONB, attempt_number INTEGER)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE v public.solve_jobs%ROWTYPE;
BEGIN
  IF p_worker IS NULL OR length(p_worker) = 0 THEN RAISE EXCEPTION 'empty worker id'; END IF;
  IF p_lease_seconds < 1 OR p_lease_seconds > 3600 THEN RAISE EXCEPTION 'lease seconds out of bounds'; END IF;
  UPDATE public.solve_jobs SET state='DEAD_LETTER', lease_owner=NULL, lease_expires_at=NULL, updated_at=now()
   WHERE lease_expires_at IS NOT NULL AND lease_expires_at < now() AND attempts >= max_attempts
     AND state <> ALL(ARRAY['SUCCEEDED','FAILED','CANCELLED','DEAD_LETTER']);
  SELECT * INTO v FROM public.solve_jobs j
   WHERE ((j.state='QUEUED' AND j.next_attempt_at<=now())
          OR (j.lease_expires_at IS NOT NULL AND j.lease_expires_at<now()
              AND j.state <> ALL(ARRAY['SUCCEEDED','FAILED','CANCELLED','DEAD_LETTER'])))
     AND j.attempts < j.max_attempts AND j.cancel_requested_at IS NULL
   ORDER BY j.next_attempt_at FOR UPDATE SKIP LOCKED LIMIT 1;
  IF NOT FOUND THEN RETURN; END IF;
  UPDATE public.solve_jobs SET attempts=attempts+1, lease_owner=p_worker,
         lease_expires_at=now()+make_interval(secs=>p_lease_seconds), heartbeat_at=now(),
         state='RETRIEVING', updated_at=now() WHERE id=v.id;
  INSERT INTO public.solve_attempts(org_id, job_id, attempt_number, worker_id) VALUES(v.org_id, v.id, v.attempts+1, p_worker);
  RETURN QUERY SELECT v.id, v.org_id, v.submitter_user_id, v.task_policy_id, v.spec_json, v.attempts+1;
END $$;
ALTER FUNCTION claim_next_job(TEXT, INTEGER) OWNER TO job_dispatcher_owner;
REVOKE ALL ON FUNCTION claim_next_job(TEXT, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claim_next_job(TEXT, INTEGER) TO worker_service;

-- ------------------------------------------------------------------ cross-tenant outbox dispatch (index worker)
CREATE FUNCTION claim_next_outbox_event(p_worker TEXT, p_lease_seconds INTEGER)
RETURNS TABLE (event_id UUID, org_id UUID, event_type TEXT, aggregate_type TEXT, aggregate_id UUID,
               aggregate_version INTEGER, lease_token UUID, lease_expires_at TIMESTAMPTZ)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE v public.outbox_events%ROWTYPE; tok UUID; exp TIMESTAMPTZ;
BEGIN
  IF p_worker IS NULL OR length(p_worker) = 0 THEN RAISE EXCEPTION 'empty worker id'; END IF;
  IF p_lease_seconds < 1 OR p_lease_seconds > 3600 THEN RAISE EXCEPTION 'lease seconds out of bounds'; END IF;
  SELECT * INTO v FROM public.outbox_events e
   WHERE e.status IN ('PENDING','PROCESSING') AND (e.lease_expires_at IS NULL OR e.lease_expires_at < now())
     AND e.next_attempt_at <= now()
   ORDER BY e.created_at FOR UPDATE SKIP LOCKED LIMIT 1;
  IF NOT FOUND THEN RETURN; END IF;
  tok := gen_random_uuid(); exp := now() + make_interval(secs=>p_lease_seconds);
  UPDATE public.outbox_events SET status='PROCESSING', lease_owner=p_worker, lease_token=tok,
         lease_expires_at=exp, attempts=attempts+1 WHERE id=v.id;
  RETURN QUERY SELECT v.id, v.org_id, v.event_type, v.aggregate_type, v.aggregate_id, v.aggregate_version, tok, exp;
END $$;
ALTER FUNCTION claim_next_outbox_event(TEXT, INTEGER) OWNER TO index_dispatcher_owner;
REVOKE ALL ON FUNCTION claim_next_outbox_event(TEXT, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claim_next_outbox_event(TEXT, INTEGER) TO index_worker_service;

CREATE FUNCTION complete_outbox_event(p_event UUID, p_worker TEXT, p_token UUID)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE n INT;
BEGIN
  UPDATE public.outbox_events SET status='PROCESSED', processed_at=now(),
         lease_owner=NULL, lease_token=NULL, lease_expires_at=NULL
   WHERE id=p_event AND status='PROCESSING' AND lease_owner=p_worker AND lease_token=p_token AND lease_expires_at > now();
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'invalid or expired lease'; END IF;
  RETURN true;
END $$;
ALTER FUNCTION complete_outbox_event(UUID, TEXT, UUID) OWNER TO index_dispatcher_owner;
REVOKE ALL ON FUNCTION complete_outbox_event(UUID, TEXT, UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION complete_outbox_event(UUID, TEXT, UUID) TO index_worker_service;

CREATE FUNCTION retry_outbox_event(p_event UUID, p_worker TEXT, p_token UUID, p_error TEXT, p_backoff INTEGER)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE v public.outbox_events%ROWTYPE;
BEGIN
  SELECT * INTO v FROM public.outbox_events WHERE id=p_event FOR UPDATE;
  IF NOT FOUND OR v.status <> 'PROCESSING' OR v.lease_owner <> p_worker OR v.lease_token <> p_token OR v.lease_expires_at <= now() THEN
    RAISE EXCEPTION 'invalid or expired lease'; END IF;
  IF v.attempts >= v.max_attempts THEN
    UPDATE public.outbox_events SET status='QUARANTINED', lease_owner=NULL, lease_token=NULL, lease_expires_at=NULL,
           error_detail_sanitized=p_error WHERE id=p_event;
    RETURN 'QUARANTINED';
  END IF;
  UPDATE public.outbox_events SET status='PENDING', lease_owner=NULL, lease_token=NULL, lease_expires_at=NULL,
         next_attempt_at=now()+make_interval(secs=>p_backoff), error_detail_sanitized=p_error WHERE id=p_event;
  RETURN 'PENDING';
END $$;
ALTER FUNCTION retry_outbox_event(UUID, TEXT, UUID, TEXT, INTEGER) OWNER TO index_dispatcher_owner;
REVOKE ALL ON FUNCTION retry_outbox_event(UUID, TEXT, UUID, TEXT, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retry_outbox_event(UUID, TEXT, UUID, TEXT, INTEGER) TO index_worker_service;
