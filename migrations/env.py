"""Alembic env — SYNC psycopg2 engine (multi-statement DDL incl. DO blocks / functions). Runtime uses
asyncpg separately. Migrations connect as MIGRATION_USER (owner/superuser)."""
import os
from alembic import context
from sqlalchemy import create_engine


def _sync_dsn():
    base = os.environ["DATABASE_URL"]
    host = base.split("://", 1)[1]
    if "@" in host:
        host = host.split("@", 1)[1]
    u = os.environ.get("MIGRATION_USER", "postgres")
    p = os.environ.get("MIGRATION_PASSWORD", "postgres")
    return "postgresql+psycopg2://%s:%s@%s" % (u, p, host)


def run():
    engine = create_engine(_sync_dsn())
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run()
