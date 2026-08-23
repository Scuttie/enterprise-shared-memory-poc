#!/usr/bin/env python3
"""Migration head guard shared by every migration-aware CI workflow.

Instead of hard-coding a revision string (which goes stale the moment a new migration lands — as `0013` did after
`0014`), this reads the real Alembic **script head** from the migration tree and compares it to the **DB applied
head** recorded in the target database. It fails if they differ, if there is more than one head, or if the DB is
not at head. No revision number is baked in, so it stays correct across future migrations.

Usage:
  python scripts/check_migration_head.py                # compare script head vs DB applied head (needs DATABASE_URL)
  python scripts/check_migration_head.py --script-only  # only assert a single script head (no DB; used by unit test)
"""
import os
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALEMBIC_INI = os.path.join(ROOT, "alembic.ini")


def script_heads():
    """Head revision(s) defined by the migration scripts on disk (no DB access)."""
    return list(ScriptDirectory.from_config(Config(ALEMBIC_INI)).get_heads())


def _sync_dsn():
    # Mirror migrations/env.py: migrations connect as the MIGRATION_USER against DATABASE_URL's host.
    base = os.environ["DATABASE_URL"]
    host = base.split("://", 1)[1]
    if "@" in host:
        host = host.split("@", 1)[1]
    user = os.environ.get("MIGRATION_USER", "postgres")
    pw = os.environ.get("MIGRATION_PASSWORD", "postgres")
    return "postgresql+psycopg2://%s:%s@%s" % (user, pw, host)


def db_heads():
    """Head revision(s) actually applied in the target database."""
    from sqlalchemy import create_engine
    from alembic.runtime.migration import MigrationContext
    engine = create_engine(_sync_dsn())
    try:
        with engine.connect() as conn:
            return list(MigrationContext.configure(conn).get_current_heads())
    finally:
        engine.dispose()


def main(argv):
    heads = script_heads()
    if len(heads) != 1:
        print("MIGRATION HEAD: FAIL — expected exactly one script head, found %s" % heads)
        return 1
    script_head = heads[0]

    if "--script-only" in argv:
        print("MIGRATION HEAD (script-only): PASS — single script head %s" % script_head)
        return 0

    applied = db_heads()
    if applied != [script_head]:
        print("MIGRATION HEAD: FAIL — script head %s but DB applied head %s (DB not at head?)"
              % (script_head, applied))
        return 1
    print("MIGRATION HEAD: PASS — DB at script head %s" % script_head)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
