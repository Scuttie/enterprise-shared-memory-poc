"""Per-cell seeding (P5.1 §7/§8/§9). Each experiment cell (one family × arm) runs in its OWN org so memory is
cleanly scoped: the generic governed retrieval then returns exactly the arm's seeded memory with no
cross-contamination. Seeds org + users + repository + server-owned task policy (carrying the arm + retrieval
policy) + the arm's memory (private / shared-ungoverned / shared-governed / negative control) into PostgreSQL
and the vector index. Returns the submission parameters (the runner signs a token for the target user and
POSTs /v1/solve — the arm is never in the client request)."""
from __future__ import annotations
import json
import uuid
from datetime import datetime

from sqlalchemy import text
from enterprise_memory.contracts import codec
from enterprise_memory.indexing.projection import build_record
from enterprise_memory.indexing.models import PRIVATE, SHARED
from . import memory_bank as MB


async def _mk_repo_perm(c, org, repo, user, *, can_modify):
    await c.execute(text("INSERT INTO repository_permissions(org_id,repository_id,subject_type,subject_id,"
                         "can_read,can_modify) VALUES(:o,:r,'user',:u,true,:cm)"),
                    {"o": org, "r": repo, "u": user, "cm": can_modify})


_USER_NS = uuid.UUID("3b1e9d7a-2c4f-4a8b-9e6d-5f0a1b2c3d4e")


async def seed_cell(su_engine, index, embedder, cell, family):
    """Seed one cell. Returns {org, target_user, repo, task_key, desired_ref, arm, cell_id}. Each cell runs in
    its own org, so DB user ids are derived PER CELL (users.id is globally unique). The cross-user property is
    preserved: source != target when the frozen assignment says so; source == target for M1 (own source)."""
    org = str(uuid.uuid4())
    repo = str(uuid.uuid4())
    logical_target, logical_source = cell["target_user"], cell["source_user"]
    # DB ids derived from the fresh per-call org uuid -> globally unique even if the same cell is seeded twice
    target_user = str(uuid.uuid5(_USER_NS, org + "|target"))
    if logical_source is None:
        source_user = None
    elif logical_source == logical_target:
        source_user = target_user                      # M1 own-source: same DB user
    else:
        source_user = str(uuid.uuid5(_USER_NS, org + "|source"))   # distinct DB user
    exp_id = cell["cell_id"].rsplit("|", 2)[0] if "|" in cell["cell_id"] else cell["cell_id"]
    async with su_engine.begin() as c:
        await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                        {"i": org, "k": "org-%s-%s" % (cell["cell_id"], org)})   # unique per seeded org
        # users (target always; source only if distinct)
        await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                        {"i": target_user, "o": org, "s": "u-" + target_user})
        if source_user and source_user != target_user:
            await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                            {"i": source_user, "o": org, "s": "u-" + source_user})
        await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"),
                        {"i": repo, "o": org, "r": cell["target_repo"]})
        await _mk_repo_perm(c, org, repo, target_user, can_modify=True)
        if source_user and source_user != target_user:
            await _mk_repo_perm(c, org, repo, source_user, can_modify=False)
        # server-owned task policy: carries the assigned arm + retrieval policy + fixture id + target path
        await c.execute(text(
            "INSERT INTO task_execution_policies(org_id,repository_id,task_key,editable_paths,target_symbol,"
            "exact_signature,test_bundle_ref,maximum_changed_lines,allowed_refs,version,active,target_path,"
            "family_id,domain,repository_fixture_id,hidden_test_manifest_id,policy_version,retrieval_policy,"
            "experiment_id,experiment_arm) VALUES(:o,:r,:tk,:ep,:sym,:sig,'hidden:%s',:mcl,:refs,1,true,:tp,"
            ":fam,:dom,:fix,:htm,1,cast(:rp as jsonb),:eid,:arm)" % cell["target_task_id"]),
            {"o": org, "r": repo, "tk": cell["target_task_id"], "ep": cell["editable_paths"],
             "sym": cell["target_symbol"], "sig": cell["exact_signature"], "mcl": cell["maximum_changed_lines"],
             "refs": ["refs/heads/main", "main"], "tp": cell["target_path"], "fam": cell["family_id"],
             "dom": cell["domain"], "fix": cell["target_repo"], "htm": "hm-%s" % cell["target_task_id"],
             "rp": json.dumps(cell["retrieval_policy"]), "eid": exp_id, "arm": cell["arm"]})

    # seed memory for the arm (outside the DDL tx; uses the index too)
    form = cell["memory_form"]
    records = []
    if form == "none":
        pass
    elif form == "private":
        canonical = MB.private_canonical(family, repo)
        eid = str(uuid.uuid4())
        chash = "sha256:" + codec_sha(canonical)
        async with su_engine.begin() as c:
            await c.execute(text(
                "INSERT INTO private_episodes(id,org_id,owner_user_id,repository_id,canonical_json,"
                "content_hash,state) VALUES(:i,:o,:u,:r,cast(:j as jsonb),:h,'success')"),
                {"i": eid, "o": org, "u": target_user, "r": repo, "j": json.dumps(canonical), "h": chash})
        row = {"object_id": eid, "content_hash": chash, "org_id": org, "canonical": canonical,
               "owner_user_id": target_user, "repository_id": repo, "state": "success"}
        records.append(build_record(PRIVATE, row))
    elif form == "shared_ungoverned":
        canonical = MB.ungoverned_canonical(family)
        await _seed_shared(su_engine, org, repo, canonical, chash_hint=None, records=records)
    else:  # governed forms (shared_governed, negative_*)
        contract = MB.governed_contract(org, repo, family, form)
        canonical = MB.canonical_of(contract)
        # the expired control must be expired in the AUTHORITATIVE DB validity columns (validated_search reads
        # validity from the column, not the canonical), so the governance gate actually rejects it.
        vfrom, vuntil = (None, None)
        if form == "negative_expired":
            vfrom = datetime.strptime(MB._PAST_FROM, "%Y-%m-%d")
            vuntil = datetime.strptime(MB._PAST_UNTIL, "%Y-%m-%d")
        await _seed_shared(su_engine, org, repo, canonical, chash_hint=contract.content_hash,
                           records=records, valid_from=vfrom, valid_until=vuntil)

    if records:
        await index.ensure_ready()
        await index.upsert(records, embedder.embed([r.text for r in records]))

    return {"org": org, "target_user": target_user, "repo": repo, "task_key": cell["target_task_id"],
            "desired_ref": "refs/heads/main", "arm": cell["arm"], "cell_id": cell["cell_id"],
            "experiment_id": exp_id}


