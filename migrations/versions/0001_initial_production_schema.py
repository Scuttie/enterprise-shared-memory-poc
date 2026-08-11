"""initial production schema
Revision ID: 0001
Revises:
"""
from pathlib import Path
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_SCHEMA = Path(__file__).resolve().parents[2] / "src" / "enterprise_memory" / "persistence" / "schema.sql"


def _raw_execute(sql: str):
    # raw psycopg2 cursor on the migration connection: runs multi-statement DDL (DO blocks, functions,
    # $$ bodies) as one PQexec without SQLAlchemy parameter binding.
    cur = op.get_bind().connection.dbapi_connection.cursor()
    try:
        cur.execute(sql)
    finally:
        cur.close()


def upgrade():
    _raw_execute(_SCHEMA.read_text(encoding="utf-8"))


def downgrade():
    _raw_execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
