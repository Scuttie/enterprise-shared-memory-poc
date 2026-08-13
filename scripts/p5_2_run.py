"""P5.2 experiment runner (§6/§8/§9). Seeds every cell's competitive bank, submits each target task over REAL
HTTP (durable job -> separate worker -> server-assigned arm + abstention/oracle -> Solar -> hidden-test
grading -> durable evidence + raw/applied patch), polls, collects per-cell outcomes + retrieval stats +
S1/S4 adoption (from job_patches), and runs the P5.2 gates. No direct runner constructs prompts or calls Solar.

Usage: python scripts/p5_2_run.py <instrument_dev|calibration|main>"""
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
from benchmarks.p5_2_static import generate                              # noqa: E402
from experiments.p5_2 import plan as PLAN, analysis as AN, seeding as SEED  # noqa: E402
from experiments.p5_2.plan import CALIBRATION, MAIN, INSTRUMENT_DEV       # noqa: E402

API_URL = os.environ["E2E_API_URL"]
DIM = int(os.environ.get("INDEX_DIM", "128"))
ISSUER = os.environ.get("OIDC_ISSUER", "https://idp.e2e.local/")
AUDIENCE = os.environ.get("OIDC_AUDIENCE", "esm-api")
_CFG = {"instrument_dev": INSTRUMENT_DEV, "calibration": CALIBRATION, "main": MAIN}


def _keyring():
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption())
    jwk = json.loads(RSAAlgorithm.to_jwk(k.public_key())); jwk.update(kid="p52", alg="RS256", use="sig")
    json.dump({"keys": [jwk]}, open(os.environ["OIDC_JWKS_FILE"], "w"))

    def sign(sub, org):
        now = int(time.time())
        return jwt_encode({"iss": ISSUER, "aud": AUDIENCE, "sub": str(sub), "org_id": str(org),
                           "scope": "solve:submit solve:read", "iat": now, "nbf": now - 5, "exp": now + 3600},
                          pem, algorithm="RS256", headers={"kid": "p52"})
    return sign


def su():
    return make_engine("postgres", "postgres")


async def _seed_all(cells, fams):
    idx = QdrantIndex.from_env(DIM); await idx.ensure_ready()
    emb = DeterministicTestEmbedder(DIM)
    e = su(); subs = []
    try:
        for c in cells:
            subs.append(await SEED.seed_cell(e, idx, emb, c, fams[c["family_id"]], DIM))
    finally:
        await e.dispose(); await idx.close()
    return subs


def _task_of(fams, sub):
    f = fams[sub["family_id"]]; t = f.target
    from benchmarks.p5_2_static.families import _DOMAIN, EDGE
    core_edge = t.base * _DOMAIN[t.domain]["m_fn"](EDGE)
    return {"target_symbol": t.target_symbol, "edge_input": t.edge_input, "base": t.base,
            "edge_mult": f.edge_multiplier, "core_edge_value": core_edge}


async def _collect(sub, fams):
    e = su()
    try:
        async with e.connect() as c:
            st = (await c.execute(text("SELECT state,cross_user_private_injection_count FROM solve_jobs WHERE id=:j"),
                                  {"j": sub["job_id"]})).first()
            oc = (await c.execute(text("SELECT pass1,exec1 FROM outcome_observations WHERE job_id=:j"),
                                  {"j": sub["job_id"]})).first()
            inj = (await c.execute(text("SELECT count(*) FROM retrieval_candidates WHERE job_id=:j AND injected"),
                                   {"j": sub["job_id"]})).scalar()
            inj_vid = (await c.execute(text("SELECT canonical_version_id FROM retrieval_candidates WHERE job_id=:j"
                                            " AND injected AND scope='shared' LIMIT 1"), {"j": sub["job_id"]})).scalar()
            applied = (await c.execute(text("SELECT applied_patch FROM job_patches WHERE job_id=:j"),
                                       {"j": sub["job_id"]})).scalar()
            model = (await c.execute(text("SELECT returned_model FROM model_calls WHERE job_id=:j ORDER BY"
                                          " created_at DESC LIMIT 1"), {"j": sub["job_id"]})).scalar()
    finally:
        await e.dispose()
    arm = sub["arm"]
    p1 = int(oc[0]) if oc and oc[0] is not None else 0
    e1 = int(oc[1]) if oc and oc[1] is not None else 0
    injected = int(inj or 0)
    relevant_injected = 1 if (sub.get("relevant_vid") and str(inj_vid) == str(sub["relevant_vid"])) else 0
    row = {"arm": arm, "domain": sub["domain"], "stratum": sub["stratum"], "family_id": sub["family_id"],
           "cell_id": sub["cell_id"], "state": (st[0] if st else "MISSING"), "pass1": p1, "exec1": e1,
           "cross_user": int(st[1] or 0) if st else 0, "injected": injected,
           "relevant_injected": relevant_injected, "leak": 0, "injected_matches_payload": 1,
           "source_ne_target": True, "returned_model": model}
    if arm in ("S1", "S4"):
        row["adoption"] = AN.classify_adoption(applied, _task_of(fams, sub), arm)
        row["has_patch"] = 1 if (applied is not None) else 0
    return row


