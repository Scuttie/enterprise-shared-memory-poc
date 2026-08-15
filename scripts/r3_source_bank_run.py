"""REALBENCH-R3 §6 source bank. Runs INSIDE the official DS-1000 conda env. Submits SOURCE_POOL tasks through
the real service path with NO memory (EXECUTION_BACKEND=ds1000), grades with the OFFICIAL DS-1000 evaluator, and
builds USER_SUCCESS_BANK (deployable; source users' own verified solves -> canonical memory) + GOLD_VERIFIED_BANK
(diagnostic; reference-solution facts). One org, 24 source users (source_user != target_user by construction).

Env: E2E_API_URL, OIDC_*, UPSTAGE_API_KEY, DS1000_REPO/DS1000_DATA; R3_SOURCE_SUBSET (first-N-per-library smoke).
Writes artifacts/actionable_memory_r3/{source_bank_manifest,gold_bank_manifest,canonical_memory_manifest,
user_assignment}.json. Run: python scripts/r3_source_bank_run.py
"""
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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, REPO)
from enterprise_memory.persistence.database import make_engine                      # noqa: E402
from enterprise_memory.providers.solar import SolarProvider                         # noqa: E402
from enterprise_memory.providers.secrets import EnvSecretProvider                   # noqa: E402
from experiments.actionable_memory_r3 import ds1000_adapter as AD, assignment as ASG, \
    source_bank as SB, users as U                                                   # noqa: E402
from experiments.actionable_memory_r3.service_adapter import fixture_id            # noqa: E402

API_URL = os.environ["E2E_API_URL"]
ISSUER = os.environ.get("OIDC_ISSUER", "https://idp.e2e.local/")
AUDIENCE = os.environ.get("OIDC_AUDIENCE", "esm-api")
ART = os.path.join(REPO, "artifacts", "actionable_memory_r3")
DATA = AD.__dict__  # noqa
DS_DATA = os.environ.get("DS1000_DATA", os.path.join(os.environ.get("DS1000_REPO", "DS-1000"),
                                                     "data", "ds1000.jsonl.gz"))
EVAL_HASH = json.load(open(os.path.join(REPO, "configs", "actionable_memory_r3", "ds1000_lock.json"),
                           encoding="utf-8"))["github_commit"]


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


def _source_tasks():
    part = json.load(open(os.path.join(ART, "task_partition.json"), encoding="utf-8"))
    src_ids = set(part["sets"]["SOURCE_POOL"])
    tasks = [t for t in AD.load_tasks(DS_DATA) if t["_id"] in src_ids]
    n = os.environ.get("R3_SOURCE_SUBSET")
    if n:
        bylib = collections.defaultdict(list)
        for t in sorted(tasks, key=lambda x: int(x["_id"].split("_")[1])):
            bylib[t["_library"]].append(t)
        tasks = [t for lib in bylib.values() for t in lib[:int(n)]]
    return tasks


async def _seed(org, user_uuid, tasks, assign):
    e = su()
    try:
        async with e.begin() as c:
            await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                            {"i": org, "k": "org-r3-%s" % org})
            for u in set(user_uuid.values()):
                await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                                {"i": u, "o": org, "s": "u-" + u})
        out = []
        for t in tasks:
            tid = t["_id"]; pid = tid.split("_")[1]; u = user_uuid[tid]; repo = str(uuid.uuid4())
            async with e.begin() as c:
                await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"),
                                {"i": repo, "o": org, "r": fixture_id(pid)})
                await c.execute(text("INSERT INTO repository_permissions(org_id,repository_id,subject_type,"
                                     "subject_id,can_read,can_modify) VALUES(:o,:r,'user',:u,true,true)"),
                                {"o": org, "r": repo, "u": u})
                await c.execute(text(
                    "INSERT INTO task_execution_policies(org_id,repository_id,task_key,editable_paths,"
                    "target_symbol,exact_signature,test_bundle_ref,maximum_changed_lines,allowed_refs,version,"
                    "active,target_path,repository_fixture_id,hidden_test_manifest_id,policy_version,"
                    "retrieval_policy,experiment_id,experiment_arm) VALUES(:o,:r,:tk,:ep,:sym,:sig,:tb,:mcl,"
                    ":refs,1,true,:tp,:fix,:htm,1,cast(:rp as jsonb),:eid,:arm)"),
                    {"o": org, "r": repo, "tk": tid, "ep": ["src/**"], "sym": "", "sig": "",
                     "tb": "DS1000:" + pid, "mcl": 400, "refs": ["refs/heads/main", "main"],
                     "tp": "src/solution.py", "fix": fixture_id(pid), "htm": "DS1000:" + pid,
                     "rp": json.dumps({"scopes": [], "max_injected": 0}),
                     "eid": "R3_SOURCE_BANK", "arm": "SOURCE"})
            out.append({"tid": tid, "pid": pid, "repo": repo, "user": u, "task": t})
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


def _provider():
    mo = int(os.environ.get("SOLAR_MAX_TOKENS", "1024"))
    return SolarProvider(os.environ["SOLAR_BASE_URL"], os.environ["SOLAR_MODEL"], EnvSecretProvider(),
                         key_name=os.environ.get("SOLAR_KEY_NAME", "UPSTAGE_API_KEY"), max_output_tokens=mo,
                         max_attempts=int(os.environ.get("SOLAR_MAX_ATTEMPTS", "8")),
                         total_deadline=float(os.environ.get("SOLAR_TOTAL_DEADLINE", "300")),
                         read_timeout=float(os.environ.get("SOLAR_READ_TIMEOUT", "40")),
                         backoff_max=float(os.environ.get("SOLAR_BACKOFF_MAX", "16")),
                         retry_after_max=float(os.environ.get("SOLAR_RETRY_AFTER_MAX", "30")))


