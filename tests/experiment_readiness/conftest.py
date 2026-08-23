"""P5.1 experiment-readiness harness (§17). Drives the worker/finaliser primitives directly against REAL
PostgreSQL + Qdrant (+ MinIO if configured) — no API/worker HTTP process. Credential-free. Skipped unless
DATABASE_URL is set (ci-experiment-readiness only)."""
import os
import sys
import json
import uuid
import asyncio
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from sqlalchemy import text                                                # noqa: E402
from enterprise_memory.persistence.database import make_engine             # noqa: E402
from enterprise_memory.service.p5deps import OfflineRepositoryProvider     # noqa: E402

DIM = int(os.environ.get("INDEX_DIM", "64"))


def _require():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("experiment-readiness requires DATABASE_URL (ci-experiment-readiness only)")


@pytest.fixture(autouse=True)
def _guard():
    _require()


def run(coro):
    return asyncio.run(coro)


def su():
    return make_engine("postgres", "postgres")


def worker_engine():
    return make_engine("worker_service", "worker_pw")


async def _mk_org_user_repo(c, *, with_read=True, with_modify=True):
    org, user, repo = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                    {"i": org, "k": "org-er-%s" % org})
    await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                    {"i": user, "o": org, "s": "u-" + str(user)})
    await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"),
                    {"i": repo, "o": org, "r": "repo-er"})
    if with_read or with_modify:
        await c.execute(text(
            "INSERT INTO repository_permissions(org_id,repository_id,subject_type,subject_id,can_read,"
            "can_modify) VALUES(:o,:r,'user',:u,:cr,:cm)"),
            {"o": org, "r": repo, "u": user, "cr": with_read, "cm": with_modify})
    await c.execute(text(
        "INSERT INTO task_execution_policies(org_id,repository_id,task_key,editable_paths,target_symbol,"
        "exact_signature,test_bundle_ref,maximum_changed_lines,allowed_refs,version,active) VALUES"
        "(:o,:r,'fix-return',:ep,'f','def f()','tests/test_app.py',12,:refs,1,true)"),
        {"o": org, "r": repo, "ep": ["src/**"], "refs": ["refs/heads/main", "main"]})
    return str(org), str(user), str(repo)


async def _seed(**kw):
    e = su()
    async with e.begin() as c:
        org, user, repo = await _mk_org_user_repo(c, **kw)
    await e.dispose()
    return {"org": org, "user": user, "repo": repo}


@pytest.fixture
def seed():
    return lambda **kw: run(_seed(**kw))


def spec_for(repo):
    rp = OfflineRepositoryProvider()
    commit = rp.resolve_commit(repo, "refs/heads/main")
    tree = rp.resolve_tree(commit)
    return {"repository_id": repo, "task_id": "fix-return", "instruction": "make f return 1",
            "desired_ref": "refs/heads/main", "commit_sha": commit, "tree_sha": tree,
            "target_path": "src/app.py", "editable_paths": ["src/**"], "target_symbol": "f",
            "exact_signature": "def f()", "maximum_changed_lines": 12}


async def plant_job(s, *, worker="wX", cancel=False, live=True, state="RETRIEVING"):
    """Insert a claimed job (RETRIEVING) owned by `worker` with a live/expired lease and optional cancel."""
    org, user, repo = s["org"], s["user"], s["repo"]
    spec = spec_for(repo)
    jid = str(uuid.uuid4())
    lease_sql = "now()+interval '5 minutes'" if live else "now()-interval '1 hour'"
    cancel_sql = "now()" if cancel else "NULL"
    e = su()
    async with e.begin() as c:
        await c.execute(text(
            "INSERT INTO solve_jobs(id,org_id,submitter_user_id,repository_id,logical_request_id,"
            "idempotency_key,state,spec_json,attempts,max_attempts,lease_owner,lease_expires_at,heartbeat_at,"
            "cancel_requested_at,requested_ref,resolved_commit_sha,resolved_tree_sha,backend_type) VALUES"
            "(:i,:o,:u,:r,:lrq,:k,:st,cast(:s as jsonb),1,3,:w,%s,now(),%s,:ref,:cs,:ts,'fake')"
            % (lease_sql, cancel_sql)),
            {"i": jid, "o": org, "u": user, "r": repo, "lrq": "er-%s" % jid, "k": "er-%s" % jid, "st": state,
             "s": json.dumps(spec), "w": worker, "ref": "refs/heads/main", "cs": spec["commit_sha"],
             "ts": spec["tree_sha"]})
        await c.execute(text("INSERT INTO solve_attempts(org_id,job_id,attempt_number,worker_id,state)"
                             " VALUES(:o,:j,1,:w,'RETRIEVING')"), {"o": org, "j": jid, "w": worker})
    await e.dispose()
    ev = {"job_id": jid, "org_id": org, "submitter": user, "task_policy_id": None, "spec_json": spec,
          "attempt": 1}
    return jid, ev


