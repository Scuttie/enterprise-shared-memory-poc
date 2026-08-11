-- Bootstrap the runtime roles (run as a superuser/migration owner BEFORE the migration).
-- Test-only passwords; production uses a managed secret store + SSO-mapped roles.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='api_service') THEN
    CREATE ROLE api_service LOGIN PASSWORD 'api_pw' NOBYPASSRLS; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='worker_service') THEN
    CREATE ROLE worker_service LOGIN PASSWORD 'worker_pw' NOBYPASSRLS; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='audit_reader') THEN
    CREATE ROLE audit_reader LOGIN PASSWORD 'audit_pw' NOBYPASSRLS; END IF;
END $$;
