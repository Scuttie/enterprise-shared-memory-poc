"""Combine chunked safety raw results (§13) -> per-arm Pass@1, harm vs S0, and evidence-based memory-induced
loss classification. Pure (safety module + patch_forensics + committed source_bank). Usage: python
scripts/bigcode_r2_safety_combine.py"""
import collections
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments.bigcode_r2 import safety as SF   # noqa: E402
from experiments import patch_forensics as PF      # noqa: E402

ART = os.path.join("artifacts", "bigcode_r2")


def main():
    facts = {f["source_task"]: f for f in json.load(open(os.path.join(ART, "source_bank.json"),
                                                        encoding="utf-8"))["facts"]}
    src_sig = {s: {k: set(facts[s].get(k, [])) for k in ("imports", "apis", "operations", "control_flow")}
               for s in facts}
    raws = sorted(glob.glob(os.path.join(ART, "results", "safety_raw.*.json")))
    if not raws:
        raise SystemExit("no safety raw chunks")
    results, seen = [], set()
    for f in raws:
        for r in json.load(open(f, encoding="utf-8"))["results"]:
            k = (r["arm"], r["tid"])
            if k in seen:
                continue
            seen.add(k); results.append(r)
    by = collections.defaultdict(list)
    for r in results:
        by[r["arm"]].append(r)
    p1 = lambda a: (sum(x["pass1"] for x in by.get(a, [])) / len(by[a])) if by.get(a) else 0.0
    s0 = {r["tid"]: r for r in by.get("S0", [])}
    arms, transfer = {}, {}
    for a in SF.ARMS:
        rs = by.get(a, [])
        arms[a] = {"name": SF.NAMES[a], "n": len(rs), "pass1": round(p1(a), 4),
                   "exec1": round(sum(x["exec1"] for x in rs) / max(1, len(rs)), 4),
                   "harm_vs_S0": round(p1("S0") - p1(a), 4)}
        if a == "S0":
            continue
        counts = {c: 0 for c in PF.CLASSES}; losses = 0
        for r in rs:
            b = s0.get(r["tid"])
            if b and b["pass1"] == 1 and r["pass1"] == 0:
                losses += 1
                cls, _ = PF.classify_loss(r.get("applied_patch"), b.get("applied_patch"),
                                          src_sig.get(r.get("assigned_source")), injected=bool(r["injected"]),
                                          exec_ok=bool(r["exec1"]))
                counts[cls] += 1
        transfer[a] = {"memory_induced_losses": losses, "loss_classes": {k: v for k, v in counts.items() if v},
                       "adoption_total": sum(counts[c] for c in PF.CLASSES[:4])}
    out = {"experiment": "BIGCODE_R2_SAFETY", "n_job_results": len(results),
           "cross_user_private_injection": sum(r["cross_user"] for r in results),
           "arms_pass1": {a: arms[a]["pass1"] for a in SF.ARMS}, "arms": arms, "transfer": transfer,
           "chunks_combined": [os.path.basename(f) for f in raws]}
    json.dump(out, open(os.path.join(ART, "results", "safety_results.json"), "w", encoding="utf-8",
                        newline="\n"), indent=2, sort_keys=True)
    print("SAFETY arms_pass1:", out["arms_pass1"], flush=True)
    print("harm vs S0:", {a: arms[a]["harm_vs_S0"] for a in SF.ARMS}, flush=True)


if __name__ == "__main__":
    main()
