"""BIGCODE-R2 confirmatory main/calibration seeding (§5/§10). ONE org, 24 source + 24 target users. Seeds an
org-global shared bank (verified USER_SUCCESS facts, rendered in the SELECTED format) once, then per
(physical arm, target) a repo owned by the target user + a task policy carrying the arm's retrieval policy,
plus per-target memory as required by the arm. Fixed arms (M2/M3/M6/M7) inject a SPECIFIC source via oracle_id;
M4/M5 retrieve from the org-global bank; M1 injects the target user's own prior source; M0 none. Relevance
labels are computed over the VERIFIED sources so every oracle target exists in the bank."""
from __future__ import annotations
import json
import uuid

from sqlalchemy import text
from enterprise_memory.indexing.projection import build_record
from enterprise_memory.indexing.models import PRIVATE, SHARED
from experiments.bigcode_r2 import grader as G, render as R
from experiments.bigcode_r2.adapter import fixture_id
from experiments.bigcode_r2 import main_arms as MA


def _sha32(canonical):
    import hashlib
    return "sha256:" + hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:32]


async def _shared_contract(su, org, repo, canonical, chash):
    cid, vid = str(uuid.uuid4()), str(uuid.uuid4())
    async with su.begin() as c:
        await c.execute(text("INSERT INTO memory_contracts(id,org_id,repository_id) VALUES(:i,:o,:r)"),
                        {"i": cid, "o": org, "r": repo})
        await c.execute(text("INSERT INTO memory_contract_versions(id,contract_id,org_id,version_number,"
                             "canonical_json,content_hash,governance_state) VALUES(:i,:c,:o,1,cast(:j as jsonb),"
                             ":h,'promoted')"), {"i": vid, "c": cid, "o": org, "j": json.dumps(canonical),
                                                 "h": chash})
        await c.execute(text("UPDATE memory_contracts SET current_version_id=:v WHERE id=:c"),
                        {"v": vid, "c": cid})
    return cid, vid


async def _index_shared(index, embedder, org, repo, cid, vid, canonical, chash, text_repr):
    rec = build_record(SHARED, {"contract_id": cid, "object_id": vid, "version_number": 1, "content_hash": chash,
                                "org_id": org, "canonical": canonical, "repository_id": repo,
                                "governance_state": "promoted", "valid_from": None, "valid_until": None})
    await index.ensure_ready()
    await index.upsert([rec], embedder.embed([text_repr]))


