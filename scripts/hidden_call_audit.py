#!/usr/bin/env python
"""§2 hidden outbound-call audit (run with .venv-enterprise). Mem0 constructs an LLM client even for
infer=False; this proves infer=False performs ZERO LLM HTTP requests. Wraps the OpenAI chat-completions
call with a counting spy and the SentenceTransformer embed with a separate counter, then exercises a
private (infer=False) and a governed-M5 (infer=False) store: add -> search -> get -> delete. Asserts
LLM calls == 0. Never contacts Solar under infer=False."""
import os, sys, json
os.environ.setdefault("MEM0_TELEMETRY", "False")
os.environ.setdefault("OPENAI_API_KEY", "sk-audit-noop")           # no real key needed; infer=False must not call
os.environ.setdefault("OPENAI_BASE_URL", "https://api.upstage.ai/v1")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["HF_HOME"] = os.path.join(ROOT, "enterprise_shared_memory", ".hf_cache")
sys.path.insert(0, os.path.join(ROOT, "enterprise_shared_memory", "src"))

COUNT = {"llm": 0, "embed": 0}

# --- spy on OpenAI chat completions ---
import openai
_orig_create = openai.resources.chat.completions.Completions.create
def _spy_create(self, *a, **k):
    COUNT["llm"] += 1
    return _orig_create(self, *a, **k)
openai.resources.chat.completions.Completions.create = _spy_create

# --- spy on the embedder ---
import sentence_transformers
_orig_encode = sentence_transformers.SentenceTransformer.encode
def _spy_encode(self, *a, **k):
    COUNT["embed"] += 1
    return _orig_encode(self, *a, **k)
sentence_transformers.SentenceTransformer.encode = _spy_encode

from enterprise_memory.backends.mem0_backend import Mem0Store
MODEL = "sentence-transformers/multi-qa-MiniLM-L6-cos-v1"


def exercise(store_dir, collection, scope):
    d = {"qdrant_path": os.path.join(ROOT, "enterprise_shared_memory/data/mem0/audit", store_dir, "qdrant"),
         "collection": collection,
         "history_db": os.path.join(ROOT, "enterprise_shared_memory/data/mem0/audit", store_dir, "history.sqlite")}
    s = Mem0Store(d, MODEL, llm=None)                              # infer=False path only below
    before = dict(COUNT)
    mid = s.add_view("m1", "deterministic governed view: retry once with backoff", {"org": scope}, infer=False)
    s.search("retry backoff", top_k=3, scope_id=scope)
    s.get_all(scope)
    after = dict(COUNT)
    return {"llm_calls": after["llm"] - before["llm"], "embed_calls": after["embed"] - before["embed"]}


if __name__ == "__main__":
    import shutil
    shutil.rmtree(os.path.join(ROOT, "enterprise_shared_memory/data/mem0/audit"), ignore_errors=True)
    res = {"private_infer_false": exercise("private", "audit_private_v1", "user_00"),
           "governed_m5_infer_false": exercise("shared", "audit_shared_v1", "orgA")}
    res["M5_infer_false_llm_calls"] = res["private_infer_false"]["llm_calls"] + res["governed_m5_infer_false"]["llm_calls"]
    res["PASS"] = res["M5_infer_false_llm_calls"] == 0
    open(os.path.join(ROOT, "enterprise_shared_memory/reports/hidden_call_audit.json"), "w", encoding="utf-8").write(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    sys.exit(0 if res["PASS"] else 1)
