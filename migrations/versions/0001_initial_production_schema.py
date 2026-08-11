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


def upgrade():
    op.get_bind().exec_driver_sql(_SCHEMA.read_text(encoding="utf-8"))


def downgrade():
    op.get_bind().exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
