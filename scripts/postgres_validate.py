"""Post-migration sanity: required tables exist and RLS is forced."""
import os, psycopg2
conn = psycopg2.connect(host=os.environ.get("PGHOST", "localhost"), port=int(os.environ.get("PGPORT", "5432")),
                        user=os.environ.get("PGUSER", "postgres"), password=os.environ.get("PGPASSWORD", "postgres"),
                        dbname=os.environ.get("PGDATABASE", "esm"))
cur = conn.cursor()
for t in ("organisations", "private_episodes", "solve_jobs", "outbox_events", "audit_events", "memory_contract_versions"):
    cur.execute("SELECT to_regclass(%s)", ("public." + t,))
    assert cur.fetchone()[0] is not None, "missing table " + t
cur.execute("SELECT count(*) FROM pg_class WHERE relrowsecurity AND relforcerowsecurity")
assert cur.fetchone()[0] >= 15, "RLS not forced on enough tables"
print("postgres schema validated")
