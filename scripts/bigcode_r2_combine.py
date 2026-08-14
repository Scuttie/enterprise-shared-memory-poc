"""Combine chunked raw per-job results (bigcode_r2_run.py CHUNK=i/n) into the final analysed results. Runs
the SAME _analyze over the union of all chunks so E1/E2/secondary/transfer are computed over the full split.
No model calls, no eval-image needed (pure analysis over committed artifacts + raw results).

Usage: python scripts/bigcode_r2_combine.py <calibration|main>"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments.bigcode_r2 import relevance as REL, users as U                    # noqa: E402
import scripts.bigcode_r2_run as RUN  # noqa: E402  (import _analyze + _load)

ART = os.path.join("artifacts", "bigcode_r2")


def main():
    split = sys.argv[1] if len(sys.argv) > 1 else "main"
    exp = "BIGCODE_R2_" + split.upper()
    part, facts, fmt, all_targets = RUN._load(split)
    sources = sorted(facts.keys())
    mem_len = {s: len(facts[s]["summary"] or "") for s in sources}
    labels = REL.build_labels(sources, all_targets, mem_len)
    U.build_assignment(sources, all_targets)
    src_sig = {s: {k: set(facts[s].get(k, [])) for k in ("imports", "apis", "operations", "control_flow")}
               for s in sources}

    raws = sorted(glob.glob(os.path.join(ART, "results", "%s_raw.*.json" % split)))
    if not raws:
        raise SystemExit("no raw chunks for %s" % split)
    results, seen = [], set()
    for f in raws:
        for r in json.load(open(f, encoding="utf-8"))["results"]:
            key = (r["arm"], r["tid"])
            if key in seen:                 # de-dup if chunks overlapped
                continue
            seen.add(key)
            results.append(r)
    print("combined %d chunks -> %d job results over %d targets" % (len(raws), len(results), len(all_targets)),
          flush=True)
    out = RUN._analyze(split, exp, part, all_targets, fmt, labels, src_sig, results)
    out["chunks_combined"] = [os.path.basename(f) for f in raws]
    path = os.path.join(ART, "results", "%s_results.json" % split)
    json.dump(out, open(path, "w", encoding="utf-8", newline="\n"), indent=2, sort_keys=True)
    print("WROTE", path, json.dumps(out.get("arms_pass1", {})), flush=True)
    if split == "main":
        print("E1(M2-M3)=%s p=%s | E2=%s" % (out["E1"]["diff"], out["E1"]["mcnemar"]["p_value"],
                                             out.get("E2", {}).get("diff")), flush=True)


if __name__ == "__main__":
    main()
