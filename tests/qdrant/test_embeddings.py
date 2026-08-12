"""DeterministicTestEmbedder: reproducible, offline, credential-free, provenance-stamped."""
from enterprise_memory.indexing.embeddings import DeterministicTestEmbedder


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_deterministic_and_normalised():
    e = DeterministicTestEmbedder(64)
    v1 = e.embed(["retry once with backoff"])[0]
    v2 = e.embed(["retry once with backoff"])[0]
    assert v1 == v2                                   # identical text -> identical vector
    assert abs(_cos(v1, v1) - 1.0) < 1e-9             # L2-normalised
    assert len(v1) == 64


def test_distinct_texts_separate():
    e = DeterministicTestEmbedder(64)
    a = e.embed(["retry once with backoff"])[0]
    b = e.embed(["delete the production database"])[0]
    assert _cos(a, b) < 0.9                           # unrelated texts are not collinear


def test_provenance_stamp():
    e = DeterministicTestEmbedder(48)
    p = e.provenance()
    assert p["model_id"] == "deterministic-test-embedder-v1" and p["dim"] == 48
    assert p["algorithm_digest"].startswith("sha256-")
