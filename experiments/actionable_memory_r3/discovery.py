"""REALBENCH-R3 §12 — representation discovery: arms + oracle-forced seeding on the DISCOVERY split.

12 arms (§12): D0 NO_MEMORY; D1 SHUFFLED_MATCHED (baseline bundle B0); D2..D11 = relevant memory rendered in
bundles B0..B9. The invariant (§8/§11): same target + same evaluator-frozen relevant source ID + different
renderer. Injection reuses the production path — each rendered execution view is stored as a shared
memory_contract_version and force-injected via the retrieval policy `oracle_id` (identical mechanism to R2). The
model only ever sees the rendered view; relevance labels are evaluator-side.

RelevantBundleLift(Bx) = Pass@1(relevant Bx) − Pass@1(shuffled-matched control). Per §12 the shuffled control is
rendered in the plain baseline bundle B0 (a shuffled/irrelevant source is ignored regardless of rendering, so a
common baseline is a faithful, cheaper stand-in for a per-bundle shuffled arm; documented in the report).
"""
from __future__ import annotations
import json
import uuid

from sqlalchemy import text
from enterprise_memory.indexing.projection import build_record
from enterprise_memory.indexing.models import SHARED
from experiments.actionable_memory_r3 import renderers as R
from experiments.actionable_memory_r3.service_adapter import fixture_id
from experiments.actionable_memory_r3.discovery_arms import BUNDLES, ARMS, ARM_BUNDLE, BASELINE_BUNDLE


def _sha32(canonical):
    import hashlib
    return "sha256:" + hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:32]


async def _shared_version(su, org, repo, canonical, chash, conn=None):
    cid, vid = str(uuid.uuid4()), str(uuid.uuid4())

    async def _do(c):
        await c.execute(text("INSERT INTO memory_contracts(id,org_id,repository_id) VALUES(:i,:o,:r)"),
                        {"i": cid, "o": org, "r": repo})
        await c.execute(text("INSERT INTO memory_contract_versions(id,contract_id,org_id,version_number,"
                             "canonical_json,content_hash,governance_state) VALUES(:i,:c,:o,1,cast(:j as jsonb),"
                             ":h,'promoted')"), {"i": vid, "c": cid, "o": org, "j": json.dumps(canonical),
                                                 "h": chash})
        await c.execute(text("UPDATE memory_contracts SET current_version_id=:v WHERE id=:c"),
                        {"v": vid, "c": cid})
    if conn is not None:
        await _do(conn)
    else:
        async with su.begin() as c:
            await _do(c)
    return cid, vid


def render_view(bundle, canon):
    return R.render(bundle, canon)["view"]


async def seed(su, index, embedder, targets, canon_by_src, labels, target_user_of, tgt_users, org,
               experiment_id, ref_trace=None):
    """Seed the discovery arms. canon_by_src: {source_id: canonical dict (fact surface; evidence.solution_code
    optional)}. labels: {tid: {relevant, shuffled}}. ref_trace: {source_id: redacted reference code} for B9.
    Returns arm_targets {arm: [{tid, repo, user, instruction}]}."""
    # org-global bank: version per (source, bundle) rendered view -> version_id
    bank, recs, texts = {}, [], []
    needed = set()
    for t in targets:
        tid = t["_id"] if isinstance(t, dict) else t
        for key in ("relevant", "shuffled"):
            s = labels.get(tid, {}).get(key)
            if s is not None:
                needed.add(s)
    for s in sorted(needed):
        canon = dict(canon_by_src.get(s, {}))
        if ref_trace and s in ref_trace:
            canon.setdefault("evidence", {})["solution_code"] = ref_trace[s]
        for b in BUNDLES:
            view = render_view(b, canon)
            can = {"summary": view, "source_task": s, "kind": "shared_memory", "bundle": b,
                   "provenance_source_user": canon.get("source_user_id")}
            chash = _sha32(can)
            cid, vid = await _shared_version(su, org, None, can, chash)
            bank[(s, b)] = vid
            recs.append(build_record(SHARED, {"contract_id": cid, "object_id": vid, "version_number": 1,
                                              "content_hash": chash, "org_id": org, "canonical": can,
                                              "repository_id": None, "governance_state": "promoted",
                                              "valid_from": None, "valid_until": None}))
            texts.append(view)
    await index.ensure_ready()
    if recs:
        await index.upsert(recs, embedder.embed(texts))

    arm_targets = {a: [] for a in ARMS}
    for arm in ARMS:
        for tinfo in targets:
            tid = tinfo if isinstance(tinfo, str) else tinfo["_id"]
            instr = tinfo["prompt"] if isinstance(tinfo, dict) else ""
            pid = tid.split("_")[1]
            tu = tgt_users[target_user_of[tid]]
            repo = str(uuid.uuid4())
            if arm == "D0":
                rp = {"scopes": [], "max_injected": 0}
            elif arm == "D1":
                src = labels.get(tid, {}).get("shuffled")
                rp = {"scopes": ["shared"], "max_injected": 1, "search_limit": 5,
                      "oracle_id": bank.get((src, BASELINE_BUNDLE))} if src else {"scopes": [], "max_injected": 0}
            else:
                b = ARM_BUNDLE[arm]; src = labels.get(tid, {}).get("relevant")
                rp = {"scopes": ["shared"], "max_injected": 1, "search_limit": 5,
                      "oracle_id": bank.get((src, b))} if src else {"scopes": [], "max_injected": 0}
            async with su.begin() as c:
                await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"),
                                {"i": repo, "o": org, "r": "%s__%s" % (fixture_id(pid), arm)})
                await c.execute(text("INSERT INTO repository_permissions(org_id,repository_id,subject_type,"
                                     "subject_id,can_read,can_modify) VALUES(:o,:r,'user',:u,true,true)"),
                                {"o": org, "r": repo, "u": tu})
                await c.execute(text(
                    "INSERT INTO task_execution_policies(org_id,repository_id,task_key,editable_paths,"
                    "target_symbol,exact_signature,test_bundle_ref,maximum_changed_lines,allowed_refs,version,"
                    "active,target_path,repository_fixture_id,hidden_test_manifest_id,policy_version,"
                    "retrieval_policy,experiment_id,experiment_arm) VALUES(:o,:r,:tk,:ep,'','',:tb,:mcl,"
                    ":refs,1,true,:tp,:fix,:htm,1,cast(:rp as jsonb),:eid,:arm)"),
                    {"o": org, "r": repo, "tk": tid, "ep": ["src/**"], "tb": "DS1000:" + pid, "mcl": 400,
                     "refs": ["refs/heads/main", "main"], "tp": "src/solution.py", "fix": fixture_id(pid),
                     "htm": "DS1000:" + pid, "rp": json.dumps(rp), "eid": experiment_id, "arm": arm})
            arm_targets[arm].append({"tid": tid, "repo": repo, "user": tu, "instruction": instr})
    return {"arm_targets": arm_targets, "bank_size": len(bank)}
