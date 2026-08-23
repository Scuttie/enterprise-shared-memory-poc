"""p5.2: per-job raw+applied patch for adoption forensics
Revision ID: 0013
Revises: 0012
"""
import hashlib
from pathlib import Path
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_SQL = Path(__file__).resolve().parents[1] / "sql" / "0013_up.sql"
_EXPECTED = (Path(__file__).resolve().parents[1] / "sql" / "0013_up.sha256").read_text(encoding="utf-8").strip()


def upgrade():
    body = _SQL.read_text(encoding="utf-8").replace("\r\n", "\n")
    if hashlib.sha256(body.encode()).hexdigest() != _EXPECTED:
        raise RuntimeError("0013_up.sql hash mismatch")
    cur = op.get_bind().connection.dbapi_connection.cursor()
    try:
        cur.execute(body)
    finally:
        cur.close()


def downgrade():
    raise RuntimeError("revision 0013 downgrade is not supported")
