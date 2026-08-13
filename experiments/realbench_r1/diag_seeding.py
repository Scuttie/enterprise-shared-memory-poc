"""REALBENCH-R1.1 diagnostic seeding (§2). One org+user per arm. Fixed-source arms (D1-D6, D8) seed EXACTLY
the evaluator-assigned source memory per target as a private episode scoped to that target's user+repo, with
the arm's rendering, and a retrieval policy that always injects (tau_abs=0) — guaranteeing the assigned source
is the injected memory. D7 seeds the full 300/150-source shared bank (plain) and lets the PRODUCTION
retriever pick top-1 (threshold off). D0 seeds nothing. Source-only content; target solution/tests never in
memory. Rendering happens AFTER source selection (labels are frozen upstream)."""
from __future__ import annotations
import json
import uuid

from sqlalchemy import text
from enterprise_memory.indexing.projection import build_record
from enterprise_memory.indexing.models import PRIVATE, SHARED
from experiments.realbench_r1 import experiment as X, grader as G, diagnostic as D
from experiments.realbench_r1.adapter import fixture_id
from experiments.realbench_r1.seeding import _sha32

ALWAYS_INJECT = {"max_injected": 1, "search_limit": 1, "abstain": {"tau_abs": 0.0, "tau_margin": 0.0}}


def _rendered(arm, source_tid):
    fact = X.source_fact(source_tid)
    return D.RENDERERS[arm.render](source_tid, fact)


def _assigned_source(arm, tid, labels):
    if arm.source_kind == "relevant":
        return labels["relevant"][tid]
    if arm.source_kind == "shuffled":
        return labels["shuffled"][tid]
    if arm.source_kind == "irrelevant":
        return labels["irrelevant"][tid]
    return None


async def seed_diag_arm(su, index, embedder, arm, labels, split, experiment_id):
    org, user = str(uuid.uuid4()), str(uuid.uuid4())
    async with su.begin() as c:
        await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                        {"i": org, "k": "org-%s-%s" % (arm.code, org)})
        await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                        {"i": user, "o": org, "s": "u-" + user})

    # D7: seed the shared source bank once (plain), retrieved by the production embedder
    if arm.source_kind == "retrieved":
        recs, texts = [], []
        for s in split["source"]:
            can = {"summary": D.render_plain(X.source_fact(s)), "source_task": s, "kind": "shared_summary"}
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
            texts.append(can["summary"])
        if recs:
            await index.ensure_ready()
            await index.upsert(recs, embedder.embed(texts))

    targets = []
    for t in split["main"]:
        tk = G.task(t)
        repo = str(uuid.uuid4())
        src = _assigned_source(arm, t, labels)
        async with su.begin() as c:
            await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"),
                            {"i": repo, "o": org, "r": fixture_id(t)})
            await c.execute(text("INSERT INTO repository_permissions(org_id,repository_id,subject_type,"
                                 "subject_id,can_read,can_modify) VALUES(:o,:r,'user',:u,true,true)"),
                            {"o": org, "r": repo, "u": user})
            if src is not None:                       # fixed-source arm: seed the assigned source, private+scoped
                rendered = _rendered(arm, src)
                can = {"private_note": rendered, "source_task": src, "kind": "diag_%s" % arm.render}
                eid = str(uuid.uuid4()); chash = _sha32(can)
                await c.execute(text("INSERT INTO private_episodes(id,org_id,owner_user_id,repository_id,"
                                     "canonical_json,content_hash,state) VALUES(:i,:o,:u,:r,cast(:j as jsonb),"
                                     ":h,'success')"),
                                {"i": eid, "o": org, "u": user, "r": repo, "j": json.dumps(can), "h": chash})
                await index.upsert([build_record(PRIVATE, {"object_id": eid, "content_hash": chash, "org_id": org,
                                                           "canonical": can, "owner_user_id": user,
                                                           "repository_id": repo, "state": "success"})],
                                   embedder.embed([rendered]))
                scopes = ["private"]
            elif arm.source_kind == "retrieved":
                scopes = ["shared"]
            else:
                scopes = []
            rp = {"scopes": scopes, **ALWAYS_INJECT} if scopes else {"scopes": [], "max_injected": 0}
            await c.execute(text(
                "INSERT INTO task_execution_policies(org_id,repository_id,task_key,editable_paths,target_symbol,"
                "exact_signature,test_bundle_ref,maximum_changed_lines,allowed_refs,version,active,target_path,"
                "repository_fixture_id,hidden_test_manifest_id,policy_version,retrieval_policy,experiment_id,"
                "experiment_arm) VALUES(:o,:r,:tk,:ep,:sym,:sig,:tb,:mcl,:refs,1,true,:tp,:fix,:htm,1,"
                "cast(:rp as jsonb),:eid,:arm)"),
                {"o": org, "r": repo, "tk": t, "ep": ["src/**"], "sym": tk["entry_point"],
                 "sig": "def %s" % tk["entry_point"], "tb": "EVALPLUS:" + t, "mcl": 400,
                 "refs": ["refs/heads/main", "main"], "tp": "src/solution.py", "fix": fixture_id(t),
                 "htm": "EVALPLUS:" + t, "rp": json.dumps(rp), "eid": experiment_id, "arm": arm.code})
        targets.append({"tid": t, "repo": repo, "task_key": t, "assigned_source": src,
                        "instruction": "Complete the function %s in src/solution.py. %s"
                        % (tk["entry_point"], tk["prompt"].strip())})
    return {"org": org, "user": user, "arm": arm.code, "targets": targets}