async def seed_evidence(jid, org, user):
    """Seed the durable evidence a SUCCEEDED job requires: a model call, >=5 AVAILABLE artifacts, a retrieved
    job_event. (No terminal outcome/episode/candidate — the finaliser writes those.)"""
    classes = ["repository_snapshot", "sanitized_model_request", "sanitized_model_response", "parsed_patch",
               "applied_patch", "sandbox_result"]
    e = su()
    async with e.begin() as c:
        await c.execute(text("INSERT INTO model_calls(org_id,job_id,logical_request_id,backend_type,"
                             "final_status,attempts) VALUES(:o,:j,:l,'fake','success',1)"),
                        {"o": org, "j": jid, "l": "mc-%s" % jid})
        await c.execute(text("INSERT INTO job_events(org_id,job_id,seq,state,event_type)"
                             " VALUES(:o,:j,5,'GENERATING','retrieved') ON CONFLICT DO NOTHING"),
                        {"o": org, "j": jid})
        for i, cls in enumerate(classes):
            await c.execute(text("INSERT INTO artifacts(org_id,job_id,kind,object_key,deletion_state,"
                                 "artifact_class) VALUES(:o,:j,:k,:ok,'AVAILABLE',:cls)"),
                            {"o": org, "j": jid, "k": cls, "ok": "k/%s/%d" % (jid, i), "cls": cls})
    await e.dispose()


async def add_user(org):
    uid = str(uuid.uuid4())
    e = su()
    async with e.begin() as c:
        await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                        {"i": uid, "o": org, "s": "u-" + uid})
    await e.dispose()
    return uid


async def grant_repo_read(org, repo, user):
    e = su()
    async with e.begin() as c:
        await c.execute(text("INSERT INTO repository_permissions(org_id,repository_id,subject_type,subject_id,"
                             "can_read,can_modify) VALUES(:o,:r,'user',:u,true,false)"),
                        {"o": org, "r": repo, "u": user})
    await e.dispose()


async def seed_private_episode(org, owner, repo, note, *, index_owner=None):
    """Insert a private episode owned by `owner` and index a PRIVATE record. `index_owner` (if given) tampers
    the index payload's claimed owner (adversarial cross-user candidate)."""
    from enterprise_memory.indexing.qdrant_indexes import QdrantIndex
    from enterprise_memory.indexing.embeddings import DeterministicTestEmbedder
    from enterprise_memory.indexing.projection import build_record
    from enterprise_memory.indexing.models import PRIVATE
    import hashlib
    eid = str(uuid.uuid4())
    canonical = {"private_note": note, "task_id": "fix-return", "repo_id": repo}
    chash = "sha256:" + hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:32]
    e = su()
    async with e.begin() as c:
        await c.execute(text(
            "INSERT INTO private_episodes(id,org_id,owner_user_id,repository_id,canonical_json,content_hash,"
            "state) VALUES(:i,:o,:u,:r,cast(:j as jsonb),:h,'success')"),
            {"i": eid, "o": org, "u": owner, "r": repo, "j": json.dumps(canonical), "h": chash})
    await e.dispose()
    row = {"object_id": eid, "content_hash": chash, "org_id": org, "canonical": canonical,
           "owner_user_id": str(index_owner or owner), "repository_id": repo, "state": "success"}
    idx = QdrantIndex.from_env(DIM); await idx.ensure_ready()
    emb = DeterministicTestEmbedder(DIM)
    rec = build_record(PRIVATE, row)
    await idx.upsert([rec], emb.embed([rec.text]))
    await idx.close()
    return eid


