"""Retrieval + injection pipeline (handoff §5.3/§8). Ordered stages: private search -> shared search
-> permission -> repo/path -> language/framework -> dependency/version -> applies/does-not-apply ->
validity/expiry -> supersession/conflict -> rerank -> dedup -> prompt-budget -> inject <=2. Private and
shared results are NEVER merged before access control. Persists every candidate, gate result,
rejection reason, and injected id."""
from __future__ import annotations
from . import gates as G

REJECTIONS = ("unauthorized_org", "unauthorized_user", "unauthorized_repo", "path_mismatch",
              "language_mismatch", "framework_mismatch", "dependency_mismatch", "branch_mismatch",
              "error_signature_mismatch", "out_of_scope", "expired", "deprecated", "quarantined",
              "superseded", "conflicting", "duplicate", "prompt_budget")

DEFAULTS = {"private_pool": 10, "shared_pool": 20, "max_injected": 2, "max_memory_tokens": 1200}


def _tokens(s):
    return max(1, len((s or "").split()))


def retrieve_and_inject(user, task, private_candidates, shared_candidates, now,
                        rerank_key=None, successor_valid_ids=None, cfg=None):
    """private_candidates: list of (episode, text). shared_candidates: list of (contract, text). Returns
    a decision dict with injected ids + full audit trail. rerank_key(item)->score (higher first)."""
    cfg = {**DEFAULTS, **(cfg or {})}
    successor_valid_ids = successor_valid_ids or set()
    audit = {"candidates": [], "rejections": {}, "passed": [], "injected": []}

    # 1-2 separate searches (already provided separately); cap pools
    priv = private_candidates[:cfg["private_pool"]]
    shar = shared_candidates[:cfg["shared_pool"]]

    passed = []
    # private: permission = ownership + repo
    for ep, text in priv:
        audit["candidates"].append(("private", ep.episode_id))
        ok, reason = G.private_read_ok(user, ep)
        if not ok:
            audit["rejections"][ep.episode_id] = reason
            continue
        passed.append(("private", ep, text, 1.0))
    # shared: full ordered gate chain
    for c, text in shar:
        cid = c.contract_id
        audit["candidates"].append(("shared", cid))
        ok, r = G.permission_gate(user, c)
        if not ok:
            audit["rejections"][cid] = r if r in REJECTIONS else ("unauthorized_%s" % r.split("_")[0] if "mismatch" not in r else r)
            audit["rejections"][cid] = r
            continue
        ok, r = G.scope_gate(task, c)
        if not ok:
            audit["rejections"][cid] = "out_of_scope" if "out_of_scope" in r or "repo" in r or "path" in r else r
            continue
        ok, r = G.validity_gate(task, c, now, successor_valid=(c.validity.superseded_by_contract_id in successor_valid_ids))
        if not ok:
            audit["rejections"][cid] = {"expired": "expired", "superseded": "superseded"}.get(r, r if r in REJECTIONS else "expired" if "expired" in r else r)
            continue
        passed.append(("shared", c, text, 2.0))

    audit["passed"] = [x[1].contract_id if x[0] == "shared" else x[1].episode_id for x in passed]

    # 11 rerank (prefer verified shared contract; higher base for shared)
    def score(item):
        base = item[3]
        if rerank_key:
            base += rerank_key(item)
        return base
    passed.sort(key=score, reverse=True)

    # 12 dedup by text
    seen = set(); dedup = []
    for it in passed:
        key = it[2][:80]
        if key in seen:
            audit["rejections"][it[1].contract_id if it[0] == "shared" else it[1].episode_id] = "duplicate"
            continue
        seen.add(key); dedup.append(it)

    # 13-14 budget + inject <=2
    budget = cfg["max_memory_tokens"]; injected = []
    for it in dedup:
        if len(injected) >= cfg["max_injected"]:
            break
        t = _tokens(it[2])
        if t > budget:
            iid = it[1].contract_id if it[0] == "shared" else it[1].episode_id
            audit["rejections"][iid] = "prompt_budget"
            continue
        budget -= t
        iid = it[1].contract_id if it[0] == "shared" else it[1].episode_id
        injected.append((iid, it[2]))
    audit["injected"] = [i[0] for i in injected]
    audit["abstained"] = len(injected) == 0
    audit["memory_tokens"] = cfg["max_memory_tokens"] - budget
    return {"injected": injected, "audit": audit}
