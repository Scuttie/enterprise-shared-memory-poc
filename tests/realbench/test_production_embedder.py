"""REALBENCH-R2 §6.2 — the pinned production embedder loads, is real (not the deterministic test embedder),
produces L2-normalised vectors of its native dimension, and reports a pinnable identity/revision. Skips where
sentence-transformers is not installed (local Windows); runs in CI via the .[embed] extra."""
import math
import pytest

st = pytest.importorskip("sentence_transformers")


def test_production_embedder_is_real_and_normalized():
    from enterprise_memory.indexing.embeddings import SentenceTransformerEmbedder, DeterministicTestEmbedder
    emb = SentenceTransformerEmbedder("sentence-transformers/all-MiniLM-L6-v2")
    vs = emb.embed(["sort a list of integers", "parse a date string"])
    assert emb.dim == 384
    assert not isinstance(emb, DeterministicTestEmbedder)
    for v in vs:
        assert len(v) == 384
        assert abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-3        # L2-normalised
    # semantically related > unrelated (sanity that it is a real embedder, not a hash)
    a, b = emb.embed(["read a csv file with pandas"]), emb.embed(["load a csv into a pandas dataframe"])
    c = emb.embed(["compute the factorial of n recursively"])
    dot = lambda x, y: sum(i * j for i, j in zip(x, y))
    assert dot(a[0], b[0]) > dot(a[0], c[0])


def test_provenance_pins_identity_and_revision():
    from enterprise_memory.indexing.embeddings import SentenceTransformerEmbedder
    p = SentenceTransformerEmbedder("sentence-transformers/all-MiniLM-L6-v2").provenance()
    assert p["model_id"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert p["dim"] == 384
    assert p["sentence_transformers_version"]
    assert "revision" in p            # resolved snapshot revision recorded for reproducibility
