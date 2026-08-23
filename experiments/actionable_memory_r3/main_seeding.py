"""REALBENCH-R3 §17 — confirmatory main / §16 calibration seeding. Reuses the validated discovery injection
mechanism (rendered execution view stored as a shared memory_contract_version, force-injected via oracle_id).

Main arms (§17), SB = discovery-selected bundle:
  M0 NO_MEMORY
  M1 PLAIN_RELEVANT           oracle relevant source, rendered in B0 (plain)
  M2 SELECTED_RELEVANT        oracle SAME relevant source, rendered in SB           <- H1 vs M1, H2 vs M3
  M3 SELECTED_SHUFFLED        oracle shuffled-matched source, rendered in SB
  M4 SELECTED_PRODUCTION_RETR production retrieval (no oracle) over an SB-rendered org bank + abstention
  M5 SELECTED_PRIVATE         target user's OWN verified source (private episode), rendered in SB  (secondary)
  M6 GOLD_SELECTED_RELEVANT   oracle GOLD (reference) source, rendered in SB        (diagnostic upper bound)

Calibration arms (§16): C0 NO_MEMORY, C1 SELECTED_RELEVANT_FIXED (==M2), C2 SELECTED_SHUFFLED (==M3),
C3 SELECTED_PRODUCTION_RETRIEVAL (==M4), C4 PLAIN_RELEVANT_SAME_SOURCE (==M1), C5 GOLD_SELECTED_RELEVANT (==M6).
"""
from __future__ import annotations
import json
import uuid

from sqlalchemy import text
from enterprise_memory.indexing.projection import build_record
from enterprise_memory.indexing.models import PRIVATE, SHARED
from experiments.actionable_memory_r3 import renderers as R
from experiments.actionable_memory_r3.discovery import _shared_version, render_view, _sha32
from experiments.actionable_memory_r3.service_adapter import fixture_id

from experiments.actionable_memory_r3.main_arms import MAIN_ARMS, CALIB_ARMS, CALIB_EQUIV


