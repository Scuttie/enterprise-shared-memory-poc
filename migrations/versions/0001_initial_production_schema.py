"""initial production schema (FROZEN)
Revision ID: 0001
Revises:
"""
import hashlib
from pathlib import Path
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_SQL = Path(__file__).resolve().parents[1] / "sql" / "0001_up.sql"
_EXPECTED = (Path(__file__).resolve().parents[1] / "sql" / "0001_up.sha256").read_text(encoding="utf-8").strip()


def _raw(sql):
    cur = op.get_bind().connection.dbapi_connection.cursor()
    try:
        cur.execute(sql)
    finally:
        cur.close()


def upgrade():
    body = _SQL.read_text(encoding="utf-8").replace("\r\n", "\n")
    got = hashlib.sha256(body.encode()).hexdigest()
    if got != _EXPECTED:                       # frozen: migration output cannot depend on a mutated file
        raise RuntimeError("0001_up.sql hash mismatch: %s != %s" % (got, _EXPECTED))
    _raw(body)


def downgrade():
    # deliberately irreversible: never drop the whole public schema (would destroy unrelated objects).
    raise RuntimeError("revision 0001 downgrade is not supported (would require a destructive schema teardown)")
