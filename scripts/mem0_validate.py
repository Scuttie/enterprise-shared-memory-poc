#!/usr/bin/env python
"""§2/§4 live validation (run with .venv-enterprise): pin+download the HF embedding model (record
revision/license/size, trust_remote_code=False), build physically-separated private/shared Mem0
stores over local Qdrant, run the infer=False canonical round-trip + private/shared separation, and an
optional M3 infer=True Solar smoke (only if UPSTAGE_API_KEY is set). Writes report artifacts. Never
prints the API key."""
import os, sys, json, glob, hashlib
os.environ.setdefault("MEM0_TELEMETRY", "False")
# mem0 2.0.17's Memory always constructs an LLM (default OpenAI) even for infer=False governed
# indexing, which is never actually invoked unless infer=True. Point that client at the Solar
# (OpenAI-compatible) endpoint so construction succeeds; the key is taken ONLY from UPSTAGE_API_KEY.
_k = os.environ.get("UPSTAGE_API_KEY")
if _k:
    os.environ.setdefault("OPENAI_API_KEY", _k)
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.upstage.ai/v1")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["HF_HOME"] = os.path.join(ROOT, "enterprise_shared_memory", ".hf_cache")
sys.path.insert(0, os.path.join(ROOT, "enterprise_shared_memory", "src"))

MODEL = "sentence-transformers/multi-qa-MiniLM-L6-cos-v1"
PATHS = {"private": {"qdrant_path": os.path.join(ROOT, "enterprise_shared_memory/data/mem0/private/qdrant"),
                     "collection": "enterprise_private_v1",
                     "history_db": os.path.join(ROOT, "enterprise_shared_memory/data/mem0/private/history.sqlite")},
         "shared": {"qdrant_path": os.path.join(ROOT, "enterprise_shared_memory/data/mem0/shared/qdrant"),
                    "collection": "enterprise_shared_v1",
                    "history_db": os.path.join(ROOT, "enterprise_shared_memory/data/mem0/shared/history.sqlite")}}
out = {"model": MODEL}


def embed_audit():
    from huggingface_hub import model_info
    try:
        info = model_info(MODEL)
        out["embed_revision"] = info.sha
        out["embed_license"] = (info.card_data or {}).get("license") if info.card_data else getattr(info, "license", None)
    except Exception as e:
        out["embed_revision"] = "unavailable(%s)" % type(e).__name__
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(MODEL, trust_remote_code=False)          # download + load
    out["embed_dim"] = m.get_sentence_embedding_dimension()
    cache = os.path.join(ROOT, "enterprise_shared_memory", ".hf_cache")
    total = sum(os.path.getsize(f) for f in glob.glob(cache + "/**", recursive=True) if os.path.isfile(f))
    out["embed_cache_bytes"] = total
    out["embed_under_500mb"] = total < 500 * 1024 * 1024


