"""REALBENCH-R3 §5 — build & freeze the DS-1000 task partition. Deterministic; no model calls. Verifies the
data-file sha256 against the lock before building, so the frozen split is bound to the exact pinned dataset.
Usage: DS1000_DATA=<path to ds1000.jsonl.gz> python scripts/r3_build_partition.py"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from experiments.actionable_memory_r3 import ds1000_adapter as AD, partition as P  # noqa: E402

LOCK_P = os.path.join(REPO, "configs", "actionable_memory_r3", "ds1000_lock.json")
OUT = os.path.join(REPO, "artifacts", "actionable_memory_r3", "task_partition.json")
DATA = os.environ.get("DS1000_DATA", os.path.join(REPO, "DS-1000", "data", "ds1000.jsonl.gz"))
EXPECT_SHA = "e8c6daa9d7223976bce0296644f3933f78d7f47830669ff05cd61da62c6ba9b3"


def main():
    sha = AD.data_sha256(DATA)
    if sha != EXPECT_SHA:
        raise SystemExit("DATA SHA MISMATCH: %s != %s" % (sha, EXPECT_SHA))
    tasks = AD.load_tasks(DATA)
    part = P.build(tasks)
    part["data_sha256"] = sha
    part["data_content_hash"] = AD.content_hash(tasks)
    part["task_count"] = len(tasks)
    assert part["family_span_violations"] == 0, "near-dup family spans splits"
    assert sum(part["sizes"].values()) == len(tasks) == 1000
    assert part["sizes"]["CONFIRMATORY_MAIN"] >= 400 and part["sizes"]["SOURCE_POOL"] >= 150
    ids = [t for s in part["sets"].values() for t in s]
    assert len(ids) == len(set(ids)) == 1000, "splits not disjoint / incomplete"
    json.dump(part, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, sort_keys=True)
    print("split_hash", part["split_hash"], "sizes", part["sizes"], flush=True)
    # write the sha into the lock (idempotent)
    lock = json.load(open(LOCK_P, encoding="utf-8"))
    if lock.get("data_file_sha256") != sha:
        lock["data_file_sha256"] = sha
        json.dump(lock, open(LOCK_P, "w", encoding="utf-8", newline="\n"), indent=2, sort_keys=False)
        print("lock updated with data_file_sha256", flush=True)


if __name__ == "__main__":
    main()
