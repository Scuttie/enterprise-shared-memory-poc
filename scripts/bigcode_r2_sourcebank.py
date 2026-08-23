"""BIGCODE-R2-B source bank (§5). Runs INSIDE the official eval image. Submits the 300 SOURCE tasks through
the real service path with NO memory, grades with the official evaluator, and builds two explicitly-labelled
banks:

  USER_SUCCESS_BANK (deployable) — for each source task the source user SOLVED (verified), the source user's
    OWN verified solve (the applied patch) becomes the memory content. This is actual user experience.
  GOLD_VERIFIED_BANK (diagnostic upper bound) — the official reference solution's signature, used only for
    relevance labels / true-oracle; never presented as deployable experience.

One org, 24 source users (source_user != target_user by construction). Persists source_bank.json +
gold_bank.json. Run: python scripts/bigcode_r2_sourcebank.py"""
import asyncio
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
from experiments.bigcode_r2 import grader as G, users as U               # noqa: E402
from experiments.bigcode_r2.adapter import fixture_id                     # noqa: E402
from experiments import patch_forensics as PF                            # noqa: E402

API_URL = os.environ["E2E_API_URL"]
ISSUER = os.environ.get("OIDC_ISSUER", "https://idp.e2e.local/")
AUDIENCE = os.environ.get("OIDC_AUDIENCE", "esm-api")
ART = os.path.join("artifacts", "bigcode_r2")


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


def _sources():
    p = json.load(open(os.path.join(ART, "task_partition.json"), encoding="utf-8"))
    return p["sets"]["source"]


async def _seed(org, users, assignment, sources):
    e = su()
    try:
        async with e.begin() as c:
            await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                            {"i": org, "k": "org-bcb-%s" % org})
            for u in users:
                await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                                {"i": u, "o": org, "s": "u-" + u})
        out = []
        for t in sources:
            u = users[assignment["source_of"][t]]
            tk = G.task(t); repo = str(uuid.uuid4())
            async with e.begin() as c:
                await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"),
                                {"i": repo, "o": org, "r": fixture_id(t)})
                await c.execute(text("INSERT INTO repository_permissions(org_id,repository_id,subject_type,"
                                     "subject_id,can_read,can_modify) VALUES(:o,:r,'user',:u,true,true)"),
                                {"o": org, "r": repo, "u": u})
                await c.execute(text(
                    "INSERT INTO task_execution_policies(org_id,repository_id,task_key,editable_paths,"
                    "target_symbol,exact_signature,test_bundle_ref,maximum_changed_lines,allowed_refs,version,"
                    "active,target_path,repository_fixture_id,hidden_test_manifest_id,policy_version,"
                    "retrieval_policy,experiment_id,experiment_arm) VALUES(:o,:r,:tk,:ep,:sym,:sig,:tb,:mcl,"
                    ":refs,1,true,:tp,:fix,:htm,1,cast(:rp as jsonb),:eid,:arm)"),
                    {"o": org, "r": repo, "tk": t, "ep": ["src/**"], "sym": tk["entry_point"],
                     "sig": "def %s" % tk["entry_point"], "tb": "BIGCODE:" + t, "mcl": 400,
                     "refs": ["refs/heads/main", "main"], "tp": "src/solution.py", "fix": fixture_id(t),
                     "htm": "BIGCODE:" + t, "rp": json.dumps({"scopes": [], "max_injected": 0}),
                     "eid": "BIGCODE_R2_SOURCEBANK", "arm": "SOURCE"})
            out.append({"tid": t, "repo": repo, "user": u, "instruction": tk["instruct_prompt"]})
        return out
    finally:
        await e.dispose()


async def _collect(job_id):
    e = su()
    try:
        async with e.connect() as c:
            oc = (await c.execute(text("SELECT pass1,exec1 FROM outcome_observations WHERE job_id=:j"),
                                  {"j": job_id})).first()
            applied = (await c.execute(text("SELECT applied_patch FROM job_patches WHERE job_id=:j"),
                                       {"j": job_id})).scalar()
    finally:
        await e.dispose()
    return {"pass1": int(oc[0]) if oc and oc[0] is not None else 0,
            "exec1": int(oc[1]) if oc and oc[1] is not None else 0, "applied_patch": applied}