def roundtrip_and_separation():
    from enterprise_memory.backends.mem0_backend import build_private_shared
    from enterprise_memory.contracts.registry import SqliteRegistry
    from enterprise_memory.contracts import schema as S
    priv, shar = build_private_shared(PATHS, MODEL, llm=None)
    # authoritative contract in SQLite
    reg = SqliteRegistry(PATHS["shared"]["history_db"] + ".registry.sqlite"); reg.migrate()
    c = S.MemoryContract("c_rt", S.SCHEMA_VERSION, "retry rule", "For internal API v2, retry once with backoff.",
                         S.ContractScope("orgA", ["t1"], ["repoX"], ["src/**"], "python", "fw", {}, [], ["E_RETRY"],
                                         ["api v2 retry"], ["non-retryable"]),
                         S.ContractAction(["compute delay"], "code", [], ["retry_after"], ["op"]),
                         S.ContractValidity("2020", "", {}, {}, [], [], ""),
                         S.ContractVerification(["pytest"], ["passes"], ["noreg"], ["fails"]),
                         S.ContractProvenance(["ep_rt"], ["u0"], ["sha"], ["pass"], "x/1"),
                         S.ContractEvidence(), S.ContractGovernance(state="promoted")).stamp()
    reg.put_episode(S.PrivateEpisode("ep_rt", "user_00", "orgA", "repoX", "task", "sha", {}, [], [], "p", [], ["pytest"], {"passed": True}, "success", ["h"], "lk", "2026").stamp())
    canonical_hash = reg.put_contract(c)
    view = c.retrieval_view()
    view_text = json.dumps(view, sort_keys=True)
    shar.add_view("c_rt", view_text, {"org": "orgA", "contract_id": "c_rt", "state": "promoted"}, infer=False)
    # private store gets a DISTINCT private trace
    priv.add_view("ep_priv", "alice private raw trace: secret debugging notes", {"owner": "user_00", "org": "orgA"}, infer=False)
    # round-trip: search shared (scoped to org), reload canonical from SQLite by contract_id, compare
    hits = shar.search("internal API retry backoff", top_k=5, scope_id="orgA")
    got_cid = None
    for h in hits:
        md = h.get("metadata", {}) if isinstance(h, dict) else {}
        if md.get("contract_id") == "c_rt":
            got_cid = "c_rt"; break
    reloaded = reg.get_contract(got_cid) if got_cid else None
    out["roundtrip"] = {"shared_hits": len(hits), "contract_id_recovered": got_cid == "c_rt",
                        "sqlite_hash_matches": bool(reloaded and reloaded["content_hash"] == canonical_hash),
                        "canonical_hash": canonical_hash}
    # physical separation: distinct qdrant dirs + the shared store cannot see the private trace
    shared_sees_private = any("private raw trace" in (json.dumps(h) if not isinstance(h, str) else h)
                              for h in shar.search("private raw trace secret", top_k=10, scope_id="orgA"))
    out["separation"] = {"distinct_qdrant_dirs": PATHS["private"]["qdrant_path"] != PATHS["shared"]["qdrant_path"],
                         "distinct_collections": PATHS["private"]["collection"] != PATHS["shared"]["collection"],
                         "shared_backend_sees_private_record": shared_sees_private,
                         "private_count": len(priv.get_all("user_00")), "shared_count": len(shar.get_all("orgA"))}


def m3_smoke():
    key = os.environ.get("UPSTAGE_API_KEY")
    if not key:
        out["m3"] = {"available": False, "reason": "SOLAR_KEY_MISSING (non-blocking)"}
        return
    try:
        from enterprise_memory.backends.mem0_backend import Mem0Store
        llm = {"provider": "openai", "config": {"model": "solar-pro2-251215",
               "openai_base_url": "https://api.upstage.ai/v1", "temperature": 0}}
        disp = {"qdrant_path": os.path.join(ROOT, "enterprise_shared_memory/data/mem0/m3smoke/qdrant"),
                "collection": "m3_disposable", "history_db": os.path.join(ROOT, "enterprise_shared_memory/data/mem0/m3smoke/history.sqlite")}
        os.environ["OPENAI_API_KEY"] = key       # mem0 openai LLM reads OPENAI_API_KEY
        s = Mem0Store(disp, MODEL, llm=llm)
        r1 = s.add_episode_extracted("Fixed the checkout retry: for tenant ORCHID, retry delay doubles the Retry-After value.", "u_alice", {"org": "orgA"})
        mems = r1.get("results", r1) if isinstance(r1, dict) else r1
        found = s.search("tenant retry delay", top_k=5, scope_id="u_alice")
        out["m3"] = {"available": bool(mems), "extracted_count": len(mems) if hasattr(mems, "__len__") else None,
                     "search_hits": len(found), "credential_in_output": key in json.dumps(out.get("m3", {}))}
    except Exception as e:
        out["m3"] = {"available": False, "reason": "init/extract failed: %s" % type(e).__name__}


if __name__ == "__main__":
    embed_audit()
    roundtrip_and_separation()
    m3_smoke()
    # scrub any accidental key
    payload = json.dumps(out, indent=1)
    k = os.environ.get("UPSTAGE_API_KEY", "")
    if k:
        payload = payload.replace(k, "***REDACTED***")
    open(os.path.join(ROOT, "enterprise_shared_memory/reports/mem0_validation.json"), "w", encoding="utf-8").write(payload)
    print(payload)
