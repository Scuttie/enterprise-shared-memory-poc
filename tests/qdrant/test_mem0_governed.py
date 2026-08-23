"""Governed Mem0 index contract, proven WITHOUT torch / a model download / any network. A stub emulates
the mem0.Memory surface and RAISES if infer=True is ever requested, and counts the LLM calls that Mem0's
inference path would make. The governed wrapper must: never pass infer=True (hidden LLM calls == 0), keep
private and shared physically separate instances, and expose reference payloads only."""
import pytest
from conftest import mk_record
from enterprise_memory.indexing.mem0_indexes import GovernedMem0Index
from enterprise_memory.indexing.models import PRIVATE, SHARED


class MemoryStub:
    def __init__(self):
        self.items = []
        self.llm_calls = 0            # increments only on the inference (LLM) path

    def add(self, text, *, user_id, metadata, infer=True):
        if infer:
            self.llm_calls += 1
            raise AssertionError("governed indexing must never use infer=True")
        mid = str(len(self.items))
        self.items.append({"id": mid, "text": text, "user_id": str(user_id), "metadata": dict(metadata)})
        return {"results": [{"id": mid}]}

    def search(self, query, *, top_k, filters):
        uid = str(filters["user_id"])
        hits = [{"id": it["id"], "metadata": it["metadata"], "score": 1.0}
                for it in self.items if it["user_id"] == uid]
        return {"results": hits[:top_k]}

    def get_all(self, *, filters):
        uid = str(filters["user_id"])
        return {"results": [{"id": it["id"], "metadata": it["metadata"]}
                            for it in self.items if it["user_id"] == uid]}

    def delete(self, memory_id):
        self.items = [it for it in self.items if it["id"] != memory_id]


def _priv(oid, org, owner, h, text):
    return mk_record(PRIVATE, canonical_version_id=oid, org_id=org, content_hash=h, text=text,
                     owner_user_id=owner)


def _shared(oid, org, h, text):
    return mk_record(SHARED, canonical_version_id=oid, org_id=org, content_hash=h, text=text,
                     contract_id="c1")


def test_requires_separate_instances():
    m = MemoryStub()
    with pytest.raises(ValueError):
        GovernedMem0Index(m, m)


def test_governed_infer_false_zero_llm_and_separation():
    priv, shar = MemoryStub(), MemoryStub()
    idx = GovernedMem0Index(priv, shar)
    idx.index(_priv("ep1", "o1", "u1", "hp", "alpha retry backoff"))
    idx.index(_shared("v1", "o1", "hs", "alpha retry backoff"))

    # zero hidden LLM calls on both physical stores
    assert priv.llm_calls == 0 and shar.llm_calls == 0

    # get_all lists the scoped references (the 'get' operation)
    assert {c["canonical_version_id"] for c in idx.get_all(SHARED, "o1")} == {"v1"}
    # candidates return reference payloads only (content_hash present, canonical text absent)
    sc = idx.candidates(SHARED, "alpha retry backoff", "o1")
    assert sc and sc[0]["canonical_content_hash"] == "hs" and sc[0]["canonical_version_id"] == "v1"
    pc = idx.candidates(PRIVATE, "alpha retry backoff", "u1")
    assert pc and pc[0]["canonical_version_id"] == "ep1"

    # physical separation: the private episode lives only in the private store
    assert all(c["canonical_version_id"] != "ep1" for c in sc)
    assert all(c["canonical_version_id"] != "v1" for c in pc)


def test_delete_removes_reference():
    priv, shar = MemoryStub(), MemoryStub()
    idx = GovernedMem0Index(priv, shar)
    idx.index(_shared("v1", "o1", "hs", "text one"))
    mid = shar.items[0]["id"]
    idx.delete(SHARED, mid)
    assert idx.candidates(SHARED, "text one", "o1") == []