async def seed_shared_contract(org, repo):
    """Index a promoted shared contract so a shared view is available to inject (mirrors the e2e seed)."""
    from enterprise_memory.contracts import codec, schema as SS
    from enterprise_memory.indexing.qdrant_indexes import QdrantIndex
    from enterprise_memory.indexing.embeddings import DeterministicTestEmbedder
    from enterprise_memory.indexing.projection import build_record
    from enterprise_memory.indexing.models import SHARED
    cid, vid = str(uuid.uuid4()), str(uuid.uuid4())
    c = SS.MemoryContract(
        contract_id=cid, schema_version=SS.SCHEMA_VERSION, title="Return one",
        canonical_summary="make f return 1 with a governed fix",
        scope=SS.ContractScope(org_id=str(org), team_ids=[], repo_ids=[str(repo)], path_globs=[],
                               language="python", framework="none", dependency_version_constraints={},
                               branch_or_release_constraints=["main"], error_signatures=["E_RET"],
                               applies_when=["f returns 0"], does_not_apply_when=["unrelated"]),
        action=SS.ContractAction(ordered_steps=["change return to 1"], code_pattern="return 1",
                                 forbidden_patterns=[], required_inputs=[], operation_order=[]),
        validity=SS.ContractValidity(valid_from="2020-01-01", valid_until="", environment_constraints={},
                                     version_constraints={}, invalidation_events=[], supersedes_contract_ids=[],
                                     superseded_by_contract_id=""),
        verification=SS.ContractVerification(test_commands=["pytest"], expected_observations=["pass"],
                                             regression_checks=["noreg"], failure_observations=["fail"]),
        provenance=SS.ContractProvenance(source_episode_ids=["ep0"], contributor_user_ids_pseudonymized=["u0"],
                                         source_commit_shas=["sha0"], source_test_results=["r0"],
                                         extractor_version="x/1"),
        evidence=SS.ContractEvidence(),
        governance=SS.ContractGovernance(state="promoted", visibility="shared")).stamp()
    canonical = codec.encode_memory_contract(c)
    e = su()
    async with e.begin() as conn:
        await conn.execute(text("INSERT INTO memory_contracts(id,org_id,repository_id) VALUES(:i,:o,:r)"),
                           {"i": cid, "o": org, "r": repo})
        await conn.execute(text(
            "INSERT INTO memory_contract_versions(id,contract_id,org_id,version_number,canonical_json,"
            "content_hash,governance_state) VALUES(:i,:c,:o,1,cast(:j as jsonb),:h,'promoted')"),
            {"i": vid, "c": cid, "o": org, "j": json.dumps(canonical), "h": c.content_hash})
        await conn.execute(text("UPDATE memory_contracts SET current_version_id=:v WHERE id=:c"),
                           {"v": vid, "c": cid})
    await e.dispose()
    idx = QdrantIndex.from_env(DIM); await idx.ensure_ready()
    emb = DeterministicTestEmbedder(DIM)
    row = {"contract_id": cid, "object_id": vid, "version_number": 1, "content_hash": c.content_hash,
           "org_id": org, "canonical": canonical, "repository_id": repo, "governance_state": "promoted",
           "valid_from": None, "valid_until": None}
    rec = build_record(SHARED, row)
    await idx.upsert([rec], emb.embed([rec.text]))
    await idx.close()
    return vid


async def steal_lease(jid, new_owner):
    e = su()
    async with e.begin() as c:
        await c.execute(text("UPDATE solve_jobs SET lease_owner=:w, lease_expires_at=now()+interval '5 minutes'"
                             " WHERE id=:i"), {"w": new_owner, "i": jid})
    await e.dispose()


async def retrieval_rows(jid):
    e = su()
    async with e.connect() as c:
        rows = (await c.execute(text(
            "SELECT scope, accepted, injected, rejection_reason, index_owner_id, canonical_owner_id,"
            " injected_view_hash, injected_position FROM retrieval_candidates WHERE job_id=:j"),
            {"j": jid})).fetchall()
    await e.dispose()
    return [{"scope": r[0], "accepted": r[1], "injected": r[2], "rejection_reason": r[3],
             "index_owner": (str(r[4]) if r[4] else None), "canonical_owner": (str(r[5]) if r[5] else None),
             "injected_view_hash": r[6], "injected_position": r[7]} for r in rows]


async def job_state(jid):
    e = su()
    async with e.connect() as c:
        st = (await c.execute(text("SELECT state FROM solve_jobs WHERE id=:i"), {"i": jid})).scalar()
        oc = (await c.execute(text("SELECT count(*) FROM outcome_observations WHERE job_id=:j"), {"j": jid})).scalar()
        pe = (await c.execute(text("SELECT count(*) FROM private_episodes WHERE org_id=(SELECT org_id FROM solve_jobs WHERE id=:i)"
                                   " AND canonical_json->>'task_id' IS NOT NULL AND repository_id IS NOT NULL"), {"i": jid})).scalar()
        cand = (await c.execute(text("SELECT count(*) FROM outbox_events WHERE event_type='CONTRACT_CANDIDATE'"
                                     " AND payload_json->>'job_id'=:j"), {"j": jid})).scalar()
        aud = (await c.execute(text("SELECT count(*) FROM audit_events WHERE event_type='solve_succeeded'"
                                    " AND subject_id=:j"), {"j": jid})).scalar()
        ev_terminal = (await c.execute(text("SELECT count(*) FROM job_events WHERE job_id=:j AND state IN"
                                            " ('SUCCEEDED','FAILED','CANCELLED')"), {"j": jid})).scalar()
    await e.dispose()
    return {"state": st, "outcome": oc, "episode": pe, "candidate": cand, "audit": aud,
            "terminal_events": ev_terminal}
