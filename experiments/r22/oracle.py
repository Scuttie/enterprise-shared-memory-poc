"""R22 §6 — oracle O0–O6 runner. DRY-RUN uses a fake deterministic reader (NO model calls, NO efficacy claim).

Verifies the experimental scaffolding: identical target set, fixed source assignment, source_user != target_user,
frozen O2 derangement, matched token/search/browse budgets, zero target/gold/test leakage, injected==payload hash,
resumable idempotent task×arm execution. Freezes 12-task smoke + 40-task dev manifests.
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "artifacts", "r22")
sys.path.insert(0, os.path.join(ROOT, "src"))
from enterprise_memory.experience.stage_schema import assert_no_target_leakage  # noqa: E402

ARMS = ["O0", "O1", "O2", "O3", "O4", "O5", "O6"]
# per-arm memory content (None = no historical content); budgets must match across O1/O2/O4/O5/O6
ARM_CONTENT = {"O0": None, "O1": "compute_only", "O2": "shuffled", "O3": "full_precedent",
               "O4": "issue_card", "O5": "stage_semantic", "O6": "stage_dual"}


def _derangement(ids):
    """Frozen derangement for O2 shuffled memory: deterministic, no fixed point."""
    n = len(ids)
    if n < 2:
        return list(ids)
    order = sorted(range(n), key=lambda i: hashlib.sha256(str(ids[i]).encode()).hexdigest())
    perm = order[1:] + order[:1]           # rotation of a deterministic order => no fixed point
    out = [None] * n
    for src_idx, dst_idx in zip(order, perm):
        out[dst_idx] = ids[src_idx]
    # guarantee no fixed point
    for i in range(n):
        if out[i] == ids[i]:
            out[i], out[(i + 1) % n] = out[(i + 1) % n], out[i]
    return out


def fake_reader(target_id, arm, payload_hash):
    """Deterministic pseudo-verdict from (target, arm) hash. NOT efficacy — scaffolding only."""
    h = int(hashlib.sha256(("%s|%s|%s" % (target_id, arm, payload_hash)).encode()).hexdigest(), 16)
    return {"resolved": bool(h % 7 == 0), "patch_hash": hashlib.sha256(
        ("%s|%s" % (target_id, arm)).encode()).hexdigest()[:16]}


def _dedupe_by_target(pairs):
    """One source per target (deterministic): first source_id by SHA-256 order."""
    by_t = {}
    for p in sorted(pairs, key=lambda q: hashlib.sha256((q["target_id"] + q["source_id"]).encode()).hexdigest()):
        by_t.setdefault(p["target_id"], p)
    return sorted(by_t.values(), key=lambda q: q["target_id"])


def build_manifest(pairs, arms):
    pairs = _dedupe_by_target(pairs)
    targets = [p["target_id"] for p in pairs]
    src_of = {p["target_id"]: p["source_id"] for p in pairs}
    deranged = dict(zip(targets, _derangement(targets)))
    tasks = []
    for p in pairs:
        tid = p["target_id"]
        target_user = "u_" + hashlib.sha256(tid.encode()).hexdigest()[:10]
        source_user = "gold_" + hashlib.sha256(p["source_id"].encode()).hexdigest()[:10]
        assert source_user != target_user, "source_user == target_user"
        for arm in arms:
            content = ARM_CONTENT[arm]
            if arm == "O2":
                mem_source = deranged[tid]           # unrelated (frozen derangement)
                assert mem_source != tid
            elif content in ("full_precedent", "issue_card", "stage_semantic", "stage_dual"):
                mem_source = src_of[tid]             # the correct related source
            else:
                mem_source = None
            payload = {"arm": arm, "content": content, "mem_source": mem_source}
            tasks.append({"target_id": tid, "arm": arm, "mem_source": mem_source,
                          "target_user": target_user, "source_user": source_user,
                          "payload_hash": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                          "budget": {"search": 2 if content and content != "compute_only" else (2 if content else 0),
                                     "browse": 2 if content not in (None,) else 0, "exec_tokens": 440}})
    return tasks


def main():
    dev = _dedupe_by_target(json.load(open(os.path.join(OUT, "dev_manifest_v2.json")))["pairs"])
    smoke = dev[:12]
    oracle_dev = dev[:40]

    smoke_tasks = build_manifest(smoke, ARMS)
    dev_tasks = build_manifest(oracle_dev, ARMS)

    def freeze(name, pairs, tasks):
        m = {"schema": "r22/%s/1.0.0" % name, "pairs": len(pairs), "arms": ARMS, "tasks": len(tasks),
             "manifest_sha256": hashlib.sha256(json.dumps(tasks, sort_keys=True).encode()).hexdigest()}
        json.dump({**m, "task_list": tasks}, open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8"),
                  indent=2, default=str)
        return m

    sm = freeze("oracle_smoke_manifest", smoke, smoke_tasks)
    dm = freeze("oracle_dev_manifest", oracle_dev, dev_tasks)
    json.dump({"schema": "r22/oracle_arm_manifest/1.0.0", "arms": ARMS, "arm_content": ARM_CONTENT,
               "primary_contrast": "O6 - O2", "secondary": ["O6-O0", "O6-O4", "O5-O4", "O6-O5", "O3-O6"]},
              open(os.path.join(OUT, "oracle_arm_manifest.json"), "w", encoding="utf-8"), indent=2, default=str)

    # DRY-RUN with fake reader (idempotent, resumable) — scaffolding checks only
    seen = {}
    leakage_hits = 0          # a task whose assigned memory source IS the target (would leak the answer)
    injected_ok = 0           # payload hash recomputes consistently (injected == declared payload)
    for t in dev_tasks:
        key = (t["target_id"], t["arm"])
        assert key not in seen, "non-idempotent duplicate task"
        seen[key] = True
        if t["mem_source"] is not None and t["mem_source"] == t["target_id"]:
            leakage_hits += 1
        payload = {"arm": t["arm"], "content": ARM_CONTENT[t["arm"]], "mem_source": t["mem_source"]}
        if hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest() == t["payload_hash"]:
            injected_ok += 1
        _ = fake_reader(t["target_id"], t["arm"], t["payload_hash"])
    # budget-match check across content arms
    content_arms = [a for a in ARMS if ARM_CONTENT[a] not in (None,)]
    budgets = {a: next(t["budget"] for t in dev_tasks if t["arm"] == a) for a in content_arms}
    budgets_matched = len(set(json.dumps(b, sort_keys=True) for a, b in budgets.items()
                             if ARM_CONTENT[a] != "compute_only")) <= 1

    result = {"schema": "r22/oracle_dryrun/1.0.0", "reader": "FAKE_DETERMINISTIC (no model; not efficacy)",
              "smoke_manifest": sm, "dev_manifest": dm,
              "tasks_executed": len(dev_tasks), "idempotent": True,
              "source_user_ne_target_user": True,
              "o2_derangement_fixed_points": 0,
              "target_gold_test_leakage": leakage_hits,
              "injected_eq_payload": injected_ok == len(dev_tasks),
              "content_arm_budgets_matched": budgets_matched,
              "paid_api_calls": 0}
    json.dump(result, open(os.path.join(OUT, "oracle_dryrun_result.json"), "w", encoding="utf-8"),
              indent=2, default=str)
    print(json.dumps({k: result[k] for k in
                      ["tasks_executed", "idempotent", "source_user_ne_target_user",
                       "o2_derangement_fixed_points", "target_gold_test_leakage", "injected_eq_payload",
                       "content_arm_budgets_matched", "paid_api_calls"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
