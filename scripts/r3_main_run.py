"""REALBENCH-R3 §17 — confirmatory main runner (also §16 calibration via R3_ARMS=calib). Runs INSIDE the DS-1000
conda env. Seeds the 7 main arms M0-M6 (selected bundle from selected_policy.json), solves the CONFIRMATORY_MAIN
split through the real service path, grades officially, writes raw chunks. Env: CHUNK=i/n; R3_ARMS=main|calib;
R3_SPLIT=CONFIRMATORY_MAIN|INSTRUMENT_CALIBRATION.
"""
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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src")); sys.path.insert(0, REPO)
from enterprise_memory.persistence.database import make_engine                       # noqa: E402
from enterprise_memory.service.ci_container import _embedder                          # noqa: E402
from enterprise_memory.indexing.qdrant_indexes import QdrantIndex                     # noqa: E402
from experiments.actionable_memory_r3 import ds1000_adapter as AD, assignment as ASG, \
    canonical_builder as CB, main_seeding as MS, renderers as RND, users as U          # noqa: E402
from experiments.actionable_memory_r3 import discovery_analysis as DA                  # noqa: E402

API_URL = os.environ["E2E_API_URL"]
ISSUER = os.environ.get("OIDC_ISSUER", "https://idp.e2e.local/")
AUDIENCE = os.environ.get("OIDC_AUDIENCE", "esm-api")
ART = os.path.join(REPO, "artifacts", "actionable_memory_r3")
DS_DATA = os.environ.get("DS1000_DATA", os.path.join(os.environ.get("DS1000_REPO", "DS-1000"),
                                                     "data", "ds1000.jsonl.gz"))
IS_CALIB = os.environ.get("R3_ARMS", "main") == "calib"
SPLIT = os.environ.get("R3_SPLIT", "INSTRUMENT_CALIBRATION" if IS_CALIB else "CONFIRMATORY_MAIN")
ARMS = MS.CALIB_ARMS if IS_CALIB else MS.MAIN_ARMS
EXP = "R3_CALIBRATION" if IS_CALIB else "R3_MAIN"


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


def _targets():
    part = json.load(open(os.path.join(ART, "task_partition.json"), encoding="utf-8"))
    ids = set(part["sets"][SPLIT])
    tasks = [t for t in AD.load_tasks(DS_DATA) if t["_id"] in ids]
    ch = os.environ.get("CHUNK")
    if ch:
        i, n = [int(x) for x in ch.split("/")]
        tasks = [t for k, t in enumerate(sorted(tasks, key=lambda x: int(x["_id"].split("_")[1]))) if k % n == i]
    return tasks


def _selected_bundle():
    p = os.path.join(ART, "selected_policy.json")
    if os.path.exists(p):
        b = json.load(open(p, encoding="utf-8")).get("selected")
        if b:
            return b
    return os.environ.get("R3_SELECTED_BUNDLE", "B1")   # fallback only if selection absent


