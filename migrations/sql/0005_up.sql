-- P2-start: residual job/outbox lease invariants. Runs after 0004.

-- ------------------------------------------------------------------ §2.5 lease-state consistency constraint
ALTER TABLE outbox_events ADD CONSTRAINT outbox_lease_state_chk CHECK (
  (status = 'PROCESSING' AND lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
  OR (status IN ('PENDING','PROCESSED','QUARANTINED') AND lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)
);

-- ------------------------------------------------------------------ §2.2 claim: skip exhausted; quarantine exhausted-expired
DROP FUNCTION IF EXISTS claim_next_outbox_event(TEXT, INTEGER);
CREATE FUNCTION claim_next_outbox_event(p_worker TEXT, p_lease_seconds INTEGER)
RETURNS TABLE (event_id UUID, org_id UUID, event_type TEXT, aggregate_type TEXT, aggregate_id UUID,
               aggregate_version INTEGER, lease_token UUID, lease_expires_at TIMESTAMPTZ)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE v public.outbox_events%ROWTYPE; tok UUID; exp TIMESTAMPTZ;
BEGIN
  IF p_worker IS NULL OR length(p_worker) = 0 THEN RAISE EXCEPTION 'empty worker id'; END IF;
  IF p_lease_seconds < 1 OR p_lease_seconds > 3600 THEN RAISE EXCEPTION 'lease seconds out of bounds'; END IF;
  -- exhausted expired PROCESSING events -> QUARANTINED (clear lease)
  UPDATE public.outbox_events SET status='QUARANTINED', lease_owner=NULL, lease_token=NULL, lease_expires_at=NULL
   WHERE status='PROCESSING' AND lease_expires_at IS NOT NULL AND lease_expires_at < now() AND attempts >= max_attempts;
  SELECT * INTO v FROM public.outbox_events e
   WHERE e.status IN ('PENDING','PROCESSING') AND (e.lease_expires_at IS NULL OR e.lease_expires_at < now())
     AND e.next_attempt_at <= now() AND e.attempts < e.max_attempts
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

-- ------------------------------------------------------------------ §2.3/§2.4 retry: backoff bounds + server-side sanitisation
DROP FUNCTION IF EXISTS retry_outbox_event(UUID, TEXT, UUID, TEXT, INTEGER);
CREATE FUNCTION retry_outbox_event(p_event UUID, p_worker TEXT, p_token UUID, p_error TEXT, p_backoff INTEGER)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE v public.outbox_events%ROWTYPE; safe TEXT;
BEGIN
  IF p_backoff < 0 OR p_backoff > 86400 THEN RAISE EXCEPTION 'backoff out of bounds'; END IF;
  safe := regexp_replace(substring(coalesce(p_error, '') FROM 1 FOR 200),
                         '(ghp_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+|AKIA[A-Z0-9]+|-----BEGIN[^-]*|[[:cntrl:]])',
                         '[REDACTED]', 'g');
  SELECT * INTO v FROM public.outbox_events WHERE id=p_event FOR UPDATE;
  IF NOT FOUND OR v.status <> 'PROCESSING' OR v.lease_owner <> p_worker OR v.lease_token <> p_token OR v.lease_expires_at <= now() THEN
    RAISE EXCEPTION 'invalid or expired lease'; END IF;
  IF v.attempts >= v.max_attempts THEN
    UPDATE public.outbox_events SET status='QUARANTINED', lease_owner=NULL, lease_token=NULL, lease_expires_at=NULL,
           error_detail_sanitized=safe WHERE id=p_event;
    RETURN 'QUARANTINED';
  END IF;
  UPDATE public.outbox_events SET status='PENDING', lease_owner=NULL, lease_token=NULL, lease_expires_at=NULL,
         next_attempt_at=now()+make_interval(secs=>p_backoff), error_detail_sanitized=safe WHERE id=p_event;
  RETURN 'PENDING';
END $$;
ALTER FUNCTION retry_outbox_event(UUID, TEXT, UUID, TEXT, INTEGER) OWNER TO index_dispatcher_owner;
REVOKE ALL ON FUNCTION retry_outbox_event(UUID, TEXT, UUID, TEXT, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retry_outbox_event(UUID, TEXT, UUID, TEXT, INTEGER) TO index_worker_service;
