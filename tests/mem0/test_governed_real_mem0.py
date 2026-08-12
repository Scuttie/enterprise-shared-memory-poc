"""P2.1 §9 — REAL mem0ai (not a stub) under governed infer=False. Spies the OpenAI LLM transport (must
never be called) and the sentence-transformers embedder (counted). Proves: physically separate private/
shared Memory instances, infer=False, add/search/delete, canonical metadata survives, hidden LLM calls == 0,
embeddings counted, and that the authoritative content is reloaded from PostgreSQL — Mem0 prose is never
returned to the caller."""
import os
import pytest

os.environ.setdefault("MEM0_TELEMETRY", "False")
os.environ.setdefault("OPENAI_API_KEY", "sk-noop")          # placeholder; infer=False must never call it
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

pytest.importorskip("mem0")
pytest.importorskip("torch")
st = pytest.importorskip("sentence_transformers")
openai = pytest.importorskip("openai")

from conftest import eng, run, seed_contract                 # noqa: E402

COUNT = {"llm": 0, "embed": 0}

_orig_create = openai.resources.chat.completions.Completions.create


def _spy_create(self, *a, **k):                              # no-network: increment and refuse
    COUNT["llm"] += 1
    raise AssertionError("LLM transport must not be called under infer=False")


openai.resources.chat.completions.Completions.create = _spy_create

_orig_encode = st.SentenceTransformer.encode


def _spy_encode(self, *a, **k):
    COUNT["embed"] += 1
    return _orig_encode(self, *a, **k)


st.SentenceTransformer.encode = _spy_encode

from enterprise_memory.indexing.mem0_indexes import build_real     # noqa: E402
from enterprise_memory.indexing.projection import build_record     # noqa: E402
from enterprise_memory.indexing.models import SHARED, PRIVATE, IndexRecord, ObjectType  # noqa: E402
from enterprise_memory.indexing import canonical_loaders as cl     # noqa: E402

MODEL = "sentence-transformers/multi-qa-MiniLM-L6-cos-v1"
pytestmark = pytest.mark.mem0


def _paths(tmp):
    return {"private": {"qdrant_path": str(tmp / "priv" / "qdrant"),
                        "collection": "enterprise_private_v1",
                        "history_db": str(tmp / "priv" / "history.sqlite")},
            "shared": {"qdrant_path": str(tmp / "shar" / "qdrant"),
                       "collection": "enterprise_shared_v1",
                       "history_db": str(tmp / "shar" / "history.sqlite")}}


def test_governed_real_mem0_infer_false_zero_llm_pg_reload(tmp_path, org_ids):
    a = org_ids
    canonical = {"text": "retry once with backoff", "path_scope": ["src/**"]}
    cid, vid, h = run(seed_contract(a["org"], a["repo"], canonical))

    ie = eng("index"); row = run(cl.load_contract_version(ie, a["org"], vid)); run(ie.dispose())
    rec = build_record(SHARED, row)

    before = dict(COUNT)
    idx = build_real(_paths(tmp_path), MODEL)               # real Mem0 stores, physically separate
    idx.index(rec)                                          # governed add: infer=False
    cands = idx.candidates(SHARED, "retry once with backoff", str(a["org"]))

    assert COUNT["llm"] == before["llm"] == 0               # hidden LLM calls == 0
    assert COUNT["embed"] > before["embed"]                 # embeddings did happen (counted separately)

    assert cands and cands[0]["canonical_version_id"] == vid and cands[0]["canonical_content_hash"] == h
    # reference only — Mem0 prose never leaves the adapter
    assert all(k not in cands[0] for k in ("text", "memory", "data", "canonical", "canonical_json"))

    # authoritative content comes from PostgreSQL, reloaded from the reference
    ie = eng("index")
    reload = run(cl.load_contract_version(ie, a["org"], cands[0]["canonical_version_id"]))
    run(ie.dispose())
    assert reload["canonical"] == canonical


def test_separation_and_delete(tmp_path, org_ids):
    a = org_ids
    cs = {"text": "shared alpha phrase"}
    _, vids, _ = run(seed_contract(a["org"], a["repo"], cs))
    ie = eng("index"); row = run(cl.load_contract_version(ie, a["org"], vids)); run(ie.dispose())
    rec_s = build_record(SHARED, row)
    rec_p = IndexRecord(scope=PRIVATE, object_kind=ObjectType.PRIVATE_EPISODE.value, canonical_id="ep",
                        canonical_version_id="ep", canonical_version_number=1, canonical_content_hash="hp",
                        org_id=str(a["org"]), text="private beta phrase", owner_user_id=str(a["user"]))

    idx = build_real(_paths(tmp_path), MODEL)
    idx.index(rec_s); idx.index(rec_p)

    sc = idx.candidates(SHARED, "shared alpha phrase", str(a["org"]))
    pc = idx.candidates(PRIVATE, "private beta phrase", str(a["user"]))
    assert any(c["canonical_version_id"] == vids for c in sc)
    assert all(c.get("object_kind") != ObjectType.PRIVATE_EPISODE.value for c in sc)   # separation
    assert any(c["canonical_version_id"] == "ep" for c in pc)

    # delete via the underlying Mem0 memory id, then the shared candidate is gone
    res = idx._m[SHARED].search("shared alpha phrase", top_k=5, filters={"user_id": str(a["org"])})
    results = res.get("results", res) if isinstance(res, dict) else res
    idx.delete(SHARED, results[0]["id"])
    after = idx.candidates(SHARED, "shared alpha phrase", str(a["org"]))
    assert all(c["canonical_version_id"] != vids for c in after)
