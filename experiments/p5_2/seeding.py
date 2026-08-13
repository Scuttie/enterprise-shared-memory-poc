"""P5.2 per-cell seeding (§5). Each cell runs in its own org but the org holds a COMPETITIVE shared bank (a
relevant memory when the arm has one + 3 same-domain near-miss + 4 cross-technique irrelevant decoys), so the
frozen abstention rule actually decides inject-vs-abstain. S1 seeds only decoys (relevant absent); S2/S3 seed
the relevant memory but expired / out-of-scope so a validity/scope gate rejects it before injection; S4 seeds
a relevant-looking memory carrying a WRONG edge multiplier (adoption diagnostic). M4 records the relevant
canonical version id as the oracle target."""
from __future__ import annotations
import json
import uuid
from datetime import datetime

from sqlalchemy import text
from enterprise_memory.indexing.projection import build_record
from enterprise_memory.indexing.models import PRIVATE, SHARED
from experiments.p5_2 import memory_bank as MB, tokens as T

_USER_NS = uuid.UUID("5a4b3c2d-1e0f-4a9b-8c7d-6e5f4a3b2c1d")


def _sha32(canonical):
    import hashlib
    return "sha256:" + hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:32]


async def _perm(c, org, repo, user, can_modify):
    await c.execute(text("INSERT INTO repository_permissions(org_id,repository_id,subject_type,subject_id,"
                         "can_read,can_modify) VALUES(:o,:r,'user',:u,true,:cm)"),
                    {"o": org, "r": repo, "u": user, "cm": can_modify})


async def _index_shared(su, org, repo, canonical, records, *, chash=None, valid_from=None, valid_until=None):
    cid, vid = str(uuid.uuid4()), str(uuid.uuid4())
    chash = chash or _sha32(canonical)
    async with su.begin() as c:
        await c.execute(text("INSERT INTO memory_contracts(id,org_id,repository_id) VALUES(:i,:o,:r)"),
                        {"i": cid, "o": org, "r": repo})
        await c.execute(text("INSERT INTO memory_contract_versions(id,contract_id,org_id,version_number,"
                             "canonical_json,content_hash,governance_state,valid_from,valid_until) VALUES"
                             "(:i,:c,:o,1,cast(:j as jsonb),:h,'promoted',cast(:vf as timestamptz),"
                             "cast(:vu as timestamptz))"),
                        {"i": vid, "c": cid, "o": org, "j": json.dumps(canonical), "h": chash,
                         "vf": valid_from, "vu": valid_until})
        await c.execute(text("UPDATE memory_contracts SET current_version_id=:v WHERE id=:c"), {"v": vid, "c": cid})
    row = {"contract_id": cid, "object_id": vid, "version_number": 1, "content_hash": chash, "org_id": org,
           "canonical": canonical, "repository_id": repo, "governance_state": "promoted",
           "valid_from": valid_from, "valid_until": valid_until}
    records.append(build_record(SHARED, row))
    return vid


