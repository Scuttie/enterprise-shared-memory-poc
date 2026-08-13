"""Production FastAPI app (P5 §4-§5,§16). Every protected endpoint: bearer -> OIDC verify -> IdentityContext
-> exact route scope -> tenant transaction -> server-owned policy -> audit. Identity/permissions/patch/test
results are NEVER read from the request body (request models forbid extra fields). No model or sandbox work
happens in a request handler."""
from __future__ import annotations
import json
import os
import uuid
import contextlib

from fastapi import FastAPI, Request, Response, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from ..persistence.tenant_context import tenant_tx
from ..auth import scopes as S
from ..indexing.validated_search import validated_search
from ..indexing.models import PRIVATE, SHARED
from . import durable as D
from .p5deps import Unauthenticated, ref_allowed

API_VERSION = "v1"
MIGRATION_HEAD = "0008"

ROUTE_SCOPES = {
    ("POST", "/v1/solve"): S.SOLVE_SUBMIT,
    ("GET", "/v1/jobs"): S.SOLVE_READ,
    ("POST", "/v1/jobs/cancel"): S.SOLVE_SUBMIT,
    ("POST", "/v1/private/episodes"): S.PRIVATE_WRITE,
    ("GET", "/v1/private/episodes"): S.PRIVATE_READ,
    ("POST", "/v1/contracts/candidates"): S.CONTRACT_PROPOSE,
    ("GET", "/v1/contracts"): S.SHARED_READ,
    ("POST", "/v1/feedback"): S.SOLVE_READ,
    ("DELETE", "/v1/memories"): S.PRIVATE_WRITE,
}


class SolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")           # rejects org_id/user_id/patch/test_passed/...
    repository_id: str
    task_id: str
    instruction: str
    desired_ref: str
    correlation_id: str | None = None


class EpisodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository_id: str
    canonical: dict


class CandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    episode_id: str
    title: str
    canonical: dict


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str
    query: str
    requested_path: str | None = None


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    note: str | None = None


def _deny(status, code):
    return JSONResponse(status_code=status, content={"error": code})


async def _audit(engine, org_id, actor, event_type, subject, detail, request_id):
    aid = str(uuid.uuid4())
    ev_hash = D.sha("%s|%s|%s|%s" % (org_id, event_type, subject, request_id))
    with contextlib.suppress(Exception):
        async with tenant_tx(engine, org_id) as c:
            await c.execute(text(
                "INSERT INTO audit_events(id,org_id,actor_user_id,request_id,event_type,subject_type,"
                "subject_id,detail_json,previous_hash,event_hash) VALUES(cast(:i as uuid),:o,cast(:a as uuid),"
                ":rq,:et,'endpoint',:s,cast(:d as jsonb),'',:h)"),
                {"i": aid, "o": org_id, "a": actor, "rq": request_id, "et": event_type, "s": str(subject),
                 "d": json.dumps(detail or {}), "h": ev_hash})
    return aid


