import importlib.util
import json
from pathlib import Path
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "trimem_benchmark_run_checkpoint_test",
    ROOT / "scripts" / "trimem_benchmark_run.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
BenchmarkExecutionError = MODULE.BenchmarkExecutionError
prepare_arm_identity = MODULE.prepare_arm_identity


def _prepare(root, *, lock="sha256:" + "1" * 64, resume=False):
    return prepare_arm_identity(
        root,
        arm="M0",
        split="development",
        experiment_id="trimemv1-deadbeef0000",
        execution_lock_hash=lock,
        resume=resume,
    )


def test_session_nonce_is_persisted_before_claim_and_reused_exactly(tmp_path):
    identity = _prepare(tmp_path)
    assert str(uuid.UUID(identity["run_nonce"])) == identity["run_nonce"]

    restored = _prepare(tmp_path, resume=True)
    assert restored == identity

    with pytest.raises(BenchmarkExecutionError, match="already exists"):
        _prepare(tmp_path)


def test_session_identity_binds_execution_lock_and_fails_closed_on_tamper(tmp_path):
    _prepare(tmp_path)
    with pytest.raises(BenchmarkExecutionError, match="configuration mismatch"):
        _prepare(tmp_path, lock="sha256:" + "2" * 64, resume=True)

    path = tmp_path / "M0.session-identity.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["run_nonce"] = "00000000-0000-4000-8000-000000000123"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(BenchmarkExecutionError, match="digest mismatch"):
        _prepare(tmp_path, resume=True)