def main():
    tasks = _source_tasks()
    assign = ASG.assign_source_users(tasks)                       # {tid: 'r3-su-XX'}
    org = str(uuid.uuid4())
    slot_uuid = {slot: str(uuid.uuid4()) for slot in U.source_users()}
    user_uuid = {tid: slot_uuid[assign[tid]] for tid in assign}   # {tid: uuid}
    seeded = asyncio.run(_seed(org, user_uuid, tasks, assign))
    sign = _sign_factory()
    tokens = {u: sign(u, org) for u in set(user_uuid.values())}

    jobs = []
    with httpx.Client(base_url=API_URL, timeout=60.0) as client:
        for s in seeded:
            tok = tokens[s["user"]]
            r = client.post("/v1/solve", headers={"authorization": "Bearer " + tok,
                                                  "Idempotency-Key": "r3src-" + s["tid"]},
                            json={"repository_id": s["repo"], "task_id": s["tid"],
                                  "instruction": s["task"]["prompt"], "desired_ref": "refs/heads/main"})
            if r.status_code != 202:
                raise SystemExit("submit %s: %d %s" % (s["tid"], r.status_code, r.text))
            jobs.append({**s, "job_id": r.json()["job_id"], "token": tok})
        print("submitted %d source solves" % len(jobs), flush=True)
        deadline = time.time() + int(os.environ.get("RUN_DEADLINE", "12000"))
        pending = {j["tid"]: j for j in jobs}
        last_log = 0.0
        states = collections.Counter()
        while pending and time.time() < deadline:
            states = collections.Counter()
            for tid in list(pending):
                st = client.get("/v1/jobs/%s" % pending[tid]["job_id"],
                                headers={"authorization": "Bearer " + pending[tid]["token"]}).json().get("state")
                states[st] += 1
                if st in ("SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTER"):
                    pending.pop(tid)
            if time.time() - last_log > 25:
                print("poll: terminal=%d pending=%d states=%s" % (len(jobs) - len(pending), len(pending),
                                                                  dict(states)), flush=True)
                last_log = time.time()
            if pending:
                time.sleep(5)
        print("terminal %d pending %d final_states=%s" % (len(jobs) - len(pending), len(pending), dict(states)),
              flush=True)

    provider = _provider()
    user_success, gold, canon = [], [], []
    by_user = collections.Counter()

    async def _build():
        # collect outcomes + GOLD facts (no model calls) first
        successes = []
        for j in jobs:
            r = await _collect(j["job_id"])
            task = j["task"]
            gcam = SB.CB.assemble(task, task["reference_code"], "gold", EVAL_HASH, semantic={})
            gold.append(SB.gold_record(gcam))
            if r["pass1"] == 1 and r["applied_patch"]:
                successes.append((j, r))
        print("solves done: %d verified -> abstracting canonical (concurrent)" % len(successes), flush=True)
        sem = asyncio.Semaphore(int(os.environ.get("R3_ABSTRACT_CONCURRENCY", "4")))

        async def _one(j, r):
            task = j["task"]
            async with sem:
                cam = await SB.abstract_canonical(provider, task, r["applied_patch"], j["user"], EVAL_HASH,
                                                  org_id=org, logical_request_id="r3-canon-" + j["tid"])
            cam.assert_no_target_leakage(task.get("reference_code", ""), task.get("code_context", ""))
            return SB.user_success_record(cam), j["user"]
        for rec, usr in await asyncio.gather(*[_one(j, r) for j, r in successes]):
            user_success.append(rec); canon.append(rec); by_user[usr] += 1
        print("canonical abstraction done: %d records" % len(user_success), flush=True)
    asyncio.run(_build())

    os.makedirs(ART, exist_ok=True)
    n_src = len(jobs)
    json.dump({"bank_type": "USER_SUCCESS_BANK", "benchmark": "DS-1000", "n_source": n_src,
               "n_verified": len(user_success), "coverage": round(len(user_success) / max(1, n_src), 4),
               "distinct_source_users": len(by_user), "library_coverage": SB.coverage_by_library(user_success),
               "facts": user_success},
              open(os.path.join(ART, "source_bank_manifest.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    json.dump({"bank_type": "GOLD_VERIFIED_BANK", "benchmark": "DS-1000", "n_source": n_src, "facts": gold},
              open(os.path.join(ART, "gold_bank_manifest.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    json.dump({"n": len(canon), "facts": canon},
              open(os.path.join(ART, "canonical_memory_manifest.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    json.dump({"org": org, "assignment": {t: assign[t] for t in assign}},
              open(os.path.join(ART, "user_assignment.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    print("R3_SOURCE_BANK verified %d/%d (%.1f%%) across %d users; GOLD %d; lib_cov %s"
          % (len(user_success), n_src, 100 * len(user_success) / max(1, n_src), len(by_user), len(gold),
             SB.coverage_by_library(user_success)), flush=True)


if __name__ == "__main__":
    main()
