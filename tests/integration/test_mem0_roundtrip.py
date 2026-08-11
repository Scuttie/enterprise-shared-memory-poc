"""§4 Mem0 live round-trip + separation. SKIPS unless mem0+torch are importable (only in
.venv-enterprise), so the base CI (InMemoryBackend) never needs torch/mem0. The authoritative
evidence of a passing live run is enterprise_shared_memory/reports/mem0_validation.json."""
import os
import json
import pytest

pytest.importorskip("mem0")
pytest.importorskip("torch")


def test_validation_artifact_present_and_passing():
    p = os.path.join(os.path.dirname(__file__), "..", "..", "reports", "mem0_validation.json")
    if not os.path.exists(p):
        pytest.skip("run scripts/mem0_validate.py in .venv-enterprise first")
    d = json.load(open(p, encoding="utf-8"))
    assert d["roundtrip"]["contract_id_recovered"] and d["roundtrip"]["sqlite_hash_matches"]
    assert d["separation"]["distinct_qdrant_dirs"] and not d["separation"]["shared_backend_sees_private_record"]
    assert d["embed_under_500mb"]