async def seed(su, index, embedder, targets, facts, labels, assignment, selected_format, experiment_id):
    org = str(uuid.uuid4())
    src_users = [str(uuid.uuid4()) for _ in range(assignment["n_source_users"])]
    tgt_users = [str(uuid.uuid4()) for _ in range(assignment["n_target_users"])]
    async with su.begin() as c:
        await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                        {"i": org, "k": "org-bcb-main-%s" % org})
        for u in src_users + tgt_users:
            await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                            {"i": u, "o": org, "s": "u-" + u})

    # org-global bank (repo NULL) in the SELECTED format: {source_task: version_id}
    bank_vid, recs, texts = {}, [], []
    for s in sorted(facts.keys()):
        rendered = R.render(selected_format, facts[s])
        can = {"summary": rendered, "source_task": s, "kind": "shared_memory", "format": selected_format,
               "provenance_source_user": facts[s].get("owner_user")}
        chash = _sha32(can)
        cid, vid = await _shared_contract(su, org, None, can, chash)
        bank_vid[s] = vid
        recs.append(build_record(SHARED, {"contract_id": cid, "object_id": vid, "version_number": 1,
                                          "content_hash": chash, "org_id": org, "canonical": can,
                                          "repository_id": None, "governance_state": "promoted",
                                          "valid_from": None, "valid_until": None}))
        texts.append(rendered)
    await index.ensure_ready()
    await index.upsert(recs, embedder.embed(texts))

    physical = MA.physical_arms(selected_format)
    arm_targets = {a["code"]: [] for a in physical}
    for arm in physical:
        for t in targets:
            tk = G.task(t); repo = str(uuid.uuid4())
            tu = tgt_users[assignment["target_of"][t]]
            rp = {"scopes": [], "max_injected": 0}
            async with su.begin() as c:
                # external_repo_id unique per (arm, task); worker resolves task from policy repository_fixture_id
                await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"),
                                {"i": repo, "o": org, "r": "%s__%s" % (fixture_id(t), arm["code"])})
                await c.execute(text("INSERT INTO repository_permissions(org_id,repository_id,subject_type,"
                                     "subject_id,can_read,can_modify) VALUES(:o,:r,'user',:u,true,true)"),
                                {"o": org, "r": repo, "u": tu})
                sk, fmt = arm["source_kind"], arm["format"]
                if arm["scope"] == "private" and sk == "own":                 # M1: target's own prior source
                    src = assignment["private_source_of"][t]
                    if src in facts:
                        rendered = R.render(fmt, facts[src]); can = {"private_note": rendered,
                            "source_task": src, "kind": "own_%s" % fmt}
                        eid = str(uuid.uuid4()); chash = _sha32(can)
                        await c.execute(text("INSERT INTO private_episodes(id,org_id,owner_user_id,"
                                             "repository_id,canonical_json,content_hash,state) VALUES(:i,:o,:u,"
                                             ":r,cast(:j as jsonb),:h,'success')"),
                                        {"i": eid, "o": org, "u": tu, "r": repo, "j": json.dumps(can), "h": chash})
                        await index.upsert([build_record(PRIVATE, {"object_id": eid, "content_hash": chash,
                            "org_id": org, "canonical": can, "owner_user_id": tu, "repository_id": repo,
                            "state": "success"})], embedder.embed([rendered]))
                        rp = {"scopes": ["private"], "max_injected": 1, "search_limit": 1,
                              "abstain": {"tau_abs": 0.0, "tau_margin": 0.0}}
                elif arm["scope"] == "shared_oracle":                          # M2/M3: oracle over org bank
                    src = labels["relevant"][t] if sk == "relevant" else labels["shuffled"][t]
                    rp = {"scopes": ["shared"], "max_injected": 1, "search_limit": 5,
                          "oracle_id": bank_vid.get(src)}
                elif arm["scope"] == "shared_retrieval":                       # M4/M5: production retrieval
                    rp = {"scopes": ["shared"], "max_injected": 1, "search_limit": 5, "abstain": arm["abstain"]}
                elif arm["scope"] == "shared_repo_oracle":                     # M6/M7: same source, plain/gov
                    src = labels["relevant"][t]
                    rendered = R.render(fmt, facts[src]); can = {"summary": rendered, "source_task": src,
                        "kind": "sharedrepo_%s" % fmt, "provenance_source_user": facts[src].get("owner_user")}
                    chash = _sha32(can); cid, vid = await _shared_contract(su, org, repo, can, chash)
                    await _index_shared(index, embedder, org, repo, cid, vid, can, chash, rendered)
                    rp = {"scopes": ["shared"], "max_injected": 1, "search_limit": 5, "oracle_id": vid}
                await c.execute(text(
                    "INSERT INTO task_execution_policies(org_id,repository_id,task_key,editable_paths,"
                    "target_symbol,exact_signature,test_bundle_ref,maximum_changed_lines,allowed_refs,version,"
                    "active,target_path,repository_fixture_id,hidden_test_manifest_id,policy_version,"
                    "retrieval_policy,experiment_id,experiment_arm) VALUES(:o,:r,:tk,:ep,:sym,:sig,:tb,:mcl,"
                    ":refs,1,true,:tp,:fix,:htm,1,cast(:rp as jsonb),:eid,:arm)"),
                    {"o": org, "r": repo, "tk": t, "ep": ["src/**"], "sym": tk["entry_point"],
                     "sig": "def %s" % tk["entry_point"], "tb": "BIGCODE:" + t, "mcl": 800,
                     "refs": ["refs/heads/main", "main"], "tp": "src/solution.py", "fix": fixture_id(t),
                     "htm": "BIGCODE:" + t, "rp": json.dumps(rp), "eid": experiment_id, "arm": arm["code"]})
            arm_targets[arm["code"]].append({"tid": t, "repo": repo, "user": tu,
                                             "instruction": tk["instruct_prompt"]})
    return {"org": org, "src_users": src_users, "tgt_users": tgt_users, "arm_targets": arm_targets,
            "bank_size": len(bank_vid)}
