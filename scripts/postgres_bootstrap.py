"""Create runtime roles (as superuser) before Alembic. CI-only; test passwords."""
import os, psycopg2
conn = psycopg2.connect(host=os.environ.get("PGHOST", "localhost"), port=int(os.environ.get("PGPORT", "5432")),
                        user=os.environ.get("PGUSER", "postgres"), password=os.environ.get("PGPASSWORD", "postgres"),
                        dbname=os.environ.get("PGDATABASE", "esm"))
conn.autocommit = True
with open("scripts/postgres_bootstrap_roles.sql", encoding="utf-8") as f:
    conn.cursor().execute(f.read())
print("roles bootstrapped")
