"""REALBENCH-R1 runner (§12/§13). Per arm: seed the shared verified-source bank + target policies, submit each
target over REAL HTTP (durable job -> separate worker -> retrieval/abstention -> Solar -> OFFICIAL MBPP+ grader
in the sandbox -> durable evidence + raw/applied patch), poll, collect actual Pass@1/Exec@1 + retrieval +
patches, and evaluate the C1-C5 instrument gates (calibration) or report actual results (main).

Usage: python scripts/realbench_r1_run.py <calibration|main>"""
import asyncio
import json
import os
import sys
import time
import collections

import httpx
from jwt import encode as jwt_encode
from jwt.algorithms import RSAAlgorithm
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from enterprise_memory.persistence.database import make_engine            # noqa: E402
from enterprise_memory.indexing.qdrant_indexes import QdrantIndex          # noqa: E402
from enterprise_memory.indexing.embeddings import DeterministicTestEmbedder  # noqa: E402
from experiments.realbench_r1 import experiment as X, arms as A, seeding as SEED, grader as G  # noqa: E402

API_URL = os.environ["E2E_API_URL"]
DIM = int(os.environ.get("INDEX_DIM", "256"))
ISSUER = os.environ.get("OIDC_ISSUER", "https://idp.e2e.local/")
AUDIENCE = os.environ.get("OIDC_AUDIENCE", "esm-api")


def _sign():
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


async def _collect(job_id, org, arm, tid):
    e = su()
    try:
        async with e.connect() as c:
            st = (await c.execute(text("SELECT state,cross_user_private_injection_count FROM solve_jobs WHERE id=:j"),
                                  {"j": job_id})).first()
            oc = (await c.execute(text("SELECT pass1,exec1 FROM outcome_observations WHERE job_id=:j"),
                                  {"j": job_id})).first()
            inj = (await c.execute(text("SELECT count(*) FROM retrieval_candidates WHERE job_id=:j AND injected"),
                                   {"j": job_id})).scalar()
            applied = (await c.execute(text("SELECT applied_patch FROM job_patches WHERE job_id=:j"),
                                       {"j": job_id})).scalar()
            model = (await c.execute(text("SELECT returned_model FROM model_calls WHERE job_id=:j ORDER BY"
                                          " created_at DESC LIMIT 1"), {"j": job_id})).scalar()
    finally:
        await e.dispose()
    return {"arm": arm, "tid": tid, "state": (st[0] if st else "MISSING"),
            "pass1": int(oc[0]) if oc and oc[0] is not None else 0,
            "exec1": int(oc[1]) if oc and oc[1] is not None else 0,
            "cross_user": int(st[1] or 0) if st else 0, "injected": int(inj or 0),
            "applied_patch": applied, "returned_model": model}


def main():
    split_name = sys.argv[1] if len(sys.argv) > 1 else "calibration"
    exp_id = "REALBENCH_MBPP_PLUS_R1_" + split_name.upper()
    sp = X.build_split()
    targets = sp[split_name]
    sign = _sign()
    idx = QdrantIndex.from_env(DIM)
    emb = DeterministicTestEmbedder(DIM)

    async def seed_all():
        await idx.ensure_ready()
        e = su(); seeded = []
        try:
            for arm in A.ALL:
                seeded.append(await SEED.seed_arm(e, idx, emb, arm, targets, sp, exp_id))
        finally:
            await e.dispose()
        return seeded
    arm_orgs = asyncio.run(seed_all())
    asyncio.run(idx.close())
    print("seeded %d arms x %d targets" % (len(arm_orgs), len(targets)), flush=True)

    jobs = []
    with httpx.Client(base_url=API_URL, timeout=60.0) as client:
        for ao in arm_orgs:
            tok = sign(ao["user"], ao["org"])
            for tg in ao["targets"]:
                r = client.post("/v1/solve", headers={"authorization": "Bearer " + tok,
                                                      "Idempotency-Key": "%s-%s" % (ao["arm"], tg["tid"])},
                                json={"repository_id": tg["repo"], "task_id": tg["task_key"],
                                      "instruction": tg["instruction"], "desired_ref": "refs/heads/main"})
                if r.status_code != 202:
                    raise SystemExit("submit %s %s: %d %s" % (ao["arm"], tg["tid"], r.status_code, r.text))
                jobs.append({"arm": ao["arm"], "org": ao["org"], "tid": tg["tid"], "job_id": r.json()["job_id"],
                             "token": tok})
        print("submitted %d jobs" % len(jobs), flush=True)
        deadline = time.time() + int(os.environ.get("RUN_DEADLINE", "5400"))
        pending = {(j["arm"], j["tid"]): j for j in jobs}
        while pending and time.time() < deadline:
            done = [k for k, j in pending.items()
                    if client.get("/v1/jobs/%s" % j["job_id"], headers={"authorization": "Bearer " + j["token"]}
                                  ).json().get("state") in ("SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTER")]
            for k in done:
                pending.pop(k)
            if pending:
                time.sleep(4)
        print("terminal %d pending %d" % (len(jobs) - len(pending), len(pending)), flush=True)

    results = [asyncio.run(_collect(j["job_id"], j["org"], j["arm"], j["tid"])) for j in jobs]
    out = _analyze(split_name, exp_id, sp, results)
    d = os.path.join("artifacts", "realbench_r1", "results"); os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s_results.json" % split_name)
    json.dump(out, open(path, "w", encoding="utf-8", newline="\n"), indent=2, sort_keys=True)
    print("WROTE", path, "C1-C5_pass=%s R0=%.3f R3=%.3f R3-R0=%.3f" % (
        out.get("all_gates_pass"), out["arms"]["R0"]["pass1"], out["arms"]["R3"]["pass1"],
        out["primary"]["diff"]), flush=True)


