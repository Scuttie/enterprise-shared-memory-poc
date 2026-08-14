"""BIGCODE-R2-C discovery seeding (§7). One org; each discovery CELL (format x policy) gets its own user.
Fixed-source cells (P0 relevant / P4 shuffled) seed the assigned VERIFIED source fact rendered in the cell's
format as a per-target private episode (always-inject). Retrieval cells (P1/P2/P3) seed the whole verified
source bank (rendered in the cell format) as a shared bank and let the PRODUCTION embedder retrieve. Memory
is source-only; the target's tests/solution never enter memory. Rendering happens AFTER source selection."""
from __future__ import annotations
import json
import uuid

from sqlalchemy import text
from enterprise_memory.indexing.projection import build_record
from enterprise_memory.indexing.models import PRIVATE, SHARED
from experiments.bigcode_r2 import grader as G, render as R
from experiments.bigcode_r2.adapter import fixture_id

_POLICY = {
    "P0_FIXED_TRUE_RELEVANT": {"scopes": ["private"], "max_injected": 1, "search_limit": 1,
                               "abstain": {"tau_abs": 0.0, "tau_margin": 0.0}},
    "P4_SHUFFLED_MATCHED":     {"scopes": ["private"], "max_injected": 1, "search_limit": 1,
                               "abstain": {"tau_abs": 0.0, "tau_margin": 0.0}},
    "P1_PROD_TOP1":            {"scopes": ["shared"], "max_injected": 1, "search_limit": 1,
                               "abstain": {"tau_abs": 0.30, "tau_margin": 0.0}},
    "P2_PROD_TOP3":            {"scopes": ["shared"], "max_injected": 3, "search_limit": 3,
                               "abstain": {"tau_abs": 0.30, "tau_margin": 0.0}},
    "P3_ALWAYS_TOP1":          {"scopes": ["shared"], "max_injected": 1, "search_limit": 1,
                               "abstain": {"tau_abs": 0.0, "tau_margin": 0.0}},
}


def _sha32(canonical):
    import hashlib
    return "sha256:" + hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:32]


async def _seed_shared_bank(su, index, embedder, org, facts, fmt):
    recs, texts = [], []
    for src, fact in facts.items():
        rendered = R.render(fmt, fact)
        can = {"summary": rendered, "source_task": src, "kind": "shared_memory", "format": fmt}
        cid, vid = str(uuid.uuid4()), str(uuid.uuid4()); chash = _sha32(can)
        async with su.begin() as c:
            await c.execute(text("INSERT INTO memory_contracts(id,org_id,repository_id) VALUES(:i,:o,NULL)"),
                            {"i": cid, "o": org})
            await c.execute(text("INSERT INTO memory_contract_versions(id,contract_id,org_id,version_number,"
                                 "canonical_json,content_hash,governance_state) VALUES(:i,:c,:o,1,"
                                 "cast(:j as jsonb),:h,'promoted')"),
                            {"i": vid, "c": cid, "o": org, "j": json.dumps(can), "h": chash})
            await c.execute(text("UPDATE memory_contracts SET current_version_id=:v WHERE id=:c"),
                            {"v": vid, "c": cid})
        recs.append(build_record(SHARED, {"contract_id": cid, "object_id": vid, "version_number": 1,
                                          "content_hash": chash, "org_id": org, "canonical": can,
                                          "repository_id": None, "governance_state": "promoted",
                                          "valid_from": None, "valid_until": None}))
        texts.append(rendered)
    if recs:
        await index.ensure_ready()
        await index.upsert(recs, embedder.embed(texts))


async def seed_cell(su, index, embedder, org, cell, targets, facts, labels):
    """Seed one discovery cell (format x policy) for all discovery targets. Returns the cell's user + target
    submission descriptors."""
    user = str(uuid.uuid4())
    async with su.begin() as c:
        await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                        {"i": user, "o": org, "s": "u-" + user})
    fmt, pol, kind = cell["format"], cell["policy"], cell["source_kind"]
    if kind == "retrieved":
        await _seed_shared_bank(su, index, embedder, org, facts, fmt)

    out = []
    for t in targets:
        tk = G.task(t); repo = str(uuid.uuid4())
        src = labels["relevant"].get(t) if kind == "relevant" else \
            (labels["shuffled"].get(t) if kind == "shuffled" else None)
        async with su.begin() as c:
            await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"),
                            {"i": repo, "o": org, "r": fixture_id(t)})
            await c.execute(text("INSERT INTO repository_permissions(org_id,repository_id,subject_type,"
                                 "subject_id,can_read,can_modify) VALUES(:o,:r,'user',:u,true,true)"),
                            {"o": org, "r": repo, "u": user})
            if src is not None and src in facts:               # fixed-source cell: seed the assigned source
                rendered = R.render(fmt, facts[src])
                can = {"private_note": rendered, "source_task": src, "kind": "disc_%s" % fmt}
                eid = str(uuid.uuid4()); chash = _sha32(can)
                await c.execute(text("INSERT INTO private_episodes(id,org_id,owner_user_id,repository_id,"
                                     "canonical_json,content_hash,state) VALUES(:i,:o,:u,:r,cast(:j as jsonb),"
                                     ":h,'success')"),
                                {"i": eid, "o": org, "u": user, "r": repo, "j": json.dumps(can), "h": chash})
                await index.upsert([build_record(PRIVATE, {"object_id": eid, "content_hash": chash,
                                                           "org_id": org, "canonical": can,
                                                           "owner_user_id": user, "repository_id": repo,
                                                           "state": "success"})], embedder.embed([rendered]))
                scopes_ok = True
            elif kind == "retrieved":
                scopes_ok = True
            else:
                scopes_ok = False                              # fixed cell but no verified source -> no memory
            rp = dict(_POLICY[pol]) if scopes_ok else {"scopes": [], "max_injected": 0}
            await c.execute(text(
                "INSERT INTO task_execution_policies(org_id,repository_id,task_key,editable_paths,target_symbol,"
                "exact_signature,test_bundle_ref,maximum_changed_lines,allowed_refs,version,active,target_path,"
                "repository_fixture_id,hidden_test_manifest_id,policy_version,retrieval_policy,experiment_id,"
                "experiment_arm) VALUES(:o,:r,:tk,:ep,:sym,:sig,:tb,:mcl,:refs,1,true,:tp,:fix,:htm,1,"
                "cast(:rp as jsonb),:eid,:arm)"),
                {"o": org, "r": repo, "tk": t, "ep": ["src/**"], "sym": tk["entry_point"],
                 "sig": "def %s" % tk["entry_point"], "tb": "BIGCODE:" + t, "mcl": 800,
                 "refs": ["refs/heads/main", "main"], "tp": "src/solution.py", "fix": fixture_id(t),
                 "htm": "BIGCODE:" + t, "rp": json.dumps(rp), "eid": "BIGCODE_R2_DISCOVERY", "arm": cell["code"]})
        out.append({"tid": t, "repo": repo, "assigned_source": src, "instruction": tk["instruct_prompt"]})
    return {"user": user, "cell": cell["code"], "targets": out}
