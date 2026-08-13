"""REALBENCH-R1.1 diagnostic runner (§2). Reuses the observed 120 MBPP+ main targets. Seeds diagnostic arms
D0-D7 (D8 aliases D1) through the REAL HTTP -> worker -> retrieval -> Solar -> OFFICIAL MBPP+ grader path with
the PINNED PRODUCTION embedder, then reports DESCRIPTIVE mechanism stats only (no confirmatory p-value):
Pass@1, gain/loss vs D0, injected tokens, source-ID agreement, AST/API adoption, retrieval/abstention, latency.

Usage: EMBEDDER=st python scripts/realbench_r11_run.py"""
import asyncio
import collections
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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from enterprise_memory.persistence.database import make_engine            # noqa: E402
from enterprise_memory.indexing.qdrant_indexes import QdrantIndex          # noqa: E402
from enterprise_memory.service.ci_container import _embedder               # noqa: E402
from experiments.realbench_r1 import experiment as X, grader as G, diagnostic as D, diag_seeding as S  # noqa: E402
from experiments import patch_forensics as PF                             # noqa: E402

API_URL = os.environ["E2E_API_URL"]
ISSUER = os.environ.get("OIDC_ISSUER", "https://idp.e2e.local/")
AUDIENCE = os.environ.get("OIDC_AUDIENCE", "esm-api")
EXP = "REALBENCH_R1_1_DIAGNOSTIC"


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


async def _collect(job_id, arm, tid, assigned):
    e = su()
    try:
        async with e.connect() as c:
            oc = (await c.execute(text("SELECT pass1,exec1 FROM outcome_observations WHERE job_id=:j"),
                                  {"j": job_id})).first()
            inj = (await c.execute(text("SELECT count(*) FROM retrieval_candidates WHERE job_id=:j AND injected"),
                                   {"j": job_id})).scalar()
            cand = (await c.execute(text("SELECT count(*) FROM retrieval_candidates WHERE job_id=:j"),
                                    {"j": job_id})).scalar()
            applied = (await c.execute(text("SELECT applied_patch FROM job_patches WHERE job_id=:j"),
                                       {"j": job_id})).scalar()
            model = (await c.execute(text("SELECT returned_model,input_tokens,output_tokens FROM model_calls "
                                          "WHERE job_id=:j ORDER BY created_at DESC LIMIT 1"), {"j": job_id})).first()
            cross = (await c.execute(text("SELECT cross_user_private_injection_count FROM solve_jobs WHERE id=:j"),
                                     {"j": job_id})).scalar()
    finally:
        await e.dispose()
    return {"arm": arm, "tid": tid, "assigned_source": assigned,
            "pass1": int(oc[0]) if oc and oc[0] is not None else 0,
            "exec1": int(oc[1]) if oc and oc[1] is not None else 0,
            "injected": int(inj or 0), "candidates": int(cand or 0),
            "applied_patch": applied, "returned_model": (model[0] if model else None),
            "in_tok": (model[1] if model else None), "out_tok": (model[2] if model else None),
            "cross_user": int(cross or 0)}


