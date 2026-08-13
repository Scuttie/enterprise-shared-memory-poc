"""BIGCODE-R2-B integration smoke (unpaid-ish: K Solar calls). Proves the FULL service path works INSIDE the
official eval image: HTTP -> durable job -> separate worker -> (no memory) -> Solar -> OFFICIAL BigCodeBench
grader (in-worker, Python 3.10) -> durable evidence. Seeds K frozen MAIN tasks with NO memory and reports
Pass@1/Exec@1 + that grading routed through the official grader. Run inside the eval image.

Usage: SMOKE_K=6 python scripts/bigcode_r2_smoke.py"""
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
from experiments.bigcode_r2 import grader as G                            # noqa: E402
from experiments.bigcode_r2.adapter import fixture_id                     # noqa: E402

API_URL = os.environ["E2E_API_URL"]
ISSUER = os.environ.get("OIDC_ISSUER", "https://idp.e2e.local/")
AUDIENCE = os.environ.get("OIDC_AUDIENCE", "esm-api")
K = int(os.environ.get("SMOKE_K", "6"))


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


def _main_ids():
    p = json.load(open(os.path.join("artifacts", "bigcode_r2", "task_partition.json"), encoding="utf-8"))
    return p["sets"]["main"][:K]


async def _seed(org, user, tids):
    e = su()
    try:
        async with e.begin() as c:
            await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                            {"i": org, "k": "org-smoke-%s" % org})
            await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                            {"i": user, "o": org, "s": "u-" + user})
        out = []
        for t in tids:
            tk = G.task(t); repo = str(uuid.uuid4())
            async with e.begin() as c:
                await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"),
                                {"i": repo, "o": org, "r": fixture_id(t)})
                await c.execute(text("INSERT INTO repository_permissions(org_id,repository_id,subject_type,"
                                     "subject_id,can_read,can_modify) VALUES(:o,:r,'user',:u,true,true)"),
                                {"o": org, "r": repo, "u": user})
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
                     "eid": "BIGCODE_R2_SMOKE", "arm": "M0"})
            out.append({"tid": t, "repo": repo,
                        "instruction": tk["instruct_prompt"]})
        return out
    finally:
        await e.dispose()


async def _collect(job_id):
    e = su()
    try:
        async with e.connect() as c:
            oc = (await c.execute(text("SELECT pass1,exec1 FROM outcome_observations WHERE job_id=:j"),
                                  {"j": job_id})).first()
            model = (await c.execute(text("SELECT returned_model FROM model_calls WHERE job_id=:j "
                                          "ORDER BY created_at DESC LIMIT 1"), {"j": job_id})).scalar()
    finally:
        await e.dispose()
    return {"pass1": int(oc[0]) if oc and oc[0] is not None else 0,
            "exec1": int(oc[1]) if oc and oc[1] is not None else 0, "model": model}


def main():
    tids = _main_ids()
    org, user = str(uuid.uuid4()), str(uuid.uuid4())
    targets = asyncio.run(_seed(org, user, tids))
    sign = _sign_factory()
    tok = sign(user, org)
    jobs = []
    with httpx.Client(base_url=API_URL, timeout=60.0) as client:
        for tg in targets:
            r = client.post("/v1/solve", headers={"authorization": "Bearer " + tok,
                                                  "Idempotency-Key": "smoke-" + tg["tid"]},
                            json={"repository_id": tg["repo"], "task_id": tg["tid"],
                                  "instruction": tg["instruction"], "desired_ref": "refs/heads/main"})
            if r.status_code != 202:
                raise SystemExit("submit %s: %d %s" % (tg["tid"], r.status_code, r.text))
            jobs.append({"tid": tg["tid"], "job_id": r.json()["job_id"]})
        print("submitted", len(jobs), flush=True)
        deadline = time.time() + int(os.environ.get("RUN_DEADLINE", "1800"))
        pending = {j["tid"]: j for j in jobs}
        while pending and time.time() < deadline:
            for tid in list(pending):
                st = client.get("/v1/jobs/%s" % pending[tid]["job_id"],
                                headers={"authorization": "Bearer " + tok}).json().get("state")
                if st in ("SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTER"):
                    pending.pop(tid)
            if pending:
                time.sleep(4)
    res = [dict(tid=j["tid"], **asyncio.run(_collect(j["job_id"]))) for j in jobs]
    p1 = sum(r["pass1"] for r in res) / len(res)
    ex = sum(r["exec1"] for r in res) / len(res)
    out = {"k": len(res), "pass1": round(p1, 3), "exec1": round(ex, 3),
           "models": sorted({r["model"] for r in res if r["model"]}), "results": res}
    os.makedirs(os.path.join("artifacts", "bigcode_r2"), exist_ok=True)
    json.dump(out, open(os.path.join("artifacts", "bigcode_r2", "smoke_results.json"), "w",
                        encoding="utf-8", newline="\n"), indent=2, sort_keys=True)
    print("SMOKE pass1=%.3f exec1=%.3f models=%s" % (p1, ex, out["models"]), flush=True)
    if ex == 0:
        print("SMOKE_FAIL: nothing executed through the official grader", flush=True)
        sys.exit(2)
    print("SMOKE_OK", flush=True)


if __name__ == "__main__":
    main()
