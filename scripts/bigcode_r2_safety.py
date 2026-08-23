"""BIGCODE-R2 §13 safety subset runner. On the frozen RESERVE tasks (disjoint from all other sets), run
S0-S4 through the real service path (production embedder + official grader), interleaved, and report Pass@1
per arm + evidence-based memory-induced loss classification (patch_forensics) vs S0. Descriptive safety
diagnostic — no confirmatory p-value. Chunkable (CHUNK=i/n) + combinable like the main.

Usage: python scripts/bigcode_r2_safety.py"""
import asyncio
import collections
import json
import os
import sys
import time
import uuid

import httpx
from jwt import encode as jwt_encode
from jwt.algorithms import RSAAlgorithm
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from enterprise_memory.persistence.database import make_engine            # noqa: E402
from enterprise_memory.indexing.qdrant_indexes import QdrantIndex          # noqa: E402
from enterprise_memory.indexing.projection import build_record             # noqa: E402
from enterprise_memory.indexing.models import PRIVATE                      # noqa: E402
from enterprise_memory.service.ci_container import _embedder               # noqa: E402
from experiments.bigcode_r2 import grader as G, relevance as REL, safety as SF   # noqa: E402
from experiments.bigcode_r2.adapter import fixture_id                      # noqa: E402
from experiments import patch_forensics as PF                             # noqa: E402

API_URL = os.environ["E2E_API_URL"]
ART = os.path.join("artifacts", "bigcode_r2")
ISSUER = os.environ.get("OIDC_ISSUER", "https://idp.e2e.local/")
AUDIENCE = os.environ.get("OIDC_AUDIENCE", "esm-api")


def _sign_factory():
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption())
    jwk = json.loads(RSAAlgorithm.to_jwk(k.public_key())); jwk.update(kid="rb", alg="RS256", use="sig")
    json.dump({"keys": [jwk]}, open(os.environ["OIDC_JWKS_FILE"], "w"))

    def sign(sub, org):
        now = int(time.time())
        return jwt_encode({"iss": ISSUER, "aud": AUDIENCE, "sub": str(sub), "org_id": str(org),
                           "scope": "solve:submit solve:read", "iat": now, "nbf": now - 5, "exp": now + 3600},
                          pem, algorithm="RS256", headers={"kid": "rb"})
    return sign


def su():
    return make_engine("postgres", "postgres")


def _sha32(c):
    import hashlib
    return "sha256:" + hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest()[:32]


def _wrong_pattern(labels, facts, sources, t):
    """S3: a VERIFIED source with the richest operation set that has ZERO overlap with the target (a
    confidently-wrong reusable pattern)."""
    tsig = labels["source_sig"]  # placeholder; recompute target overlap via relevance signatures
    best, bestn = None, -1
    ov = REL._sig(t)
    for s in sources:
        ssig = {k: set(v) for k, v in labels["source_sig"][s].items()}
        inter = (ssig["imports"] | ssig["apis"] | ssig["operations"] | ssig["control_flow"]) & \
                (ov["imports"] | ov["apis"] | ov["operations"] | ov["control_flow"])
        if inter:
            continue
        n = len(ssig["operations"]) + len(ssig["apis"])
        if n > bestn:
            bestn, best = n, s
    return best or labels["irrelevant"][t]


async def _collect(job_id, arm, tid, assigned):
    e = su()
    try:
        async with e.connect() as c:
            oc = (await c.execute(text("SELECT pass1,exec1 FROM outcome_observations WHERE job_id=:j"),
                                  {"j": job_id})).first()
            stt = (await c.execute(text("SELECT state,cross_user_private_injection_count FROM solve_jobs WHERE "
                                        "id=:j"), {"j": job_id})).first()
            inj = (await c.execute(text("SELECT count(*) FROM retrieval_candidates WHERE job_id=:j AND injected"),
                                   {"j": job_id})).scalar()
            ap = (await c.execute(text("SELECT applied_patch FROM job_patches WHERE job_id=:j"),
                                  {"j": job_id})).scalar()
            mc = (await c.execute(text("SELECT final_status FROM model_calls WHERE job_id=:j ORDER BY "
                                       "created_at DESC LIMIT 1"), {"j": job_id})).scalar()
    finally:
        await e.dispose()
    return {"arm": arm, "tid": tid, "assigned_source": assigned, "state": (stt[0] if stt else "MISSING"),
            "pass1": int(oc[0]) if oc and oc[0] is not None else 0,
            "exec1": int(oc[1]) if oc and oc[1] is not None else 0,
            "cross_user": int(stt[1] or 0) if stt else 0, "injected": int(inj or 0),
            "applied_patch": ap, "model_status": mc}


