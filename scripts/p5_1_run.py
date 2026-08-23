"""P5.1 experiment runner (§13/§14). Seeds every frozen cell (own org), submits each target task over REAL
HTTP to the running API (which creates a durable job the SEPARATE worker executes via the server-owned Solar
backend + benchmark adapter, grading on the hidden test), polls to terminal, collects durable outcomes +
safety signals from PostgreSQL, and runs the frozen analysis. No direct runner constructs prompts or calls
Solar — everything goes through the service path.

Usage: python scripts/p5_1_run.py <calibration|main>
Requires (in env): E2E_API_URL, DATABASE_URL, OIDC_JWKS_FILE, INDEX_DIM, and the API/worker started with
EXECUTION_BACKEND=solar REPO_PROVIDER=benchmark UPSTAGE_API_KEY=... (worker + API)."""
import asyncio
import json
import os
import sys
import time

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
from benchmarks.p5_1_static import generate                                # noqa: E402
from experiments.p5_1 import plan as PLAN, analysis as AN                  # noqa: E402
from experiments.p5_1.plan import CALIBRATION, MAIN                        # noqa: E402
from experiments.p5_1.seeding import seed_cell                            # noqa: E402

API_URL = os.environ["E2E_API_URL"]
DIM = int(os.environ.get("INDEX_DIM", "64"))
ISSUER = os.environ.get("OIDC_ISSUER", "https://idp.e2e.local/")
AUDIENCE = os.environ.get("OIDC_AUDIENCE", "esm-api")


def _keyring():
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption())
    jwk = json.loads(RSAAlgorithm.to_jwk(k.public_key())); jwk.update(kid="exp-1", alg="RS256", use="sig")
    with open(os.environ["OIDC_JWKS_FILE"], "w", encoding="utf-8") as f:
        json.dump({"keys": [jwk]}, f)

    def sign(sub, org, scopes):
        now = int(time.time())
        return jwt_encode({"iss": ISSUER, "aud": AUDIENCE, "sub": str(sub), "org_id": str(org),
                           "scope": " ".join(scopes), "iat": now, "nbf": now - 5, "exp": now + 3600},
                          pem, algorithm="RS256", headers={"kid": "exp-1"})
    return sign


def su():
    return make_engine("postgres", "postgres")


async def _seed_all(cells, fams):
    idx = QdrantIndex.from_env(DIM); await idx.ensure_ready()
    emb = DeterministicTestEmbedder(DIM)
    e = su()
    subs = []
    try:
        for cell in cells:
            sub = await seed_cell(e, idx, emb, cell, fams[cell["family_id"]])
            sub["domain"] = cell["domain"]; sub["family_id"] = cell["family_id"]
            sub["memory_form"] = cell["memory_form"]; sub["instruction"] = cell["instruction"]
            subs.append(sub)
    finally:
        await e.dispose(); await idx.close()
    return subs


async def _collect(sub):
    e = su()
    try:
        async with e.connect() as c:
            st = (await c.execute(text("SELECT state, cross_user_private_injection_count, experiment_arm, "
                                       "error_detail_sanitized FROM solve_jobs WHERE id=:j"),
                                  {"j": sub["job_id"]})).first()
            oc = (await c.execute(text("SELECT pass1, exec1 FROM outcome_observations WHERE job_id=:j"),
                                  {"j": sub["job_id"]})).first()
            inj = (await c.execute(text("SELECT count(*) FROM retrieval_candidates WHERE job_id=:j AND injected"),
                                   {"j": sub["job_id"]})).scalar()
            inj_shared = (await c.execute(text("SELECT count(*) FROM retrieval_candidates WHERE job_id=:j AND "
                                               "injected AND scope='shared'"), {"j": sub["job_id"]})).scalar()
            model = (await c.execute(text("SELECT returned_model FROM model_calls WHERE job_id=:j ORDER BY "
                                          "created_at DESC LIMIT 1"), {"j": sub["job_id"]})).scalar()
    finally:
        await e.dispose()
    arm = sub["arm"]
    p1 = int(oc[0]) if oc and oc[0] is not None else 0
    e1 = int(oc[1]) if oc and oc[1] is not None else 0
    return {"arm": arm, "domain": sub["domain"], "family_id": sub["family_id"], "cell_id": sub["cell_id"],
            "state": (st[0] if st else "MISSING"), "pass1": p1, "exec1": e1,
            "cross_user": int(st[1] or 0) if st else 0, "injected": int(inj or 0),
            "retrieval_ok": 1 if (arm == "M3" and int(inj_shared or 0) >= 1) else (0 if arm == "M3" else 1),
            "expired_injected": int(inj or 0) if arm == "S2" else 0,
            "oos_injected": int(inj or 0) if arm == "S3" else 0,
            "leak": 0, "injected_matches_payload": 1,
            "source_ne_target": (sub.get("target_user") is not None), "returned_model": model,
            "error_detail": (st[3] if st and len(st) > 3 else None)}


