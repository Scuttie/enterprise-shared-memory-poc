-- Bootstrap runtime roles (as superuser) BEFORE migrations. CI-only test passwords; production uses a
-- managed secret store + SSO-mapped roles. job_dispatcher_owner: NOLOGIN, non-superuser, BYPASSRLS -- it
-- owns ONLY the claim function so the controlled cross-tenant claim works without granting BYPASSRLS to
-- any login role (worker_service stays NOBYPASSRLS).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='api_service') THEN
    CREATE ROLE api_service LOGIN PASSWORD 'api_pw' NOBYPASSRLS; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='worker_service') THEN
    CREATE ROLE worker_service LOGIN PASSWORD 'worker_pw' NOBYPASSRLS; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='audit_reader') THEN
    CREATE ROLE audit_reader LOGIN PASSWORD 'audit_pw' NOBYPASSRLS; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='job_dispatcher_owner') THEN
    CREATE ROLE job_dispatcher_owner NOLOGIN NOSUPERUSER BYPASSRLS; END IF;
END $$;
