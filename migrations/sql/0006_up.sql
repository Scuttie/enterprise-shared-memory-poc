-- P2.1 §10: append-only index-operation audit + outbox lease heartbeat. Runs after 0005. The frozen SQL
-- bodies of 0001-0005 are untouched.

-- ------------------------------------------------------------------ append-only index audit
CREATE TABLE index_audit_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations(id),
  outbox_event_id UUID, worker_id TEXT, lease_token UUID,
  object_kind TEXT, canonical_id UUID, canonical_version_id UUID, canonical_version_number INTEGER,
  content_hash TEXT, qdrant_operation TEXT, point_id TEXT, collection TEXT,
  result TEXT NOT NULL, detail_json JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE index_audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE index_audit_events FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON index_audit_events USING
  (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);
-- append-only: no UPDATE/DELETE (reuses the reject_mutation() trigger fn from 0002)
CREATE TRIGGER index_audit_append_only BEFORE UPDATE OR DELETE ON index_audit_events
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();
GRANT SELECT, INSERT ON index_audit_events TO index_worker_service;
GRANT SELECT ON index_audit_events TO audit_reader;

-- ------------------------------------------------------------------ outbox lease heartbeat (long rebuilds)
CREATE FUNCTION heartbeat_outbox_event(p_event UUID, p_worker TEXT, p_token UUID, p_lease_seconds INTEGER)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE n INT;
BEGIN
  IF p_lease_seconds < 1 OR p_lease_seconds > 3600 THEN RAISE EXCEPTION 'lease seconds out of bounds'; END IF;
  UPDATE public.outbox_events SET lease_expires_at = now() + make_interval(secs => p_lease_seconds)
   WHERE id = p_event AND status = 'PROCESSING' AND lease_owner = p_worker
     AND lease_token = p_token AND lease_expires_at > now();
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'invalid or expired lease'; END IF;
  RETURN true;
END $$;
ALTER FUNCTION heartbeat_outbox_event(UUID, TEXT, UUID, INTEGER) OWNER TO index_dispatcher_owner;
REVOKE ALL ON FUNCTION heartbeat_outbox_event(UUID, TEXT, UUID, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION heartbeat_outbox_event(UUID, TEXT, UUID, INTEGER) TO index_worker_service;