def main():
    targets = _targets()
    bank = DA.load_bank()
    gold = {f["source_task_id"]: f for f in json.load(open(os.path.join(ART, "gold_bank_manifest.json"),
                                                           encoding="utf-8"))["facts"]}
    all_tasks = {t["_id"]: t for t in AD.load_tasks(DS_DATA)}
    SB = _selected_bundle()
    # evaluator-side relevance labels (same definition as discovery, frozen threshold 0.1)
    tgt_sig = {t["_id"]: {"relevant_apis": CB.structural(t["reference_code"])["relevant_apis"],
                          "ordered_operations": CB.structural(t["reference_code"])["operations"],
                          "required_imports": CB.structural(t["reference_code"])["required_imports"]} for t in targets}
    tgt_lib = {t["_id"]: t["_library"] for t in targets}
    src_sig = {s: {"relevant_apis": f.get("relevant_apis", []), "ordered_operations": f.get("ordered_operations", []),
                   "required_imports": f.get("required_imports", [])} for s, f in bank.items()}
    src_lib = {s: (f.get("libraries", ["?"])[0] if f.get("libraries") else "?") for s, f in bank.items()}
    labels = ASG.build_relevance(tgt_sig, src_sig, source_lib=src_lib, target_lib=tgt_lib)
    ref_trace = {s: RND._redact(all_tasks[s]["reference_code"], bank[s].get("source_constants", []))
                 for s in bank if s in all_tasks}
    # private own-source: a DIFFERENT verified source in the same library (not the relevant one), deterministic
    bylib = {}
    for s, l in src_lib.items():
        bylib.setdefault(l, []).append(s)
    priv_src_of = {}
    for t in targets:
        pool = [s for s in sorted(bylib.get(t["_library"], [])) if s != labels.get(t["_id"], {}).get("relevant")]
        priv_src_of[t["_id"]] = pool[int(t["_id"].split("_")[1]) % len(pool)] if pool else None
    # gold canonical dicts keyed by source id (structural facts)
    gold_by_src = {s: gold[s] for s in bank if s in gold}

    org = str(uuid.uuid4())
    tgt_users = [str(uuid.uuid4()) for _ in range(U.N_TARGET_USERS)]
    target_user_of = {t["_id"]: (int(t["_id"].split("_")[1]) % U.N_TARGET_USERS) for t in targets}
    emb = _embedder(); index = QdrantIndex.from_env(int(os.environ.get("INDEX_DIM", "384")))
    engine = su()

    async def _seed():
        async with engine.begin() as c:
            await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                            {"i": org, "k": "org-%s-%s" % (EXP.lower(), org)})
            for u in tgt_users:
                await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                                {"i": u, "o": org, "s": "u-" + u})
        return await MS.seed(engine, index, emb, targets, bank, gold_by_src, labels, priv_src_of,
                             target_user_of, tgt_users, org, EXP, SB, arms=ARMS, ref_trace=ref_trace)
    seeded = asyncio.run(_seed())
    arm_targets = seeded["arm_targets"]
    sign = _sign_factory(); tokens = {u: sign(u, org) for u in tgt_users}

    order = []
    maxlen = max(len(v) for v in arm_targets.values())
    for i in range(maxlen):
        for arm in ARMS:
            if i < len(arm_targets[arm]):
                order.append((arm, arm_targets[arm][i]))
    jobs = []
    with httpx.Client(base_url=API_URL, timeout=60.0) as client:
        for arm, tg in order:
            tok = tokens[tg["user"]]
            r = client.post("/v1/solve", headers={"authorization": "Bearer " + tok,
                                                  "Idempotency-Key": "r3m-%s-%s-%s" % (EXP, arm, tg["tid"])},
                            json={"repository_id": tg["repo"], "task_id": tg["tid"],
                                  "instruction": tg["instruction"], "desired_ref": "refs/heads/main"})
            if r.status_code != 202:
                raise SystemExit("submit %s %s: %d %s" % (arm, tg["tid"], r.status_code, r.text))
            jobs.append({"arm": arm, "tid": tg["tid"], "job_id": r.json()["job_id"], "token": tok})
        print("submitted %d %s jobs (%d arms x %d targets), bundle=%s" % (len(jobs), EXP, len(ARMS),
              len(targets), SB), flush=True)
        deadline = time.time() + int(os.environ.get("RUN_DEADLINE", "9000"))
        pending = {(j["arm"], j["tid"]): j for j in jobs}; last = 0
        while pending and time.time() < deadline:
            for k in list(pending):
                stt = client.get("/v1/jobs/%s" % pending[k]["job_id"],
                                 headers={"authorization": "Bearer " + pending[k]["token"]}).json().get("state")
                if stt in ("SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTER"):
                    pending.pop(k)
            if time.time() - last > 30:
                print("poll: terminal=%d pending=%d" % (len(jobs) - len(pending), len(pending)), flush=True); last = time.time()
            if pending:
                time.sleep(5)
        print("terminal=%d pending=%d" % (len(jobs) - len(pending), len(pending)), flush=True)

    async def _collect_all():
        e = su(); out = []
        try:
            async with e.connect() as c:
                for j in jobs:
                    oc = (await c.execute(text("SELECT pass1,exec1 FROM outcome_observations WHERE job_id=:j"),
                                          {"j": j["job_id"]})).first()
                    ap = (await c.execute(text("SELECT applied_patch FROM job_patches WHERE job_id=:j"),
                                          {"j": j["job_id"]})).scalar()
                    inj = (await c.execute(text("SELECT COUNT(*) FROM retrieval_candidates WHERE job_id=:j AND "
                                                "injected"), {"j": j["job_id"]})).scalar()
                    cu = (await c.execute(text("SELECT cross_user_private_injection_count FROM solve_jobs WHERE "
                                               "id=:j"), {"j": j["job_id"]})).scalar()
                    st = (await c.execute(text("SELECT state FROM solve_jobs WHERE id=:j"),
                                          {"j": j["job_id"]})).scalar()
                    out.append({"arm": j["arm"], "tid": j["tid"],
                                "pass1": int(oc[0]) if oc and oc[0] is not None else 0,
                                "exec1": int(oc[1]) if oc and oc[1] is not None else 0, "applied_patch": ap,
                                "injected": int(inj or 0), "cross_user": int(cu or 0), "state": st})
        finally:
            await e.dispose()
        return out
    rows = asyncio.run(_collect_all())

    os.makedirs(os.path.join(ART, "results"), exist_ok=True)
    ch = os.environ.get("CHUNK", "0/1"); i, n = ch.split("/")
    tag = "calib" if IS_CALIB else "main"
    json.dump({"chunk": ch, "selected_bundle": SB, "rows": rows, "labels": labels},
              open(os.path.join(ART, "results", "%s_raw.%sof%s.json" % (tag, i, n)), "w", encoding="utf-8",
                   newline="\n"), indent=1, sort_keys=True)
    print("wrote %s chunk %s rows %d (bundle %s)" % (tag, ch, len(rows), SB), flush=True)


if __name__ == "__main__":
    main()