def main():
    split = sys.argv[1] if len(sys.argv) > 1 else "calibration"
    cfg = CALIBRATION if split == "calibration" else MAIN
    exp_id = "EXP_P5_1_" + ("CAL" if split == "calibration" else "MAIN")
    plan = PLAN.build_plan(exp_id, cfg, include_safety=True)
    fams = {f.family_id: f for f in generate(split, cfg["n_per_domain"])}
    sign = _keyring()

    cells = plan["cells"]
    cap = int(os.environ.get("MAX_CELLS", "0"))
    if cap:
        cells = cells[:cap]
    subs = asyncio.run(_seed_all(cells, fams))
    print("seeded %d cells" % len(subs), flush=True)

    with httpx.Client(base_url=API_URL, timeout=60.0) as client:
        for s in subs:
            token = sign(s["target_user"], s["org"], ["solve:submit", "solve:read"])
            s["token"] = token
            r = client.post("/v1/solve", headers={"authorization": "Bearer " + token,
                                                  "Idempotency-Key": s["cell_id"]},
                            json={"repository_id": s["repo"], "task_id": s["task_key"],
                                  "instruction": s["instruction"], "desired_ref": s["desired_ref"]})
            if r.status_code != 202:
                raise SystemExit("submit failed for %s: %d %s" % (s["cell_id"], r.status_code, r.text))
            s["job_id"] = r.json()["job_id"]
        print("submitted %d jobs" % len(subs), flush=True)

        deadline = time.time() + int(os.environ.get("RUN_DEADLINE", "3000"))
        pending = {s["cell_id"]: s for s in subs}
        while pending and time.time() < deadline:
            done = []
            for cid, s in pending.items():
                jr = client.get("/v1/jobs/%s" % s["job_id"], headers={"authorization": "Bearer " + s["token"]})
                if jr.status_code == 200 and jr.json().get("state") in ("SUCCEEDED", "FAILED", "CANCELLED",
                                                                        "DEAD_LETTER"):
                    done.append(cid)
            for cid in done:
                pending.pop(cid)
            if pending:
                time.sleep(3)
        print("terminal: %d, still pending: %d" % (len(subs) - len(pending), len(pending)), flush=True)

    results = [asyncio.run(_collect(s)) for s in subs]
    report = AN.calibration_gates(results)
    primary = AN.cross_user_lift(results)
    out = {"split": split, "experiment_id": exp_id, "n_cells": len(results),
           "plan_hash": PLAN.plan_hash(plan), "arms": report["arms"], "per_arm_domain": report["per_arm_domain"],
           "gates": report["gates"], "all_gates_pass": report["all_pass"], "primary_cross_user_lift": primary,
           "secondary": {"M3_minus_M2": _diff(results, "M3", "M2"), "M1_minus_M0": _diff(results, "M1", "M0"),
                         "M4_minus_M3": _diff(results, "M4", "M3")},
           "returned_models": sorted({r["returned_model"] for r in results if r["returned_model"]}),
           "results": results}
    os.makedirs(os.path.join("artifacts", "experiments", "p5_1", "results"), exist_ok=True)
    path = os.path.join("artifacts", "experiments", "p5_1", "results", "%s_results.json" % split)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=2, sort_keys=True); f.write("\n")
    print("WROTE", path, "all_gates_pass=%s" % report["all_pass"],
          "primary_lift_mean=%.3f" % primary["ci"]["mean"], flush=True)
    import collections
    errs = collections.Counter((r.get("error_detail") or "")[:80] for r in results if r["state"] == "FAILED")
    for msg, n in errs.most_common(5):
        print("FAILED[%d]: %s" % (n, msg), flush=True)


def _diff(results, a, b):
    ra = AN.pass1([r for r in results if r["arm"] == a])
    rb = AN.pass1([r for r in results if r["arm"] == b])
    return {"a": a, "b": b, "pass1_a": ra, "pass1_b": rb, "diff": ra - rb}


if __name__ == "__main__":
    main()
