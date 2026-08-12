"""p2.1: index audit + outbox lease heartbeat
Revision ID: 0006
Revises: 0005
"""
import hashlib
from pathlib import Path
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_SQL = Path(__file__).resolve().parents[1] / "sql" / "0006_up.sql"
_EXPECTED = (Path(__file__).resolve().parents[1] / "sql" / "0006_up.sha256").read_text(encoding="utf-8").strip()


def upgrade():
    body = _SQL.read_text(encoding="utf-8").replace("\r\n", "\n")
    if hashlib.sha256(body.encode()).hexdigest() != _EXPECTED:
        raise RuntimeError("0006_up.sql hash mismatch")
    cur = op.get_bind().connection.dbapi_connection.cursor()
    try:
        cur.execute(body)
    finally:
        cur.close()


def downgrade():
    raise RuntimeError("revision 0006 downgrade is not supported")
