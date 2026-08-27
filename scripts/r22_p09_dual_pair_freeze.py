#!/usr/bin/env python3
"""R22-P0.9.1 §4 — freeze the source relation for the 3 dual-pair dev targets BEFORE any gradeability outcome.

Rule (outcome-blind): (1) retain an existing frozen ORIGINAL_P2 O2 source assignment when it is among the competing
sources; (2) else keep only temporal-valid relations (source instance number < target instance number); (3) else
ascending sha256("REALBENCH_R22A_STAGE_ALIGNED_GRADEABLE_V1|"+target_id+"|"+source_id)."""
import hashlib
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts", "r22")
OUT = os.path.join(ROOT, "artifacts", "r22_p09")
EXP = "REALBENCH_R22A_STAGE_ALIGNED_GRADEABLE_V1"
DUAL = ["astropy__astropy-15082", "sympy__sympy-12426", "sympy__sympy-12427"]


def _num(iid):
    m = re.search(r"-(\d+)$", iid)
    return int(m.group(1)) if m else -1


def main():
    os.makedirs(OUT, exist_ok=True)
    pairs = json.load(open(os.path.join(ART, "dev_manifest_v2.json"), encoding="utf-8"))["pairs"]
    dev = json.load(open(os.path.join(ART, "oracle_dev_manifest.json"), encoding="utf-8"))["task_list"]
    # frozen ORIGINAL_P2 O2 source per target (if any)
    frozen_o2 = {}
    for t in dev:
        if t.get("arm") == "O2" and t.get("mem_source"):
            frozen_o2[t["target_id"]] = t["mem_source"]

    out = {}
    for tid in DUAL:
        competing = [{"source_id": p["source_id"], "relation_class": p["class"],
                      "temporal_valid": _num(p["source_id"]) < _num(tid)}
                     for p in pairs if p["target_id"] == tid]
        cand_ids = [c["source_id"] for c in competing]
        frozen = frozen_o2.get(tid)
        reason = None
        selected = None
        if frozen and frozen in cand_ids:
            selected, reason = frozen, "retained frozen ORIGINAL_P2 O2 assignment"
        else:
            valid = [c["source_id"] for c in competing if c["temporal_valid"]] or cand_ids
            selected = sorted(valid, key=lambda s: hashlib.sha256(("%s|%s|%s" % (EXP, tid, s)).encode()).hexdigest())[0]
            reason = ("temporal-valid + deterministic hash order" if len(valid) < len(cand_ids)
                      else "deterministic hash order (all temporal-valid)")
        sel_hash = hashlib.sha256(("%s|%s|%s" % (EXP, tid, selected)).encode()).hexdigest()
        out[tid] = {"target_id": tid, "competing_sources": competing, "frozen_o2_source": frozen,
                    "selected_source_id": selected, "selection_hash": sel_hash, "reason": reason}
        print("%-24s sources=%s frozen_o2=%s -> %s (%s)" % (tid, cand_ids, frozen, selected, reason))

    manifest = {"experiment": EXP, "rule": "retain frozen ORIGINAL_P2 -> temporal-valid -> sha256(EXP|target|source)",
                "targets": out}
    json.dump(manifest, open(os.path.join(OUT, "dual_pair_source_selection.json"), "w", encoding="utf-8"), indent=2)
    print("wrote dual_pair_source_selection.json")


if __name__ == "__main__":
    raise SystemExit(main())
