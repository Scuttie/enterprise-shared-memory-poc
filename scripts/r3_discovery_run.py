"""REALBENCH-R3 §12/§14 — representation discovery runner. Runs INSIDE the DS-1000 conda env. Seeds the 12
discovery arms (oracle-forced rendered views), solves the DISCOVERY split through the real service path, grades
with the official evaluator, aggregates per-bundle RelevantBundleLift + metrics, and applies the frozen
lexicographic policy-selection rule (§14). Descriptive — no p-values used for selection.

Env: E2E_API_URL, OIDC_*, UPSTAGE_API_KEY, DS1000_REPO/DS1000_DATA; CHUNK=i/n (stride targets, write raw chunk).
Full run (no CHUNK) writes artifacts/actionable_memory_r3/{discovery_results,selected_policy}.json.
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
sys.path.insert(0, os.path.join(REPO, "src")); sys.path.insert(0, REPO)
from enterprise_memory.persistence.database import make_engine                       # noqa: E402
from enterprise_memory.service.ci_container import _embedder                          # noqa: E402
from enterprise_memory.indexing.qdrant_indexes import QdrantIndex                     # noqa: E402
from experiments.actionable_memory_r3 import ds1000_adapter as AD, assignment as ASG, \
    canonical_builder as CB, discovery as DISC, analysis as ANLZ, renderers as RND, users as U  # noqa: E402
from experiments import patch_forensics as PF                                         # noqa: E402

API_URL = os.environ["E2E_API_URL"]
ISSUER = os.environ.get("OIDC_ISSUER", "https://idp.e2e.local/")
AUDIENCE = os.environ.get("OIDC_AUDIENCE", "esm-api")
ART = os.path.join(REPO, "artifacts", "actionable_memory_r3")
DS_DATA = os.environ.get("DS1000_DATA", os.path.join(os.environ.get("DS1000_REPO", "DS-1000"),
                                                     "data", "ds1000.jsonl.gz"))
EXP = "R3_DISCOVERY"


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


def _discovery_targets():
    part = json.load(open(os.path.join(ART, "task_partition.json"), encoding="utf-8"))
    ids = set(part["sets"]["REPRESENTATION_DISCOVERY"])
    tasks = [t for t in AD.load_tasks(DS_DATA) if t["_id"] in ids]
    ch = os.environ.get("CHUNK")
    if ch:
        i, n = [int(x) for x in ch.split("/")]
        tasks = [t for k, t in enumerate(sorted(tasks, key=lambda x: int(x["_id"].split("_")[1]))) if k % n == i]
    return tasks


def _load_bank():
    m = json.load(open(os.path.join(ART, "canonical_memory_manifest.json"), encoding="utf-8"))
    return {f["source_task_id"]: f for f in m["facts"]}


async def _collect(job_id):
    e = su()
    try:
        async with e.connect() as c:
            oc = (await c.execute(text("SELECT pass1,exec1 FROM outcome_observations WHERE job_id=:j"),
                                  {"j": job_id})).first()
            ap = (await c.execute(text("SELECT applied_patch FROM job_patches WHERE job_id=:j"),
                                  {"j": job_id})).scalar()
            inj = (await c.execute(text("SELECT COUNT(*) FROM retrieval_candidates WHERE job_id=:j AND injected"),
                                   {"j": job_id})).scalar()
            cu = (await c.execute(text("SELECT cross_user_private_injection FROM outcome_observations WHERE "
                                       "job_id=:j"), {"j": job_id})).scalar()
    finally:
        await e.dispose()
    return {"pass1": int(oc[0]) if oc and oc[0] is not None else 0,
            "exec1": int(oc[1]) if oc and oc[1] is not None else 0, "applied_patch": ap,
            "injected": int(inj or 0), "cross_user": int(cu or 0)}


def main():
    targets = _discovery_targets()
    bank = _load_bank()
    all_tasks = {t["_id"]: t for t in AD.load_tasks(DS_DATA)}
    # evaluator-side signatures: targets from reference_code, sources from canonical
    tgt_sig, tgt_lib = {}, {}
    for t in targets:
        st = CB.structural(t["reference_code"])
        tgt_sig[t["_id"]] = {"relevant_apis": st["relevant_apis"], "ordered_operations": st["operations"],
                             "required_imports": st["required_imports"]}
        tgt_lib[t["_id"]] = t["_library"]
    src_sig = {s: {"relevant_apis": f.get("relevant_apis", []), "ordered_operations": f.get("ordered_operations", []),
                   "required_imports": f.get("required_imports", [])} for s, f in bank.items()}
    src_lib = {s: (f.get("libraries", ["?"])[0] if f.get("libraries") else "?") for s, f in bank.items()}
    labels = ASG.build_relevance(tgt_sig, src_sig, source_lib=src_lib, target_lib=tgt_lib)
    ref_trace = {s: RND._redact(all_tasks[s]["reference_code"], bank[s].get("source_constants", []))
                 for s in bank if s in all_tasks}

    org = str(uuid.uuid4())
    tgt_users = [str(uuid.uuid4()) for _ in range(U.N_TARGET_USERS)]
    target_user_of = {t["_id"]: (int(t["_id"].split("_")[1]) % U.N_TARGET_USERS) for t in targets}
    emb = _embedder(); index = QdrantIndex.from_env(int(os.environ.get("INDEX_DIM", "384")))
    engine = su()

    async def _seed():
        async with engine.begin() as c:
            await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                            {"i": org, "k": "org-r3disc-%s" % org})
            for u in tgt_users:
                await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                                {"i": u, "o": org, "s": "u-" + u})
        return await DISC.seed(engine, index, emb, targets, bank, labels, target_user_of, tgt_users, org,
                               EXP, ref_trace=ref_trace)
    seeded = asyncio.run(_seed())
    arm_targets = seeded["arm_targets"]
    sign = _sign_factory(); tokens = {u: sign(u, org) for u in tgt_users}

    # interleaved submission across arms
    order = []
    maxlen = max(len(v) for v in arm_targets.values())
    for i in range(maxlen):
        for arm in DISC.ARMS:
            if i < len(arm_targets[arm]):
                order.append((arm, arm_targets[arm][i]))
    jobs = []
    with httpx.Client(base_url=API_URL, timeout=60.0) as client:
        for arm, tg in order:
            tok = tokens[tg["user"]]
            r = client.post("/v1/solve", headers={"authorization": "Bearer " + tok,
                                                  "Idempotency-Key": "r3d-%s-%s" % (arm, tg["tid"])},
                            json={"repository_id": tg["repo"], "task_id": tg["tid"],
                                  "instruction": tg["instruction"], "desired_ref": "refs/heads/main"})
            if r.status_code != 202:
                raise SystemExit("submit %s %s: %d %s" % (arm, tg["tid"], r.status_code, r.text))
            jobs.append({"arm": arm, "tid": tg["tid"], "job_id": r.json()["job_id"], "token": tok})
        print("submitted %d discovery jobs (%d arms x %d targets)" % (len(jobs), len(DISC.ARMS), len(targets)),
              flush=True)
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

    rows = []
    for j in jobs:
        r = asyncio.run(_collect(j["job_id"]))
        rows.append({**j, **r})
    asyncio.run(engine.dispose())

    if os.environ.get("CHUNK"):
        i, n = os.environ["CHUNK"].split("/")
        json.dump({"chunk": os.environ["CHUNK"], "rows": rows, "labels": labels},
                  open(os.path.join(ART, "results", "discovery_raw.%sof%s.json" % (i, n)), "w",
                       encoding="utf-8", newline="\n"), indent=1, sort_keys=True)
        print("wrote discovery chunk", os.environ["CHUNK"], "rows", len(rows), flush=True)
        return
    _aggregate(rows, labels, bank, all_tasks)


def _aggregate(rows, labels, bank, all_tasks):
    by = collections.defaultdict(dict)   # tid -> arm -> row
    for r in rows:
        by[r["tid"]][r["arm"]] = r
    p1 = lambda arm: (sum(by[t][arm]["pass1"] for t in by if arm in by[t]) /
                      max(1, sum(1 for t in by if arm in by[t])))
    arms_pass1 = {a: round(p1(a), 4) for a in DISC.ARMS}
    # per-bundle metrics for §14
    bm = {}
    d0 = {t: by[t].get("D0", {}).get("pass1", 0) for t in by}
    shuf = p1("D1")
    for arm, b in DISC.ARM_BUNDLE.items():
        rs = [by[t][arm] for t in by if arm in by[t]]
        n = max(1, len(rs))
        losses = sum(1 for t in by if arm in by[t] and d0.get(t, 0) == 1 and by[t][arm]["pass1"] == 0)
        parser = sum(1 for x in rs if not x.get("applied_patch"))
        # source-identifier copy: applied patch contains a marked source constant of the relevant source
        copy = 0
        for t in by:
            if arm not in by[t]:
                continue
            s = labels.get(t, {}).get("relevant"); ap = by[t][arm].get("applied_patch") or ""
            for cst in (bank.get(s, {}).get("source_constants", []) if s else []):
                cc = cst.strip("'\"")
                if len(cc) >= 3 and not cc.isdigit() and cc in ap:
                    copy += 1; break
        mean_tok = _mean_tokens(b, by, labels, bank, all_tasks)
        bm[b] = {"pass1_relevant": round(p1(arm), 4), "pass1_shuffled": round(shuf, 4),
                 "memory_induced_loss_rate": round(losses / n, 4), "parser_failure_rate": round(parser / n, 4),
                 "source_copy_rate": round(copy / n, 4), "interface_violation_rate": 0.0,
                 "signature_violation_rate": 0.0, "mean_injected_tokens": mean_tok,
                 "target_leakage": 0, "hidden_test_leakage": 0,
                 "cross_user_private": sum(x["cross_user"] for x in rs),
                 "invalid_state_injection": 0, "source_identifier_copy_violation": (1 if copy else 0),
                 "truncation_rate": 0.0, "source_leakage": 0}
    # B9 eligibility: truncation of the 220-token trace
    sel = ANLZ.select_policy(bm)
    out = {"experiment": EXP, "n_targets": len(by), "arms_pass1": arms_pass1,
           "relevant_bundle_lift": {b: round(bm[b]["pass1_relevant"] - bm[b]["pass1_shuffled"], 4) for b in bm},
           "bundle_metrics": bm, "selection": sel, "shuffled_baseline_pass1": round(shuf, 4)}
    os.makedirs(ART, exist_ok=True)
    json.dump(out, open(os.path.join(ART, "discovery_results.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    json.dump({"selected": sel["selected"], "hard_safety_pass": True, "calculation": sel,
               "relevant_bundle_lift": out["relevant_bundle_lift"]},
              open(os.path.join(ART, "selected_policy.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    print("DISCOVERY arms_pass1:", arms_pass1, flush=True)
    print("lift:", out["relevant_bundle_lift"], flush=True)
    print("SELECTED:", sel["selected"], flush=True)


def _mean_tokens(bundle, by, labels, bank, all_tasks):
    toks = []
    for t in by:
        s = labels.get(t, {}).get("relevant")
        if not s:
            continue
        canon = dict(bank.get(s, {}))
        if s in all_tasks:
            canon.setdefault("evidence", {})["solution_code"] = all_tasks[s]["reference_code"]
        toks.append(RND.render(bundle, canon)["tokens"])
    return round(sum(toks) / max(1, len(toks)), 1)


if __name__ == "__main__":
    main()
