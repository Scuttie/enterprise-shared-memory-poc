"""Pinned embedder policy (P3.1 §4) — injected loader so no torch/model download is needed."""
import pytest
from enterprise_memory.indexing.mem0_indexes import enforce_embedder_pin, EmbedderPinError, EMBEDDER_PIN


class FakeModel:
    def __init__(self, dim=384):
        self._d = dim

    def get_sentence_embedding_dimension(self):
        return self._d


def test_trust_remote_code_rejected():
    with pytest.raises(EmbedderPinError):
        enforce_embedder_pin(trust_remote_code=True, loader=lambda: FakeModel(), environment="test")


def test_dimension_mismatch_rejected():
    with pytest.raises(EmbedderPinError):
        enforce_embedder_pin(revision="abc", loader=lambda: FakeModel(dim=128), info_fn=lambda: "abc",
                             environment="test")


def test_production_requires_pinned_revision():
    with pytest.raises(EmbedderPinError):
        enforce_embedder_pin(revision=None, loader=lambda: FakeModel(), environment="production")


def test_records_provenance():
    prov = enforce_embedder_pin(revision="rev-sha", loader=lambda: FakeModel(384),
                                info_fn=lambda: "resolved-sha", environment="test")
    assert prov["model_id"] == EMBEDDER_PIN["model_id"] and prov["trust_remote_code"] is False
    assert prov["dimension"] == 384 and prov["resolved_revision"] == "resolved-sha"
    assert prov["license"] == "Apache-2.0" and prov["requested_revision"] == "rev-sha"