def codec_sha(canonical):
    import hashlib
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:32]


async def _seed_shared(su_engine, org, repo, canonical, *, chash_hint, records, valid_from=None,
                       valid_until=None):
    """Insert a promoted shared contract version and queue its index record."""
    cid, vid = str(uuid.uuid4()), str(uuid.uuid4())
    chash = chash_hint or ("sha256:" + codec_sha(canonical))
    async with su_engine.begin() as c:
        await c.execute(text("INSERT INTO memory_contracts(id,org_id,repository_id) VALUES(:i,:o,:r)"),
                        {"i": cid, "o": org, "r": repo})
        await c.execute(text(
            "INSERT INTO memory_contract_versions(id,contract_id,org_id,version_number,canonical_json,"
            "content_hash,governance_state,valid_from,valid_until) VALUES(:i,:c,:o,1,cast(:j as jsonb),:h,"
            "'promoted',cast(:vf as timestamptz),cast(:vu as timestamptz))"),
            {"i": vid, "c": cid, "o": org, "j": json.dumps(canonical), "h": chash, "vf": valid_from,
             "vu": valid_until})
        await c.execute(text("UPDATE memory_contracts SET current_version_id=:v WHERE id=:c"),
                        {"v": vid, "c": cid})
    row = {"contract_id": cid, "object_id": vid, "version_number": 1, "content_hash": chash,
           "org_id": org, "canonical": canonical, "repository_id": repo, "governance_state": "promoted",
           "valid_from": valid_from, "valid_until": valid_until}
    records.append(build_record(SHARED, row))