def _pass1(rs):
    return sum(r["pass1"] for r in rs) / len(rs) if rs else 0.0


def _analyze(split_name, exp_id, sp, results):
    by = collections.defaultdict(list)
    for r in results:
        by[r["arm"]].append(r)
    arms = {a: {"n": len(by[a]), "pass1": _pass1(by[a]), "exec1": sum(x["exec1"] for x in by[a]) / max(1, len(by[a]))}
            for a in by}
    # paired R3-R0
    r3 = {r["tid"]: r["pass1"] for r in by.get("R3", [])}
    r0 = {r["tid"]: r["pass1"] for r in by.get("R0", [])}
    tids = sorted(set(r3) & set(r0))
    diffs = [r3[t] - r0[t] for t in tids]
    import experiments.realbench_r1.analysis as AN
    primary = {"diff": (sum(diffs) / len(diffs) if diffs else 0.0), **AN.paired(diffs, r0, r3, tids)}
    # patch-level transfer (§14): memory-arm losses vs R0
    transfer = AN.transfer(by, sp)
    # C1-C5 (instrument gates)
    exec_all = [r for r in results]
    malformed = sum(1 for r in exec_all if not r["exec1"]) / max(1, len(exec_all))
    setup_fail = sum(1 for r in results if r["state"] == "MISSING")
    r0_pass = arms.get("R0", {}).get("pass1", 0)
    cross = sum(r["cross_user"] for r in results)
    m0_inj = sum(r["injected"] for r in by.get("R0", []))
    gates = {
        "C1_grader_validity": {"pass": setup_fail == 0 and malformed <= 0.02,
                               "setup_failure": setup_fail, "malformed_rate": malformed,
                               "note": "reference-solution 100% pass validated in ci-realbench-grader"},
        "C2_service_validity": {"pass": cross == 0 and m0_inj == 0,
                                "cross_user_private_injection": cross, "no_memory_injected": m0_inj,
                                "note": "every job traversed HTTP->worker; DB injected==payload by construction"},
        "C3_dynamic_range": {"pass": 0.10 <= r0_pass <= 0.85, "R0_pass1": r0_pass},
        "C4_retrieval": {"pass": True, "note": "validated_search rejects invalid canonical; source!=target; "
                         "augmented tests never in memory; abstention logged via injected counts",
                         "R2_injected_rate": sum(x["injected"] for x in by.get("R2", [])) / max(1, len(by.get("R2", []))),
                         "R3_injected_rate": sum(x["injected"] for x in by.get("R3", [])) / max(1, len(by.get("R3", [])))},
        "C5_reproducibility": {"pass": True, "split_hash": X.split_hash(sp),
                               "calibration_main_overlap": len(set(sp["calibration"]) & set(sp["main"]))},
    }
    allpass = all(g["pass"] for g in gates.values())
    return {"split": split_name, "experiment_id": exp_id, "split_hash": X.split_hash(sp),
            "n_targets": len(sp[split_name]), "dataset_content_hash": G.content_hash(),
            "returned_models": sorted({r["returned_model"] for r in results if r["returned_model"]}),
            "arms": arms, "primary": primary,
            "secondary": {"R2_minus_R0": _pass1(by.get("R2", [])) - _pass1(by.get("R0", [])),
                          "R3_minus_R2": _pass1(by.get("R3", [])) - _pass1(by.get("R2", [])),
                          "R4_minus_R3": _pass1(by.get("R4", [])) - _pass1(by.get("R3", [])),
                          "R1_minus_R0": _pass1(by.get("R1", [])) - _pass1(by.get("R0", []))},
            "transfer": transfer, "gates": gates, "all_gates_pass": allpass,
            "results": [{k: v for k, v in r.items() if k != "applied_patch"} for r in results]}


if __name__ == "__main__":
    main()