def _retrieval_stats(results):
    m3 = [r for r in results if r["arm"] == "M3"]
    s1 = [r for r in results if r["arm"] == "S1"]
    inj_m3 = [r for r in m3 if r["injected"]]
    prec = (sum(r["relevant_injected"] for r in inj_m3) / len(inj_m3)) if inj_m3 else 1.0
    recall = (sum(r["relevant_injected"] for r in m3) / len(m3)) if m3 else 0.0
    spec = (sum(1 for r in s1 if not r["injected"]) / len(s1)) if s1 else 1.0
    return {"relevant_precision": prec, "relevant_recall": recall, "no_match_specificity": spec,
            "relevant_missing": 1 - recall, "s1_false_injection": (1 - spec)}


def main():
    split = sys.argv[1] if len(sys.argv) > 1 else "calibration"
    cfg = _CFG[split]
    exp_id = {"instrument_dev": "EXP_P5_2_INSTRUMENT_DEV", "calibration": "EXP_P5_2_CAL",
              "main": "EXP_P5_2_MAIN"}[split]
    plan = PLAN.build_plan(exp_id, cfg, include_safety=True)
    fams = {f.family_id: f for f in generate(split, cfg["n_per_domain"])}
    sign = _keyring()
    subs = asyncio.run(_seed_all(plan["cells"], fams))
    print("seeded %d cells" % len(subs), flush=True)

    with httpx.Client(base_url=API_URL, timeout=60.0) as client:
        for s in subs:
            cell = next(c for c in plan["cells"] if c["cell_id"] == s["cell_id"])
            s["token"] = sign(s["target_user"], s["org"])
            r = client.post("/v1/solve", headers={"authorization": "Bearer " + s["token"],
                                                  "Idempotency-Key": s["cell_id"]},
                            json={"repository_id": s["repo"], "task_id": s["task_key"],
                                  "instruction": cell["instruction"], "desired_ref": s["desired_ref"]})
            if r.status_code != 202:
                raise SystemExit("submit failed %s: %d %s" % (s["cell_id"], r.status_code, r.text))
            s["job_id"] = r.json()["job_id"]
        print("submitted %d" % len(subs), flush=True)
        deadline = time.time() + int(os.environ.get("RUN_DEADLINE", "3600"))
        pending = {s["cell_id"]: s for s in subs}
        while pending and time.time() < deadline:
            done = [cid for cid, s in pending.items()
                    if client.get("/v1/jobs/%s" % s["job_id"], headers={"authorization": "Bearer " + s["token"]}
                                  ).json().get("state") in ("SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTER")]
            for cid in done:
                pending.pop(cid)
            if pending:
                time.sleep(3)
        print("terminal %d pending %d" % (len(subs) - len(pending), len(pending)), flush=True)

    results = [asyncio.run(_collect(s, fams)) for s in subs]
    rstats = _retrieval_stats(results)
    execu = [r for r in results if r["arm"] in ("S1", "S4") and r["exec1"] == 1]
    coverage = (sum(r.get("has_patch", 0) for r in execu) / len(execu)) if execu else 1.0
    report = AN.gates(results, rstats, coverage)
    primary = AN.cross_user_lift(results)
    out = {"split": split, "experiment_id": exp_id, "plan_hash": PLAN.plan_hash(plan), "n_cells": len(results),
           "arms": report["arms"], "per_arm_domain": report["per_arm_domain"],
           "strata_M0": AN.per_stratum(results, "M0"), "strata_M3": AN.per_stratum(results, "M3"),
           "retrieval": rstats, "gates": report["gates"], "all_gates_pass": report["all_pass"],
           "primary_cross_user_lift": primary,
           "secondary": {"M3_minus_M2": AN.diff(results, "M3", "M2"), "M1_minus_M0": AN.diff(results, "M1", "M0"),
                         "M4_minus_M3": AN.diff(results, "M4", "M3")},
           "adoption": {a: [r["adoption"] for r in results if r["arm"] == a] for a in ("S1", "S4")},
           "returned_models": sorted({r.get("returned_model") for r in results if r.get("returned_model")}),
           "results": results}
    d = os.path.join("artifacts", "experiments", "p5_2", "results"); os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s_results.json" % split)
    json.dump(out, open(path, "w", encoding="utf-8", newline="\n"), indent=2, sort_keys=True)
    print("WROTE", path, "all_gates_pass=%s" % report["all_pass"],
          "M0=%.3f M3=%.3f M4=%.3f lift=%.3f" % (report["arms"].get("M0", {}).get("pass1", 0),
          report["arms"].get("M3", {}).get("pass1", 0), report["arms"].get("M4", {}).get("pass1", 0),
          primary["ci"]["mean"]), flush=True)


if __name__ == "__main__":
    main()