async def seed_all(su_e, idx, emb, org, targets, facts, labels, sources, fmt):
    users, arm_targets = {}, {a: [] for a in SF.ARMS}
    async with su_e.begin() as c:
        await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                        {"i": org, "k": "org-bcb-safety-%s" % org})
    for arm in SF.ARMS:
        u = str(uuid.uuid4())
        async with su_e.begin() as c:
            await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                            {"i": u, "o": org, "s": "u-" + u})
        users[arm] = u
        kind = SF.SOURCE_KIND[arm]
        for t in targets:
            tk = G.task(t); repo = str(uuid.uuid4())
            if kind == "none":
                src = None
            elif kind == "shuffled":
                src = labels["shuffled"][t]
            elif kind == "relevant":
                src = labels["relevant"][t]
            elif kind == "irrelevant":
                src = labels["irrelevant"][t]
            else:
                src = _wrong_pattern(labels, facts, sources, t)
            async with su_e.begin() as c:
                await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"),
                                {"i": repo, "o": org, "r": "%s__%s" % (fixture_id(t), arm)})
                await c.execute(text("INSERT INTO repository_permissions(org_id,repository_id,subject_type,"
                                     "subject_id,can_read,can_modify) VALUES(:o,:r,'user',:u,true,true)"),
                                {"o": org, "r": repo, "u": u})
                rp = {"scopes": [], "max_injected": 0}
                if src is not None and src in facts:
                    rendered = SF.render_arm(arm, fmt, facts[src])
                    can = {"private_note": rendered, "source_task": src, "kind": "safety_%s" % arm}
                    eid = str(uuid.uuid4()); ch = _sha32(can)
                    await c.execute(text("INSERT INTO private_episodes(id,org_id,owner_user_id,repository_id,"
                                         "canonical_json,content_hash,state) VALUES(:i,:o,:u,:r,cast(:j as jsonb),"
                                         ":h,'success')"),
                                    {"i": eid, "o": org, "u": u, "r": repo, "j": json.dumps(can), "h": ch})
                    await idx.upsert([build_record(PRIVATE, {"object_id": eid, "content_hash": ch, "org_id": org,
                        "canonical": can, "owner_user_id": u, "repository_id": repo, "state": "success"})],
                        emb.embed([rendered]))
                    rp = {"scopes": ["private"], "max_injected": 1, "search_limit": 1,
                          "abstain": {"tau_abs": 0.0, "tau_margin": 0.0}}
                await c.execute(text(
                    "INSERT INTO task_execution_policies(org_id,repository_id,task_key,editable_paths,"
                    "target_symbol,exact_signature,test_bundle_ref,maximum_changed_lines,allowed_refs,version,"
                    "active,target_path,repository_fixture_id,hidden_test_manifest_id,policy_version,"
                    "retrieval_policy,experiment_id,experiment_arm) VALUES(:o,:r,:tk,:ep,:sym,:sig,:tb,:mcl,"
                    ":refs,1,true,:tp,:fix,:htm,1,cast(:rp as jsonb),:eid,:arm)"),
                    {"o": org, "r": repo, "tk": t, "ep": ["src/**"], "sym": tk["entry_point"],
                     "sig": "def %s" % tk["entry_point"], "tb": "BIGCODE:" + t, "mcl": 800,
                     "refs": ["refs/heads/main", "main"], "tp": "src/solution.py", "fix": fixture_id(t),
                     "htm": "BIGCODE:" + t, "rp": json.dumps(rp), "eid": "BIGCODE_R2_SAFETY", "arm": arm})
            arm_targets[arm].append({"tid": t, "repo": repo, "user": u, "assigned": src,
                                     "instruction": tk["instruct_prompt"]})
    return users, arm_targets


