"""P6/R19: utility-aware shared-memory experience layer (13 tables, RLS, immutable versions)
Revision ID: 0014
Revises: 0013
"""
import hashlib
from pathlib import Path
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_SQL = Path(__file__).resolve().parents[1] / "sql" / "0014_up.sql"
_EXPECTED = (Path(__file__).resolve().parents[1] / "sql" / "0014_up.sha256").read_text(encoding="utf-8").strip()


def upgrade():
    body = _SQL.read_text(encoding="utf-8").replace("\r\n", "\n")
    if hashlib.sha256(body.encode()).hexdigest() != _EXPECTED:
        raise RuntimeError("0014_up.sql hash mismatch")
    cur = op.get_bind().connection.dbapi_connection.cursor()
    try:
        cur.execute(body)
    finally:
        cur.close()


def downgrade():
    raise RuntimeError("revision 0014 downgrade is not supported")