def main():
    sp = X.build_split()
    labels = D.relevance_labels(sp)
    dd = os.path.join("artifacts", "realbench_r1", "diag"); os.makedirs(dd, exist_ok=True)
    json.dump({"relevant": labels["relevant"], "irrelevant": labels["irrelevant"],
               "shuffled": labels["shuffled"], "labels_hash": D.labels_hash(labels),
               "target_relevance_overlap": labels["target_relevance_overlap"]},
              open(os.path.join(dd, "relevance_labels.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    src_sig = {s: labels["source_sig"][s] for s in labels["source_sig"]}

    sign = _sign()
    emb = _embedder()
    prov = emb.provenance() if hasattr(emb, "provenance") else {}
    print("embedder", prov.get("model_id"), "dim", getattr(emb, "dim", "?"), flush=True)
    idx = QdrantIndex.from_env(getattr(emb, "dim", None) or int(os.environ.get("INDEX_DIM", "384")))

    async def seed_all():
        await idx.ensure_ready()
        e = su(); out = []
        try:
            for arm in D.PHYSICAL:
                out.append(await S.seed_diag_arm(e, idx, emb, arm, labels, sp, EXP))
        finally:
            await e.dispose()
        return out
    arm_orgs = asyncio.run(seed_all())
    asyncio.run(idx.close())
    print("seeded %d arms x %d targets" % (len(arm_orgs), len(sp["main"])), flush=True)

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
                jobs.append({"arm": ao["arm"], "tid": tg["tid"], "job_id": r.json()["job_id"], "token": tok,
                             "assigned": tg["assigned_source"]})
        print("submitted %d jobs" % len(jobs), flush=True)
        deadline = time.time() + int(os.environ.get("RUN_DEADLINE", "6000"))
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

    results = [asyncio.run(_collect(j["job_id"], j["arm"], j["tid"], j["assigned"])) for j in jobs]
    out = _analyze(sp, labels, src_sig, results)
    json.dump(out, open(os.path.join(dd, "diagnostic_results.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    print("WROTE diagnostic_results.json", json.dumps(out["arms_pass1"]), flush=True)


def _analyze(sp, labels, src_sig, results):
    by = collections.defaultdict(list)
    for r in results:
        by[r["arm"]].append(r)
    p1 = lambda rs: (sum(x["pass1"] for x in rs) / len(rs)) if rs else 0.0
    arms_pass1 = {a: round(p1(by[a]), 4) for a in by}
    d0 = {r["tid"]: r for r in by.get("D0", [])}
    per_arm = {}
    for a, rs in by.items():
        gains = losses = 0
        adopt = {c: 0 for c in PF.CLASSES}
        inj_tok = []
        for r in rs:
            b = d0.get(r["tid"])
            if b:
                if b["pass1"] == 1 and r["pass1"] == 0:
                    losses += 1
                elif b["pass1"] == 0 and r["pass1"] == 1:
                    gains += 1
            if a != "D0" and r.get("assigned_source"):
                cls, _ = PF.classify_loss(r.get("applied_patch"), (b or {}).get("applied_patch"),
                                          src_sig.get(r["assigned_source"]), injected=bool(r["injected"]),
                                          exec_ok=bool(r["exec1"]))
                adopt[cls] += 1
            if r["out_tok"] is not None:
                inj_tok.append(r["out_tok"])
        per_arm[a] = {"n": len(rs), "pass1": round(p1(rs), 4),
                      "exec1": round(sum(x["exec1"] for x in rs) / max(1, len(rs)), 4),
                      "gains_vs_D0": gains, "losses_vs_D0": losses,
                      "injection_rate": round(sum(1 for x in rs if x["injected"]) / max(1, len(rs)), 4),
                      "mean_out_tokens": round(sum(inj_tok) / max(1, len(inj_tok)), 1) if inj_tok else 0,
                      "adoption_classes": {k: v for k, v in adopt.items() if v}}
    # D8 == D1 by construction
    per_arm["D8_alias"] = {"equals": "D1", "note": "TRUE_ORACLE_RELEVANT == RELEVANT_PLAIN by construction"}
    key_contrasts = {
        "relevant_minus_shuffled_D1_D5": round(arms_pass1.get("D1", 0) - arms_pass1.get("D5", 0), 4),
        "relevant_minus_irrelevant_D1_D6": round(arms_pass1.get("D1", 0) - arms_pass1.get("D6", 0), 4),
        "governed_minus_plain_D2_D1": round(arms_pass1.get("D2", 0) - arms_pass1.get("D1", 0), 4),
        "apicard_minus_plain_D3_D1": round(arms_pass1.get("D3", 0) - arms_pass1.get("D1", 0), 4),
        "rawtrace_minus_plain_D4_D1": round(arms_pass1.get("D4", 0) - arms_pass1.get("D1", 0), 4),
        "alwaystop1_minus_nomem_D7_D0": round(arms_pass1.get("D7", 0) - arms_pass1.get("D0", 0), 4),
        "relevant_minus_nomem_D1_D0": round(arms_pass1.get("D1", 0) - arms_pass1.get("D0", 0), 4)}
    return {"experiment": EXP, "note": "DESCRIPTIVE mechanism diagnostic on the observed 120 MBPP+ main; "
            "no confirmatory p-value (§2).", "n_targets": len(sp["main"]),
            "labels_hash": D.labels_hash(labels), "embedder": os.environ.get("EMBEDDER", "deterministic"),
            "returned_models": sorted({r["returned_model"] for r in results if r["returned_model"]}),
            "cross_user_private_injection": sum(r["cross_user"] for r in results),
            "arms_pass1": arms_pass1, "per_arm": per_arm, "key_contrasts": key_contrasts,
            "results": [{k: v for k, v in r.items() if k != "applied_patch"} for r in results]}


if __name__ == "__main__":
    main()