async def seed(su, index, embedder, targets, canon_by_src, gold_by_src, labels, private_src_of, target_user_of,
               tgt_users, org, experiment_id, selected_bundle, *, arms, ref_trace=None, abstain=None):
    """Seed `arms` (MAIN_ARMS or CALIB_ARMS). Returns arm_targets {arm: [{tid,repo,user,instruction}]}."""
    SB = selected_bundle
    calib = arms and arms[0].startswith("C")
    def map_arm(a):
        return CALIB_EQUIV[a] if calib else a

    # org-global bank: SB-rendered view per source (for M4/C3 production retrieval) + oracle versions we need.
    bank_sb, recs, texts = {}, [], []
    for s in sorted(canon_by_src):
        canon = dict(canon_by_src[s])
        if ref_trace and s in ref_trace:
            canon.setdefault("evidence", {})["solution_code"] = ref_trace[s]
        view = render_view(SB, canon)
        can = {"summary": view, "source_task": s, "kind": "shared_memory", "bundle": SB,
               "provenance_source_user": canon.get("source_user_id")}
        chash = _sha32(can)
        cid, vid = await _shared_version(su, org, None, can, chash)
        bank_sb[s] = vid
        recs.append(build_record(SHARED, {"contract_id": cid, "object_id": vid, "version_number": 1,
                                          "content_hash": chash, "org_id": org, "canonical": can,
                                          "repository_id": None, "governance_state": "promoted",
                                          "valid_from": None, "valid_until": None}))
        texts.append(view)
    await index.ensure_ready()
    if recs:
        await index.upsert(recs, embedder.embed(texts))

    # per (target, needed bundle/source) oracle versions for M1(B0 relevant), M3(SB shuffled), M6(SB gold)
    async def oracle(src, bundle, canon):
        c = dict(canon)
        if ref_trace and src in ref_trace:
            c.setdefault("evidence", {})["solution_code"] = ref_trace[src]
        view = render_view(bundle, c)
        can = {"summary": view, "source_task": src, "kind": "oracle", "bundle": bundle}
        chash = _sha32(can); cid, vid = await _shared_version(su, org, None, can, chash)
        await index.upsert([build_record(SHARED, {"contract_id": cid, "object_id": vid, "version_number": 1,
                            "content_hash": chash, "org_id": org, "canonical": can, "repository_id": None,
                            "governance_state": "promoted", "valid_from": None, "valid_until": None})],
                           embedder.embed([view]))
        return vid

    arm_targets = {a: [] for a in arms}
    for a in arms:
        ma = map_arm(a)
        for t in targets:
            tid = t["_id"] if isinstance(t, dict) else t
            instr = t["prompt"] if isinstance(t, dict) else ""
            pid = tid.split("_")[1]
            tu = tgt_users[target_user_of[tid]]
            rel = labels.get(tid, {}).get("relevant")
            shuf = labels.get(tid, {}).get("shuffled")
            repo = str(uuid.uuid4())
            rp = {"scopes": [], "max_injected": 0}
            priv_vid = None
            async with su.begin() as c:
                await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"),
                                {"i": repo, "o": org, "r": "%s__%s" % (fixture_id(pid), a)})
                await c.execute(text("INSERT INTO repository_permissions(org_id,repository_id,subject_type,"
                                     "subject_id,can_read,can_modify) VALUES(:o,:r,'user',:u,true,true)"),
                                {"o": org, "r": repo, "u": tu})
                if ma == "M1" and rel in canon_by_src:
                    rp = {"scopes": ["shared"], "max_injected": 1, "search_limit": 5,
                          "oracle_id": await oracle(rel, "B0", canon_by_src[rel])}
                elif ma == "M2" and rel in canon_by_src:
                    rp = {"scopes": ["shared"], "max_injected": 1, "search_limit": 5, "oracle_id": bank_sb.get(rel)}
                elif ma == "M3" and shuf in canon_by_src:
                    rp = {"scopes": ["shared"], "max_injected": 1, "search_limit": 5,
                          "oracle_id": await oracle(shuf, SB, canon_by_src[shuf])}
                elif ma == "M4":
                    rp = {"scopes": ["shared"], "max_injected": 1, "search_limit": 5,
                          "abstain": abstain or {"tau_abs": 0.0, "tau_margin": 0.0}}
                elif ma == "M5":
                    psrc = private_src_of.get(tid)
                    if psrc in canon_by_src:
                        view = render_view(SB, canon_by_src[psrc]); can = {"private_note": view,
                            "source_task": psrc, "kind": "own_%s" % SB}
                        eid = str(uuid.uuid4()); chash = _sha32(can)
                        await c.execute(text("INSERT INTO private_episodes(id,org_id,owner_user_id,repository_id,"
                                             "canonical_json,content_hash,state) VALUES(:i,:o,:u,:r,cast(:j as "
                                             "jsonb),:h,'success')"),
                                        {"i": eid, "o": org, "u": tu, "r": repo, "j": json.dumps(can), "h": chash})
                        await index.upsert([build_record(PRIVATE, {"object_id": eid, "content_hash": chash,
                            "org_id": org, "canonical": can, "owner_user_id": tu, "repository_id": repo,
                            "state": "success"})], embedder.embed([view]))
                        rp = {"scopes": ["private"], "max_injected": 1, "search_limit": 1,
                              "abstain": {"tau_abs": 0.0, "tau_margin": 0.0}}
                elif ma == "M6" and rel in gold_by_src:
                    rp = {"scopes": ["shared"], "max_injected": 1, "search_limit": 5,
                          "oracle_id": await oracle(rel, SB, gold_by_src[rel])}
                await c.execute(text(
                    "INSERT INTO task_execution_policies(org_id,repository_id,task_key,editable_paths,"
                    "target_symbol,exact_signature,test_bundle_ref,maximum_changed_lines,allowed_refs,version,"
                    "active,target_path,repository_fixture_id,hidden_test_manifest_id,policy_version,"
                    "retrieval_policy,experiment_id,experiment_arm) VALUES(:o,:r,:tk,:ep,'','',:tb,:mcl,"
                    ":refs,1,true,:tp,:fix,:htm,1,cast(:rp as jsonb),:eid,:arm)"),
                    {"o": org, "r": repo, "tk": tid, "ep": ["src/**"], "tb": "DS1000:" + pid, "mcl": 400,
                     "refs": ["refs/heads/main", "main"], "tp": "src/solution.py", "fix": fixture_id(pid),
                     "htm": "DS1000:" + pid, "rp": json.dumps(rp), "eid": experiment_id, "arm": a})
            arm_targets[a].append({"tid": tid, "repo": repo, "user": tu, "instruction": instr})
    return {"arm_targets": arm_targets, "bank_size": len(bank_sb)}
