"""REALBENCH-R3 §12/§14 — combine chunked discovery raw results -> aggregate + frozen policy selection. Pure
(reads committed source bank + DS-1000 data). Usage: python scripts/r3_discovery_combine.py"""
import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src")); sys.path.insert(0, REPO)
from experiments.actionable_memory_r3 import ds1000_adapter as AD  # noqa: E402
import scripts.r3_discovery_run as DR  # noqa: E402

ART = os.path.join(REPO, "artifacts", "actionable_memory_r3")
DS_DATA = os.environ.get("DS1000_DATA", os.path.join(os.environ.get("DS1000_REPO", "DS-1000"),
                                                     "data", "ds1000.jsonl.gz"))


def main():
    rows, labels, seen = [], {}, set()
    for f in sorted(glob.glob(os.path.join(ART, "results", "discovery_raw.*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        labels.update(d.get("labels", {}))
        for r in d["rows"]:
            k = (r["arm"], r["tid"])
            if k in seen:
                continue
            seen.add(k); rows.append(r)
    if not rows:
        raise SystemExit("no discovery raw chunks")
    bank = DR._load_bank()
    all_tasks = {t["_id"]: t for t in AD.load_tasks(DS_DATA)}
    DR._aggregate(rows, labels, bank, all_tasks)


if __name__ == "__main__":
    main()
