"""§2 downgrade safety (no DB): both migrations declare an irreversible downgrade that raises rather than
DROP SCHEMA public, so unrelated pre-existing public objects can never be destroyed by a downgrade."""
import os
import importlib.util
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(fn):
    spec = importlib.util.spec_from_file_location(fn.replace(".py", ""), os.path.join(ROOT, "migrations", "versions", fn))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_downgrades_are_irreversible_not_destructive():
    for fn in ("0001_initial_production_schema.py", "0002_p1_hardening.py"):
        m = _load(fn)
        with pytest.raises(RuntimeError):
            m.downgrade()      # raises immediately (no op.execute) -> nothing dropped
        src = open(os.path.join(ROOT, "migrations", "versions", fn), encoding="utf-8").read()
        assert "DROP SCHEMA public" not in src
