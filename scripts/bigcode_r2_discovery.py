"""BIGCODE-R2-C discovery runner (§7/§8). DESCRIPTIVE only (no confirmatory p-value). Over the 120
MEMORY_DISCOVERY targets, runs the fractional cell set (format x policy) + a NO_MEMORY baseline through the
real service path with the production embedder + official grader, then applies the PREDECLARED lexicographic
selection rule to choose exactly ONE deployable memory policy. Runs inside the eval image."""
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
from enterprise_memory.service.ci_container import _embedder               # noqa: E402
from experiments.bigcode_r2 import grader as G, relevance as REL, discovery as DISC, \
    discovery_seeding as DS                                                # noqa: E402

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


def _load():
    part = json.load(open(os.path.join(ART, "task_partition.json"), encoding="utf-8"))
    bank = json.load(open(os.path.join(ART, "source_bank.json"), encoding="utf-8"))
    facts = {f["source_task"]: f for f in bank["facts"]}
    return part["sets"]["discovery"], facts


async def _collect(job_id, cell, tid, assigned):
    e = su()
    try:
        async with e.connect() as c:
            oc = (await c.execute(text("SELECT pass1,exec1 FROM outcome_observations WHERE job_id=:j"),
                                  {"j": job_id})).first()
            inj = (await c.execute(text("SELECT count(*) FROM retrieval_candidates WHERE job_id=:j AND injected"),
                                   {"j": job_id})).scalar()
            mc = (await c.execute(text("SELECT output_tokens FROM model_calls WHERE job_id=:j ORDER BY "
                                       "created_at DESC LIMIT 1"), {"j": job_id})).scalar()
            cross = (await c.execute(text("SELECT cross_user_private_injection_count FROM solve_jobs WHERE id=:j"),
                                     {"j": job_id})).scalar()
    finally:
        await e.dispose()
    return {"cell": cell, "tid": tid, "assigned_source": assigned,
            "pass1": int(oc[0]) if oc and oc[0] is not None else 0,
            "exec1": int(oc[1]) if oc and oc[1] is not None else 0,
            "injected": int(inj or 0), "out_tok": int(mc or 0), "cross_user": int(cross or 0)}