def main():
    part = json.load(open(os.path.join(ART, "task_partition.json"), encoding="utf-8"))
    facts = {f["source_task"]: f for f in json.load(open(os.path.join(ART, "source_bank.json"),
                                                        encoding="utf-8"))["facts"]}
    all_targets = part["sets"]["reserve"]
    chunk = os.environ.get("CHUNK", "0/1"); ci, cn = (int(x) for x in chunk.split("/"))
    targets = all_targets[ci::cn] if cn > 1 else all_targets
    sources = sorted(facts.keys())
    mem_len = {s: len(facts[s]["summary"] or "") for s in sources}
    labels = REL.build_labels(sources, all_targets, mem_len)
    sel = json.load(open(os.path.join(ART, "selected_policy.json"), encoding="utf-8"))
    fmt = (sel.get("selected") or {}).get("format") or "F1_PLAIN_LESSON"
    src_sig = {s: {k: set(facts[s].get(k, [])) for k in ("imports", "apis", "operations", "control_flow")}
               for s in sources}

    sign = _sign_factory(); emb = _embedder()
    idx = QdrantIndex.from_env(getattr(emb, "dim", None) or int(os.environ.get("INDEX_DIM", "384")))
    org = str(uuid.uuid4())

    async def _seed():
        await idx.ensure_ready(); e = su()
        try:
            return await seed_all(e, idx, emb, org, targets, facts, labels, sources, fmt)
        finally:
            await e.dispose()
    users, arm_targets = asyncio.run(_seed()); asyncio.run(idx.close())
    print("safety seeded arms=%s targets=%d" % (list(arm_targets), len(targets)), flush=True)

    max_i = max((len(v) for v in arm_targets.values()), default=0)
    order = [(a, arm_targets[a][i]) for i in range(max_i) for a in SF.ARMS if i < len(arm_targets[a])]
    jobs = []
    with httpx.Client(base_url=API_URL, timeout=60.0) as client:
        for arm, tg in order:
            tok = sign(tg["user"], org)
            r = client.post("/v1/solve", headers={"authorization": "Bearer " + tok,
                                                  "Idempotency-Key": "%s-%s" % (arm, tg["tid"])},
                            json={"repository_id": tg["repo"], "task_id": tg["tid"],
                                  "instruction": tg["instruction"], "desired_ref": "refs/heads/main"})
            if r.status_code != 202:
                raise SystemExit("submit %s %s: %d %s" % (arm, tg["tid"], r.status_code, r.text))
            jobs.append({"arm": arm, "tid": tg["tid"], "job_id": r.json()["job_id"], "token": tok,
                         "assigned": tg["assigned"]})
        print("submitted %d safety jobs" % len(jobs), flush=True)
        deadline = time.time() + int(os.environ.get("RUN_DEADLINE", "17000"))
        pending = {(j["arm"], j["tid"]): j for j in jobs}
        while pending and time.time() < deadline:
            done = [k for k, j in pending.items()
                    if client.get("/v1/jobs/%s" % j["job_id"], headers={"authorization": "Bearer " + j["token"]}
                                  ).json().get("state") in ("SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTER")]
            for k in done:
                pending.pop(k)
            if pending:
                time.sleep(6)

    results = [asyncio.run(_collect(j["job_id"], j["arm"], j["tid"], j["assigned"])) for j in jobs]
    d = os.path.join(ART, "results"); os.makedirs(d, exist_ok=True)
    if cn > 1:
        raw = os.path.join(d, "safety_raw.%dof%d.json" % (ci, cn))
        json.dump({"results": results}, open(raw, "w", encoding="utf-8", newline="\n"), indent=2, sort_keys=True)
        print("WROTE_RAW", raw, flush=True); return
    out = _analyze(all_targets, src_sig, results)
    json.dump(out, open(os.path.join(d, "safety_results.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    print("SAFETY", json.dumps(out["arms_pass1"]), flush=True)


def _analyze(targets, src_sig, results):
    by = collections.defaultdict(list)
    for r in results:
        by[r["arm"]].append(r)
    p1 = lambda a: (sum(x["pass1"] for x in by.get(a, [])) / len(by[a])) if by.get(a) else 0.0
    s0 = {r["tid"]: r for r in by.get("S0", [])}
    arms, transfer = {}, {}
    for a in SF.ARMS:
        rs = by.get(a, [])
        arms[a] = {"name": SF.NAMES[a], "n": len(rs), "pass1": round(p1(a), 4),
                   "exec1": round(sum(x["exec1"] for x in rs) / max(1, len(rs)), 4),
                   "harm_vs_S0": round(p1("S0") - p1(a), 4)}
        if a == "S0":
            continue
        counts = {c: 0 for c in PF.CLASSES}; losses = 0
        for r in rs:
            b = s0.get(r["tid"])
            if b and b["pass1"] == 1 and r["pass1"] == 0:
                losses += 1
                cls, _ = PF.classify_loss(r.get("applied_patch"), b.get("applied_patch"),
                                          src_sig.get(r.get("assigned_source")), injected=bool(r["injected"]),
                                          exec_ok=bool(r["exec1"]))
                counts[cls] += 1
        transfer[a] = {"memory_induced_losses": losses, "loss_classes": {k: v for k, v in counts.items() if v},
                       "adoption_total": sum(counts[c] for c in PF.CLASSES[:4])}
    return {"experiment": "BIGCODE_R2_SAFETY", "note": "descriptive wrong-memory safety (§13); evidence-based "
            "adoption, never poisoning without AST/API evidence", "n_targets": len(targets),
            "cross_user_private_injection": sum(r["cross_user"] for r in results),
            "arms_pass1": {a: arms[a]["pass1"] for a in SF.ARMS}, "arms": arms, "transfer": transfer}


if __name__ == "__main__":
    main()
