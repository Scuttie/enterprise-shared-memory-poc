"""REALBENCH-R1 seeding (§7/§8). Per ARM, one org holds a SHARED bank of the 150 verified source memories
(rendered per arm) plus one repository + server-owned policy per target task (carrying the arm's retrieval
policy + the official grader marker). R1 (private) additionally seeds, per target, the target user's own
assigned source memory. R0 seeds no memory. Targets in an arm search the same shared bank (not a per-cell
singleton). Source memories are org-global (repository_id NULL) so they are readable by the target user."""
from __future__ import annotations
import json
import uuid

from sqlalchemy import text
from enterprise_memory.contracts import schema as SS, codec
from enterprise_memory.indexing.projection import build_record
from enterprise_memory.indexing.models import PRIVATE, SHARED
from experiments.realbench_r1 import experiment as X, arms as A
from experiments.realbench_r1.adapter import fixture_id


def _governed_contract(org, fact):
    c = SS.MemoryContract(
        contract_id=str(uuid.uuid4()), schema_version=SS.SCHEMA_VERSION,
        title="reusable lesson %s" % fact["source_task"], canonical_summary=X.governed_summary(fact),
        scope=SS.ContractScope(org_id=str(org), team_ids=[], repo_ids=[], path_globs=[], language="python",
                               framework="none", dependency_version_constraints={},
                               branch_or_release_constraints=[], error_signatures=[fact["entry_point"]],
                               applies_when=[fact["tokens"]], does_not_apply_when=["an unrelated problem"]),
        action=SS.ContractAction(ordered_steps=[fact["approach"]], code_pattern="approach", forbidden_patterns=[],
                                 required_inputs=[], operation_order=[]),
        validity=SS.ContractValidity(valid_from="2020-01-01", valid_until="", environment_constraints={},
                                     version_constraints={}, invalidation_events=[], supersedes_contract_ids=[],
                                     superseded_by_contract_id=""),
        verification=SS.ContractVerification(test_commands=["pytest"], expected_observations=["pass"],
                                             regression_checks=["noreg"], failure_observations=["fail"]),
        provenance=SS.ContractProvenance(source_episode_ids=[fact["source_task"]],
                                         contributor_user_ids_pseudonymized=["u0"], source_commit_shas=["s0"],
                                         source_test_results=["pass"], extractor_version="realbench/1"),
        evidence=SS.ContractEvidence(), governance=SS.ContractGovernance(state="promoted", visibility="shared")
    ).stamp()
    return c


def _sha32(canonical):
    import hashlib
    return "sha256:" + hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:32]


async def _index_shared(su, org, canonical, records, chash):
    cid, vid = str(uuid.uuid4()), str(uuid.uuid4())
    async with su.begin() as c:
        await c.execute(text("INSERT INTO memory_contracts(id,org_id,repository_id) VALUES(:i,:o,NULL)"),
                        {"i": cid, "o": org})
        await c.execute(text("INSERT INTO memory_contract_versions(id,contract_id,org_id,version_number,"
                             "canonical_json,content_hash,governance_state) VALUES(:i,:c,:o,1,cast(:j as jsonb),"
                             ":h,'promoted')"),
                        {"i": vid, "c": cid, "o": org, "j": json.dumps(canonical), "h": chash})
        await c.execute(text("UPDATE memory_contracts SET current_version_id=:v WHERE id=:c"), {"v": vid, "c": cid})
    row = {"contract_id": cid, "object_id": vid, "version_number": 1, "content_hash": chash, "org_id": org,
           "canonical": canonical, "repository_id": None, "governance_state": "promoted",
           "valid_from": None, "valid_until": None}
    records.append(build_record(SHARED, row))
    return vid


async def seed_arm(su, index, embedder, arm, target_tids, split, experiment_id):
    org, user = str(uuid.uuid4()), str(uuid.uuid4())
    facts = {t: X.source_fact(t) for t in split["source"]}
    async with su.begin() as c:
        await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                        {"i": org, "k": "org-%s-%s" % (arm.code, org)})
        await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                        {"i": user, "o": org, "s": "u-" + user})

    records = []
    if arm.memory_form in ("shared_ungoverned", "shared_governed"):
        for t, f in facts.items():
            if arm.memory_form == "shared_governed":
                ct = _governed_contract(org, f); await _index_shared(su, org, codec.encode_memory_contract(ct),
                                                                     records, ct.content_hash)
            else:
                can = {"summary": X.ungoverned_text(f), "source_task": t, "kind": "shared_summary"}
                await _index_shared(su, org, can, records, _sha32(can))
    if records:
        await index.ensure_ready()
        await index.upsert(records, embedder.embed([r.text for r in records]))

    targets = []
    for t in target_tids:
        tk = G_task(t)
        repo = str(uuid.uuid4())
        async with su.begin() as c:
            await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"),
                            {"i": repo, "o": org, "r": fixture_id(t)})
            await c.execute(text("INSERT INTO repository_permissions(org_id,repository_id,subject_type,"
                                 "subject_id,can_read,can_modify) VALUES(:o,:r,'user',:u,true,true)"),
                            {"o": org, "r": repo, "u": user})
            # R1 private: seed the target user's own assigned source memory (the most token-similar source)
            if arm.memory_form == "private":
                pf = facts[_nearest_source(embedder, tk, facts)]
                can = {"private_note": X.ungoverned_text(pf), "source_task": pf["source_task"],
                       "kind": "private_lesson"}
                eid = str(uuid.uuid4()); chash = _sha32(can)
                await c.execute(text("INSERT INTO private_episodes(id,org_id,owner_user_id,repository_id,"
                                     "canonical_json,content_hash,state) VALUES(:i,:o,:u,:r,cast(:j as jsonb),"
                                     ":h,'success')"),
                                {"i": eid, "o": org, "u": user, "r": repo, "j": json.dumps(can), "h": chash})
                prow = {"object_id": eid, "content_hash": chash, "org_id": org, "canonical": can,
                        "owner_user_id": user, "repository_id": repo, "state": "success"}
                await index.upsert([build_record(PRIVATE, prow)], embedder.embed([X.ungoverned_text(pf)]))
            rp = dict(arm.retrieval_policy)
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
        targets.append({"tid": t, "repo": repo, "task_key": t,
                        "instruction": _instruction(tk)})
    return {"org": org, "user": user, "arm": arm.code, "targets": targets}


def G_task(tid):
    from experiments.realbench_r1 import grader as G
    return G.task(tid)


def _instruction(tk):
    return "Complete the function %s in src/solution.py. %s" % (tk["entry_point"], tk["prompt"].strip())


def _nearest_source(embedder, tk, facts):
    q = embedder.embed([tk["prompt"] + " " + tk["entry_point"]])[0]
    best, bs = None, -9
    texts = {t: X.ungoverned_text(f) for t, f in facts.items()}
    vs = embedder.embed(list(texts.values()))
    for (t, _), v in zip(texts.items(), vs):
        s = sum(a * b for a, b in zip(q, v))
        if s > bs:
            bs, best = s, t
    return best