def _fact(tid, verified_code):
    tk = G.task(tid)
    sig = PF.patch_signature(verified_code or "") or {"imports": set(), "apis": set(),
                                                       "control_flow": set(), "operations": set()}
    summary = (tk["instruct_prompt"].strip().splitlines() or [tid])[0][:160]
    return {"source_task": tid, "entry_point": tk["entry_point"], "summary": summary,
            "verified_code": verified_code, "pitfall": "handle empty / boundary inputs and exact return type",
            "imports": sorted(sig["imports"]), "apis": sorted(sig["apis"]),
            "operations": sorted(sig["operations"]), "control_flow": sorted(sig["control_flow"])}


def main():
    sources = _sources()
    assignment = U.build_assignment(sources, [])
    org = str(uuid.uuid4())
    users = [str(uuid.uuid4()) for _ in range(U.N_SOURCE_USERS)]
    targets = asyncio.run(_seed(org, users, assignment, sources))
    sign = _sign_factory()
    tokens = {u: sign(u, org) for u in users}

    jobs = []
    with httpx.Client(base_url=API_URL, timeout=60.0) as client:
        for tg in targets:
            tok = tokens[tg["user"]]
            r = client.post("/v1/solve", headers={"authorization": "Bearer " + tok,
                                                  "Idempotency-Key": "src-" + tg["tid"]},
                            json={"repository_id": tg["repo"], "task_id": tg["tid"],
                                  "instruction": tg["instruction"], "desired_ref": "refs/heads/main"})
            if r.status_code != 202:
                raise SystemExit("submit %s: %d %s" % (tg["tid"], r.status_code, r.text))
            jobs.append({"tid": tg["tid"], "job_id": r.json()["job_id"], "user": tg["user"], "token": tok})
        print("submitted %d source solves" % len(jobs), flush=True)
        deadline = time.time() + int(os.environ.get("RUN_DEADLINE", "9000"))
        pending = {j["tid"]: j for j in jobs}
        while pending and time.time() < deadline:
            for tid in list(pending):
                st = client.get("/v1/jobs/%s" % pending[tid]["job_id"],
                                headers={"authorization": "Bearer " + pending[tid]["token"]}).json().get("state")
                if st in ("SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTER"):
                    pending.pop(tid)
            if pending:
                time.sleep(5)
        print("terminal %d pending %d" % (len(jobs) - len(pending), len(pending)), flush=True)

    verified, gold = [], []
    by_user_success = {}
    for j in jobs:
        r = asyncio.run(_collect(j["job_id"]))
        gold.append(_fact(j["tid"], G.reference_solution(j["tid"])))    # GOLD: reference signature
        if r["pass1"] == 1 and r["applied_patch"]:
            f = _fact(j["tid"], r["applied_patch"])                      # USER_SUCCESS: own verified solve
            f["owner_user"] = j["user"]
            verified.append(f)
            by_user_success[j["user"]] = by_user_success.get(j["user"], 0) + 1

    os.makedirs(ART, exist_ok=True)
    json.dump({"bank_type": "USER_SUCCESS_BANK", "n_source": len(sources), "n_verified": len(verified),
               "coverage": round(len(verified) / len(sources), 4),
               "distinct_source_users": len(by_user_success), "facts": verified},
              open(os.path.join(ART, "source_bank.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    json.dump({"bank_type": "GOLD_VERIFIED_BANK", "n_source": len(sources), "facts": gold},
              open(os.path.join(ART, "gold_bank.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    print("SOURCE_BANK verified %d/%d (%.1f%%) across %d users; GOLD %d"
          % (len(verified), len(sources), 100 * len(verified) / len(sources), len(by_user_success), len(gold)),
          flush=True)


if __name__ == "__main__":
    main()