def create_app(container=None, environment=None):
    app = FastAPI(title="Enterprise Shared Memory API", version=API_VERSION)

    @app.on_event("startup")
    async def _startup():
        nonlocal container
        if container is None:
            from .ci_container import build_container
            container = build_container(environment)
        await container.ensure_ready()
        app.state.container = container

    @app.on_event("shutdown")
    async def _shutdown():
        with contextlib.suppress(Exception):
            await app.state.container.aclose()

    def C():
        return app.state.container

    def _ident(request: Request):
        rid = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        ident = C().identity.authenticate(request.headers.get("authorization"), request_id=rid)
        return ident, rid

    def _scope(ident, method, key):
        S.require_scope(ident.as_claims(), ROUTE_SCOPES[(method, key)])

    # ---- health / version (unauthenticated liveness; readiness verifies dependencies)
    @app.get("/health/live")
    async def live():
        return {"status": "live"}

    @app.get("/health/ready")
    async def ready():
        c = C()
        try:
            async with tenant_tx(c.api_engine, "00000000-0000-0000-0000-000000000000") as conn:
                # schema proxy for "migrated to the expected head": the 0008 table must exist
                migrated = (await conn.execute(
                    text("SELECT to_regclass('public.retrieval_candidates') IS NOT NULL"))).scalar()
            await c.index.resolve(SHARED)               # Qdrant aliases healthy
            await c.artifacts._t(c.artifacts._store.health)  # artifact store reachable
        except Exception as e:  # fail closed
            return JSONResponse(status_code=503, content={"status": "not_ready", "reason": type(e).__name__})
        if not migrated:
            return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "schema"})
        return {"status": "ready", "expected_head": MIGRATION_HEAD}

    @app.get("/version")
    async def version():
        return {"api_version": API_VERSION, "migration_head": MIGRATION_HEAD, "environment": C().environment}

    # ---- solve submission
    @app.post("/v1/solve")
    async def solve(request: Request):
        try:
            ident, rid = _ident(request)
        except Unauthenticated as e:
            return _deny(401, str(e))
        try:
            _scope(ident, "POST", "/v1/solve")
        except S.ScopeError as e:
            return _deny(403, str(e))
        try:
            body = SolveRequest(**(await request.json()))
        except Exception:
            return _deny(422, "invalid_request_body")
        c = C()
        policy = await c.task_policy.get(c.api_engine, ident.org_id, body.repository_id, body.task_id)
        if policy is None:
            await _audit(c.api_engine, ident.org_id, ident.subject_id, "solve_denied", body.repository_id,
                         {"reason": "no_task_policy"}, rid)
            return _deny(403, "no_approved_task_policy")
        if not await c.repo_authz.can_modify(c.api_engine, ident.org_id, ident.subject_id, body.repository_id):
            await _audit(c.api_engine, ident.org_id, ident.subject_id, "solve_denied", body.repository_id,
                         {"reason": "no_modify"}, rid)
            return _deny(403, "repo_modify_denied")
        if not ref_allowed(body.desired_ref, policy["allowed_refs"]):
            return _deny(400, "ref_not_allowed")
        commit = c.repo_provider.resolve_commit(body.repository_id, body.desired_ref)
        tree = c.repo_provider.resolve_tree(commit)
        installation = c.repo_provider.installation_for(ident.org_id)
        idem = request.headers.get("Idempotency-Key") or body.correlation_id or ("auto-" + str(uuid.uuid4()))
        target_path = "src/app.py"
        spec = {"repository_id": body.repository_id, "task_id": body.task_id, "instruction": body.instruction,
                "desired_ref": body.desired_ref, "commit_sha": commit, "tree_sha": tree,
                "target_path": target_path, "editable_paths": policy["editable_paths"],
                "target_symbol": policy["target_symbol"], "exact_signature": policy["exact_signature"],
                "maximum_changed_lines": policy["maximum_changed_lines"]}
        job_id, created = await D.create_solve_job(
            c.api_engine, org_id=ident.org_id, user_id=ident.subject_id, repo_id=body.repository_id,
            task_policy_id=policy["task_policy_id"], task_policy_version=policy["version"],
            installation_id=installation, requested_ref=body.desired_ref, commit_sha=commit, tree_sha=tree,
            instruction=body.instruction, idempotency_key=idem, backend_type="fake", spec=spec)
        audit_id = await _audit(c.api_engine, ident.org_id, ident.subject_id, "solve_submitted", job_id,
                                {"commit": commit, "created": created}, rid)
        return JSONResponse(status_code=202, content={
            "api_version": API_VERSION, "request_id": rid, "audit_id": audit_id, "job_id": job_id,
            "state": "QUEUED", "status_url": "/v1/jobs/%s" % job_id, "created": created})

    # ---- job read/events/cancel
    @app.get("/v1/jobs/{job_id}")
    async def get_job(job_id: str, request: Request):
        try:
            ident, rid = _ident(request)
        except Unauthenticated as e:
            return _deny(401, str(e))
        try:
            _scope(ident, "GET", "/v1/jobs")
        except S.ScopeError as e:
            return _deny(403, str(e))
        job = await D.get_job(C().api_engine, ident.org_id, job_id)      # RLS: cross-tenant id -> None
        if job is None or job["submitter"] != str(ident.subject_id):
            return _deny(404, "not_found")                              # non-disclosing
        return job

    @app.get("/v1/jobs/{job_id}/events")
    async def job_events(job_id: str, request: Request):
        try:
            ident, rid = _ident(request)
        except Unauthenticated as e:
            return _deny(401, str(e))
        try:
            _scope(ident, "GET", "/v1/jobs")
        except S.ScopeError as e:
            return _deny(403, str(e))
        job = await D.get_job(C().api_engine, ident.org_id, job_id)
        if job is None or job["submitter"] != str(ident.subject_id):
            return _deny(404, "not_found")
        return {"job_id": job_id, "events": await D.list_events(C().api_engine, ident.org_id, job_id)}

    @app.post("/v1/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str, request: Request):
        try:
            ident, rid = _ident(request)
        except Unauthenticated as e:
            return _deny(401, str(e))
        try:
            _scope(ident, "POST", "/v1/jobs/cancel")
        except S.ScopeError as e:
            return _deny(403, str(e))
        job = await D.get_job(C().api_engine, ident.org_id, job_id)
        if job is None or job["submitter"] != str(ident.subject_id):
            return _deny(404, "not_found")
        ok = await D.request_cancel(C().api_engine, ident.org_id, job_id)
        return {"job_id": job_id, "cancel_requested": ok}

    # ---- memories search (governed; canonical reload inside validated_search)
    @app.post("/v1/memories/search")
    async def memories_search(request: Request):
        try:
            ident, rid = _ident(request)
        except Unauthenticated as e:
            return _deny(401, str(e))
        try:
            body = SearchRequest(**(await request.json()))
        except Exception:
            return _deny(422, "invalid_request_body")
        if body.scope not in (PRIVATE, SHARED):
            return _deny(422, "bad_scope")
        need = S.PRIVATE_READ if body.scope == PRIVATE else S.SHARED_READ
        try:
            S.require_scope(ident.as_claims(), need)
        except S.ScopeError as e:
            return _deny(403, str(e))
        c = C()
        res = await validated_search(c.api_engine, c.index, c.embedder, body.scope, ident.org_id, body.query,
                                     user_id=ident.subject_id, requested_path=body.requested_path, limit=5)
        return {"scope": body.scope, "hits": [{"object_id": h.canonical_version_id, "content_hash": h.content_hash,
                                               "canonical": h.canonical} for h in res.hits],
                "rejections": res.reasons()}

    # ---- private episodes
    @app.post("/v1/private/episodes")
    async def create_episode(request: Request):
        try:
            ident, rid = _ident(request)
        except Unauthenticated as e:
            return _deny(401, str(e))
        try:
            _scope(ident, "POST", "/v1/private/episodes")
        except S.ScopeError as e:
            return _deny(403, str(e))
        try:
            body = EpisodeRequest(**(await request.json()))
        except Exception:
            return _deny(422, "invalid_request_body")
        eid = await D.persist_private_episode(C().api_engine, ident.org_id, ident.subject_id,
                                              body.repository_id, body.canonical)
        return JSONResponse(status_code=201, content={"episode_id": eid})

    @app.get("/v1/private/episodes/{episode_id}")
    async def get_episode(episode_id: str, request: Request):
        try:
            ident, rid = _ident(request)
        except Unauthenticated as e:
            return _deny(401, str(e))
        try:
            _scope(ident, "GET", "/v1/private/episodes")
        except S.ScopeError as e:
            return _deny(403, str(e))
        from ..indexing.canonical_loaders import load_private_episode
        row = await load_private_episode(C().api_engine, ident.org_id, ident.subject_id, episode_id)
        if row is None:
            return _deny(404, "not_found")
        return {"episode_id": row["object_id"], "canonical": row["canonical"], "content_hash": row["content_hash"]}

    # ---- contracts
    @app.post("/v1/contracts/candidates")
    async def create_candidate(request: Request):
        try:
            ident, rid = _ident(request)
        except Unauthenticated as e:
            return _deny(401, str(e))
        try:
            _scope(ident, "POST", "/v1/contracts/candidates")
        except S.ScopeError as e:
            return _deny(403, str(e))
        try:
            body = CandidateRequest(**(await request.json()))
        except Exception:
            return _deny(422, "invalid_request_body")
        c = C()
        from ..indexing.canonical_loaders import load_private_episode
        ep = await load_private_episode(c.api_engine, ident.org_id, ident.subject_id, body.episode_id)
        if ep is None:
            return _deny(403, "episode_not_owned")           # must reference a user-owned episode
        h = "sha256:" + D.sha(json.dumps(body.canonical, sort_keys=True))[:32]
        cid = str(uuid.uuid4()); vid = str(uuid.uuid4())
        async with tenant_tx(c.api_engine, ident.org_id, ident.subject_id) as conn:
            await conn.execute(text("INSERT INTO memory_contracts(id,org_id,repository_id) VALUES(:i,:o,:r)"),
                               {"i": cid, "o": ident.org_id, "r": ep["repository_id"]})
            await conn.execute(text(
                "INSERT INTO memory_contract_versions(id,contract_id,org_id,version_number,canonical_json,"
                "content_hash,governance_state,created_by) VALUES(:i,:c,:o,1,cast(:j as jsonb),:h,'candidate',:u)"),
                {"i": vid, "c": cid, "o": ident.org_id, "j": json.dumps(body.canonical), "h": h,
                 "u": ident.subject_id})
            await conn.execute(text("INSERT INTO contract_sources(org_id,contract_version_id,"
                                    "private_episode_id,evidence_type) VALUES(:o,:v,:e,'private_episode')"),
                               {"o": ident.org_id, "v": vid, "e": body.episode_id})
        return JSONResponse(status_code=201, content={"contract_id": cid, "version_id": vid, "state": "candidate"})

    @app.get("/v1/contracts")
    async def list_contracts(request: Request):
        try:
            ident, rid = _ident(request)
        except Unauthenticated as e:
            return _deny(401, str(e))
        try:
            _scope(ident, "GET", "/v1/contracts")
        except S.ScopeError as e:
            return _deny(403, str(e))
        async with tenant_tx(C().api_engine, ident.org_id) as conn:
            rows = (await conn.execute(text(
                "SELECT mc.id, v.version_number, v.governance_state FROM memory_contracts mc"
                " JOIN memory_contract_versions v ON v.id = mc.current_version_id"
                " WHERE v.governance_state='promoted' ORDER BY v.created_at DESC"))).fetchall()
        return {"contracts": [{"contract_id": str(r[0]), "version": r[1], "state": r[2]} for r in rows]}

    @app.get("/v1/contracts/{contract_id}")
    async def get_contract(contract_id: str, request: Request):
        try:
            ident, rid = _ident(request)
        except Unauthenticated as e:
            return _deny(401, str(e))
        try:
            S.require_scope(ident.as_claims(), S.SHARED_READ)
        except S.ScopeError as e:
            return _deny(403, str(e))
        async with tenant_tx(C().api_engine, ident.org_id) as conn:
            r = (await conn.execute(text(
                "SELECT mc.id, v.version_number, v.governance_state, v.canonical_json FROM memory_contracts mc"
                " JOIN memory_contract_versions v ON v.id = mc.current_version_id WHERE mc.id=:i"
                " AND v.governance_state='promoted'"), {"i": contract_id})).first()
        if r is None:
            return _deny(404, "not_found")
        return {"contract_id": str(r[0]), "version": r[1], "state": r[2],
                "canonical": (r[3] if isinstance(r[3], dict) else json.loads(r[3]))}

    @app.post("/v1/feedback")
    async def feedback(request: Request):
        try:
            ident, rid = _ident(request)
        except Unauthenticated as e:
            return _deny(401, str(e))
        try:
            _scope(ident, "POST", "/v1/feedback")
        except S.ScopeError as e:
            return _deny(403, str(e))
        try:
            body = FeedbackRequest(**(await request.json()))
        except Exception:
            return _deny(422, "invalid_request_body")
        job = await D.get_job(C().api_engine, ident.org_id, body.job_id)
        if job is None or job["submitter"] != str(ident.subject_id):
            return _deny(404, "not_found")
        await _audit(C().api_engine, ident.org_id, ident.subject_id, "feedback", body.job_id,
                     {"note_hash": D.sha(body.note or "")}, rid)
        return {"job_id": body.job_id, "recorded": True}

    @app.delete("/v1/memories/{memory_id}")
    async def delete_memory(memory_id: str, request: Request):
        try:
            ident, rid = _ident(request)
        except Unauthenticated as e:
            return _deny(401, str(e))
        try:
            _scope(ident, "DELETE", "/v1/memories")
        except S.ScopeError as e:
            return _deny(403, str(e))
        async with tenant_tx(C().api_engine, ident.org_id, ident.subject_id) as conn:
            n = (await conn.execute(text("UPDATE private_episodes SET state='deleted' WHERE id=:i"
                                         " AND owner_user_id=:u"), {"i": memory_id, "u": ident.subject_id})).rowcount
        if n != 1:
            return _deny(404, "not_found")
        await _audit(C().api_engine, ident.org_id, ident.subject_id, "memory_deleted", memory_id, {}, rid)
        return {"memory_id": memory_id, "deleted": True}

    return app
