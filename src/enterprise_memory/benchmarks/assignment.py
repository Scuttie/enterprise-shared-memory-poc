"""Deterministic hash-based user assignment (§13). 8 users; source owner != target owner; the target
owner's private store must NOT contain the related source (enforced at eval time)."""
import hashlib
USERS = ["user_%02d" % i for i in range(8)]


def _h(s):
    return int(hashlib.sha256(s.encode()).hexdigest(), 16)


def assign(family_id):
    src = USERS[_h("src|" + family_id) % 8]
    tgt = USERS[_h("tgt|" + family_id) % 8]
    if tgt == src:
        tgt = USERS[(USERS.index(src) + 1) % 8]
    return {"source_owner": src, "target_owner": tgt}


def assignment_manifest(family_ids):
    a = {fid: assign(fid) for fid in family_ids}
    import json
    return {"assignment": a, "hash": "sha256:" + hashlib.sha256(json.dumps(a, sort_keys=True).encode()).hexdigest()[:24],
            "all_source_ne_target": all(v["source_owner"] != v["target_owner"] for v in a.values())}
