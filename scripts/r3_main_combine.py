"""REALBENCH-R3 §18 — combine main raw chunks -> confirmatory analysis (H1/H2 + Holm + secondaries). ITT: a
target×arm missing (chunk/infra loss) is scored as a failure. Light (no ESM deps). Usage: python scripts/r3_main_combine.py"""
import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from experiments.actionable_memory_r3 import main_analysis as MA           # noqa: E402
from experiments.actionable_memory_r3.main_arms import MAIN_ARMS         # noqa: E402

ART = os.path.join(REPO, "artifacts", "actionable_memory_r3")


def main():
    rows, seen, bundle, all_t = [], set(), None, set()
    for f in sorted(glob.glob(os.path.join(ART, "results", "main_raw.*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        bundle = bundle or d.get("selected_bundle")
        for r in d["rows"]:
            k = (r["arm"], r["tid"])
            if k in seen:
                continue
            seen.add(k); rows.append(r); all_t.add(r["tid"])
    if not rows:
        raise SystemExit("no main raw chunks")
    # ITT: fill missing (arm,target) as failures
    for arm in MAIN_ARMS:
        for t in all_t:
            if (arm, t) not in seen:
                rows.append({"arm": arm, "tid": t, "pass1": 0, "exec1": 0, "applied_patch": None,
                             "injected": 0, "cross_user": 0, "state": "MISSING"})
    res = MA.analyze(rows)
    res["selected_bundle"] = bundle
    res["cross_user_private_injection"] = sum(r.get("cross_user", 0) for r in rows)
    res["n_job_rows"] = len(rows)
    json.dump(res, open(os.path.join(ART, "results", "main_results.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    print("arms_pass1:", res["arms_pass1"], flush=True)
    for k, v in res["primary"].items():
        print(k, "diff=%.4f" % v["diff"], "p=%.4f" % v["mcnemar"]["p_value"], "holm_reject=%s" % v["holm"]["reject"],
              "CI[%.3f,%.3f]" % (v["ci"]["lo"], v["ci"]["hi"]), flush=True)
    print("reject_any_primary:", res["reject_any_primary"], flush=True)


if __name__ == "__main__":
    main()