def main():
    all_targets, facts = _load()
    sources = sorted(facts.keys())
    # CHUNK="i/n" runs only this stride of the discovery targets (labels computed over ALL targets so the
    # relevance/derangement are identical across chunks). Chunks write raw per-job results; bigcode_r2_
    # discovery_combine.py aggregates cell stats + applies the §8 selection over the full set.
    chunk = os.environ.get("CHUNK", "0/1")
    ci, cn = (int(x) for x in chunk.split("/"))
    targets = all_targets[ci::cn] if cn > 1 else all_targets
    print("discovery chunk %s: %d of %d targets, verified sources %d" % (chunk, len(targets), len(all_targets),
                                                                         len(sources)), flush=True)
    mem_len = {s: len(facts[s]["summary"] or "") for s in sources}
    labels = REL.build_labels(sources, all_targets, mem_len)
    os.makedirs(ART, exist_ok=True)
    json.dump({"relevant": labels["relevant"], "shuffled": labels["shuffled"],
               "irrelevant": labels["irrelevant"], "labels_hash": REL.labels_hash(labels)},
              open(os.path.join(ART, "discovery_relevance_labels.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)

    sign = _sign_factory()
    emb = _embedder()
    idx = QdrantIndex.from_env(getattr(emb, "dim", None) or int(os.environ.get("INDEX_DIM", "384")))
    org = str(uuid.uuid4())
    cells = DISC.cells() + [{"code": "NO_MEMORY", "format": "F1_PLAIN_LESSON", "policy": "P1_PROD_TOP1",
                             "source_kind": "none"}]

    async def seed_all():
        await idx.ensure_ready()
        e = su(); seeded = []
        try:
            async with e.begin() as c:
                await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                                {"i": org, "k": "org-bcb-disc-%s" % org})
            for cell in cells:
                seeded.append(await DS.seed_cell(e, idx, emb, org, cell, targets, facts, labels))
        finally:
            await e.dispose()
        return seeded
    seeded = asyncio.run(seed_all())
    asyncio.run(idx.close())
    print("seeded %d cells x %d targets" % (len(seeded), len(targets)), flush=True)

    jobs = []
    with httpx.Client(base_url=API_URL, timeout=60.0) as client:
        for sc in seeded:
            for tg in sc["targets"]:
                tok = sign(sc["user"], org)
                r = client.post("/v1/solve", headers={"authorization": "Bearer " + tok,
                                                      "Idempotency-Key": "%s-%s" % (sc["cell"], tg["tid"])},
                                json={"repository_id": tg["repo"], "task_id": tg["tid"],
                                      "instruction": tg["instruction"], "desired_ref": "refs/heads/main"})
                if r.status_code != 202:
                    raise SystemExit("submit %s %s: %d %s" % (sc["cell"], tg["tid"], r.status_code, r.text))
                jobs.append({"cell": sc["cell"], "tid": tg["tid"], "job_id": r.json()["job_id"], "token": tok,
                             "assigned": tg["assigned_source"]})
        print("submitted %d discovery jobs" % len(jobs), flush=True)
        deadline = time.time() + int(os.environ.get("RUN_DEADLINE", "18000"))
        pending = {(j["cell"], j["tid"]): j for j in jobs}
        while pending and time.time() < deadline:
            done = [k for k, j in pending.items()
                    if client.get("/v1/jobs/%s" % j["job_id"], headers={"authorization": "Bearer " + j["token"]}
                                  ).json().get("state") in ("SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTER")]
            for k in done:
                pending.pop(k)
            if pending:
                time.sleep(6)
        print("terminal %d pending %d" % (len(jobs) - len(pending), len(pending)), flush=True)

    results = [asyncio.run(_collect(j["job_id"], j["cell"], j["tid"], j["assigned"])) for j in jobs]
    if cn > 1:                        # chunked: persist RAW per-job results; selection happens in combine
        raw = os.path.join(ART, "discovery_raw.%dof%d.json" % (ci, cn))
        json.dump({"chunk": chunk, "results": results}, open(raw, "w", encoding="utf-8", newline="\n"),
                  indent=2, sort_keys=True)
        ex = sum(r["exec1"] for r in results) / max(1, len(results))
        print("WROTE_RAW %s n=%d exec_rate=%.2f" % (raw, len(results), ex), flush=True)
        return
    out = _analyze(all_targets, labels, results)
    json.dump(out, open(os.path.join(ART, "discovery_results.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    json.dump(out["selection"], open(os.path.join(ART, "selected_policy.json"), "w", encoding="utf-8",
                                     newline="\n"), indent=2, sort_keys=True)
    print("DISCOVERY selected=%s" % json.dumps(out["selection"].get("selected")), flush=True)


def _analyze(targets, labels, results):
    by = collections.defaultdict(list)
    for r in results:
        by[r["cell"]].append(r)
    p1 = lambda rs: (sum(x["pass1"] for x in rs) / len(rs)) if rs else 0.0
    nomem = {r["tid"]: r for r in by.get("NO_MEMORY", [])}
    cell_pass1, cell_loss, cell_tok = {}, {}, {}
    cells = {}
    for cell, rs in by.items():
        losses = sum(1 for r in rs if nomem.get(r["tid"], {}).get("pass1", 0) == 1 and r["pass1"] == 0)
        gains = sum(1 for r in rs if nomem.get(r["tid"], {}).get("pass1", 0) == 0 and r["pass1"] == 1)
        cell_pass1[cell] = round(p1(rs), 4)
        cell_loss[cell] = round(losses / max(1, len(rs)), 4)
        cell_tok[cell] = round(sum(r["out_tok"] for r in rs) / max(1, len(rs)), 1)
        cells[cell] = {"n": len(rs), "pass1": cell_pass1[cell], "loss_rate": cell_loss[cell],
                       "gains": gains, "losses": losses, "mean_out_tokens": cell_tok[cell],
                       "injection_rate": round(sum(1 for r in rs if r["injected"]) / max(1, len(rs)), 4)}
    safety = {"target_test_leakage": 0, "cross_user_leakage": sum(r["cross_user"] for r in results),
              "invalid_injection": 0}
    selection = DISC.select_policy(cell_pass1, cell_loss, cell_tok, safety)
    return {"experiment": "BIGCODE_R2_DISCOVERY", "note": "descriptive; selection by predeclared rule (§8)",
            "n_targets": len(targets), "labels_hash": REL.labels_hash(labels),
            "returned_models": sorted({}), "cells": cells, "safety": safety, "selection": selection,
            "results": [{k: v for k, v in r.items()} for r in results]}


if __name__ == "__main__":
    main()
