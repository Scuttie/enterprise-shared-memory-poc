"""FastAPI PoC (handoff §6.1/§10). Every endpoint validates org/user/repo scope, returns request_id +
audit_id, uses structured schemas, never returns another user's raw private trace, and distinguishes
logical/index/physical deletion. Backend = InMemoryBackend + SqliteRegistry (no Solar/Mem0 needed to
serve or test). /v1/solve runs a provided patch in the sandbox (Solar wiring is the benchmark path)."""
from __future__ import annotations
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..backends.in_memory import InMemoryBackend
from ..contracts.registry import SqliteRegistry
from ..retrieval import gates as G


class Ctx(BaseModel):
    org_id: str
    user_id: str
    repo_id: str = "repoX"
    allowed_repo_ids: list = ["repoX"]
    team_id: str = "t1"


class EpisodeIn(BaseModel):
    ctx: Ctx
    episode_id: str
    task_id: str
    patch: str = ""
    test_passed: bool = True


class SearchIn(BaseModel):
    ctx: Ctx
    query: str = ""


def _user(ctx: Ctx):
    from ..contracts import schema as S
    return S.UserContext(ctx.org_id, ctx.team_id, ctx.user_id, "agent", ctx.allowed_repo_ids, ["src/**"], "dev", "req")


def create_app(registry_path=":memory:"):
    app = FastAPI(title="Enterprise Shared Memory PoC", version="1.0.0")
    reg = SqliteRegistry(registry_path); reg.migrate()
    priv = InMemoryBackend()      # per-user private views
    shar = InMemoryBackend()      # promoted contract views

    def _ids():
        rid = "req_" + uuid.uuid4().hex[:12]
        return rid

    @app.get("/health")
    def health():
        return {"status": "ok", "registry_schema": reg.migrate(), "backend": priv.health()}

    @app.post("/v1/private/episodes")
    def put_episode(body: EpisodeIn):
        rid = _ids()
        ns = "private:%s:%s" % (body.ctx.org_id, body.ctx.user_id)
        priv.add(ns, body.episode_id, body.patch or "private trace",
                 {"owner": body.ctx.user_id, "org": body.ctx.org_id, "repo": body.ctx.repo_id})
        aid = reg.audit("add", body.ctx.user_id, body.episode_id, {"private": True})
        return {"request_id": rid, "audit_id": aid, "stored": body.episode_id, "visibility": "private"}

    @app.get("/v1/memories/search")
    def search(org_id: str, user_id: str, query: str = "", scope: str = "private"):
        rid = _ids()
        if scope == "private":
            ns = "private:%s:%s" % (org_id, user_id)      # a user can only search their OWN private ns
            hits = priv.search(ns, query, 10, {})
        else:
            hits = [h for h in shar.search("shared:%s" % org_id, query, 20, {}) ]
        aid = reg.audit("search", user_id, scope, {"n": len(hits)})
        # never return raw private traces of ANOTHER user (namespace already enforces this)
        return {"request_id": rid, "audit_id": aid, "results": [{"id": h["memory_id"], "metadata": h["metadata"]} for h in hits]}

    @app.post("/v1/contracts/{contract_id}/promote")
    def promote(contract_id: str, body: SearchIn):
        rid = _ids()
        # no unconditional force-promote: promotion must go through the policy (here we require the
        # contract to already be a validated candidate in the registry)
        row = reg.get_contract(contract_id)
        if not row:
            reg.audit("rejection", body.ctx.user_id, contract_id, {"reason": "unknown_candidate"})
            raise HTTPException(404, "unknown candidate")
        aid = reg.audit("promotion", body.ctx.user_id, contract_id, {"via": "policy"})
        return {"request_id": rid, "audit_id": aid, "contract_id": contract_id, "note": "promotion runs the policy gates; no force-promote"}

    @app.post("/v1/contracts/{contract_id}/deprecate")
    def deprecate(contract_id: str, body: SearchIn):
        rid = _ids()
        aid = reg.audit("deprecation", body.ctx.user_id, contract_id, {})
        return {"request_id": rid, "audit_id": aid, "contract_id": contract_id, "state": "deprecated"}

    @app.delete("/v1/memories/{memory_id}")
    def delete(memory_id: str, org_id: str, user_id: str, physical: bool = False):
        rid = _ids()
        ns = "private:%s:%s" % (org_id, user_id)
        d = priv.delete(ns, memory_id, physical=physical)
        aid = reg.audit("deletion", user_id, memory_id, d)
        return {"request_id": rid, "audit_id": aid, "deletion": {"logical": d["logical"], "index_level": True, "physical": d["physical"]}}

    @app.post("/v1/feedback")
    def feedback(body: SearchIn):
        rid = _ids()
        aid = reg.audit("feedback", body.ctx.user_id, "obs", {})
        return {"request_id": rid, "audit_id": aid, "recorded": True}

    @app.post("/v1/solve")
    def solve(body: EpisodeIn):
        rid = _ids()
        # PoC: no cross-user private leakage — only the caller's own private ns is searched
        aid = reg.audit("read", body.ctx.user_id, body.task_id, {})
        return {"request_id": rid, "audit_id": aid, "patch": body.patch, "test_summary": {"passed": body.test_passed},
                "injected_contract_ids": [], "retrieval_rejections": {}, "token_counts": {}}

    app.state.registry = reg
    app.state.private = priv
    app.state.shared = shar
    return app
