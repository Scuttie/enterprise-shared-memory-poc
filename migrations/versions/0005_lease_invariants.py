"""p2-start: residual job/outbox lease invariants
Revision ID: 0005
Revises: 0004
"""
import hashlib
from pathlib import Path
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_SQL = Path(__file__).resolve().parents[1] / "sql" / "0005_up.sql"
_EXPECTED = (Path(__file__).resolve().parents[1] / "sql" / "0005_up.sha256").read_text(encoding="utf-8").strip()


def upgrade():
    body = _SQL.read_text(encoding="utf-8").replace("\r\n", "\n")
    if hashlib.sha256(body.encode()).hexdigest() != _EXPECTED:
        raise RuntimeError("0005_up.sql hash mismatch")
    cur = op.get_bind().connection.dbapi_connection.cursor()
    try:
        cur.execute(body)
    finally:
        cur.close()


def downgrade():
    raise RuntimeError("revision 0005 downgrade is not supported")