async def seed_cell(su, index, embedder, cell, family, dim):
    org, repo = str(uuid.uuid4()), str(uuid.uuid4())
    lt, ls = cell["target_user"], cell["source_user"]
    target_user = str(uuid.uuid5(_USER_NS, org + "|t"))
    source_user = None if ls is None else (target_user if ls == lt else str(uuid.uuid5(_USER_NS, org + "|s")))
    exp_id = cell["cell_id"].rsplit("|", 2)[0]
    form = cell["memory_form"]
    arm = cell["arm"]
    async with su.begin() as c:
        await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                        {"i": org, "k": "org-%s-%s" % (cell["cell_id"], org)})
        await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                        {"i": target_user, "o": org, "s": "u-" + target_user})
        if source_user and source_user != target_user:
            await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                            {"i": source_user, "o": org, "s": "u-" + source_user})
        await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"),
                        {"i": repo, "o": org, "r": cell["target_repo"]})
        await _perm(c, org, repo, target_user, True)
        if source_user and source_user != target_user:
            await _perm(c, org, repo, source_user, False)

    records = []
    oracle_id = None
    private_ct = 0
    if form == "private":
        canonical = MB.private_canonical(family, repo)
        eid = str(uuid.uuid4()); chash = _sha32(canonical)
        async with su.begin() as c:
            await c.execute(text("INSERT INTO private_episodes(id,org_id,owner_user_id,repository_id,"
                                 "canonical_json,content_hash,state) VALUES(:i,:o,:u,:r,cast(:j as jsonb),:h,"
                                 "'success')"),
                            {"i": eid, "o": org, "u": target_user, "r": repo, "j": json.dumps(canonical),
                             "h": chash})
        prow = {"object_id": eid, "content_hash": chash, "org_id": org, "canonical": canonical,
                "owner_user_id": target_user, "repository_id": repo, "state": "success"}
        records.append(build_record(PRIVATE, prow)); private_ct = 1
    elif form != "none":
        # a competitive SHARED bank
        if form == "shared_ungoverned":
            oracle_id = await _index_shared(su, org, repo, MB.ungoverned_canonical(family), records)
        elif form in ("shared_governed", "governed_wrong", "governed_out_of_scope"):
            ct, _K = MB.governed_relevant(org, repo, family, form=form)
            oracle_id = await _index_shared(su, org, repo, MB.canonical_of(ct), records, chash=ct.content_hash)
        elif form == "governed_expired":
            ct, _K = MB.governed_relevant(org, repo, family, form="shared_governed")
            oracle_id = await _index_shared(su, org, repo, MB.canonical_of(ct), records, chash=ct.content_hash,
                                            valid_from=datetime.strptime(MB._PAST_FROM, "%Y-%m-%d"),
                                            valid_until=datetime.strptime(MB._PAST_UNTIL, "%Y-%m-%d"))
        # decoys: relevant_absent (S1) has none relevant above -> add 4 near-miss + 4 irrelevant; others 3+4
        n_near = 4 if form == "relevant_absent" else 3
        for k in range(n_near):
            tag = "technique_%s_decoy_%d" % (family.domain, k)
            await _index_shared(su, org, repo, MB.canonical_of(MB.decoy_contract(org, repo, family.domain, tag)),
                                records, chash=MB.decoy_contract(org, repo, family.domain, tag).content_hash)
        other_domains = [d for d in T.DOMAINS if d != family.domain]
        for k in range(4):
            od = other_domains[k % len(other_domains)]
            tag = "technique_%s_irr_%d" % (od, k)
            dc = MB.decoy_contract(org, repo, od, tag)
            await _index_shared(su, org, repo, MB.canonical_of(dc), records, chash=dc.content_hash)

    if records:
        await index.ensure_ready()
        await index.upsert(records, embedder.embed([r.text for r in records]))

    # policy carries the server-assigned arm + retrieval policy (oracle id filled for M4)
    rpol = dict(cell["retrieval_policy"])
    if rpol.get("oracle") and oracle_id:
        rpol["oracle_id"] = oracle_id
    async with su.begin() as c:
        await c.execute(text(
            "INSERT INTO task_execution_policies(org_id,repository_id,task_key,editable_paths,target_symbol,"
            "exact_signature,test_bundle_ref,maximum_changed_lines,allowed_refs,version,active,target_path,"
            "family_id,domain,repository_fixture_id,hidden_test_manifest_id,policy_version,retrieval_policy,"
            "experiment_id,experiment_arm) VALUES(:o,:r,:tk,:ep,:sym,:sig,:tb,:mcl,:refs,1,true,:tp,:fam,:dom,"
            ":fix,:htm,1,cast(:rp as jsonb),:eid,:arm)"),
            {"o": org, "r": repo, "tk": cell["target_task_id"], "ep": cell["editable_paths"],
             "sym": cell["target_symbol"], "sig": cell["exact_signature"], "tb": "hidden:%s" % cell["target_task_id"],
             "mcl": cell["maximum_changed_lines"], "refs": ["refs/heads/main", "main"], "tp": cell["target_path"],
             "fam": cell["family_id"], "dom": cell["domain"], "fix": cell["target_repo"],
             "htm": "hm-%s" % cell["target_task_id"], "rp": json.dumps(rpol), "eid": exp_id, "arm": arm})

    return {"org": org, "target_user": target_user, "repo": repo, "task_key": cell["target_task_id"],
            "desired_ref": "refs/heads/main", "arm": arm, "cell_id": cell["cell_id"], "experiment_id": exp_id,
            "domain": cell["domain"], "stratum": cell["stratum"], "private_seeded": private_ct}
