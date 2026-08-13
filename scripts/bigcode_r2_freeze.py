"""BIGCODE-R2-A part 2 — freeze the partition + pin the lock (§4/§18). Runs inside the official eval image
(needs the bigcodebench dataset). Deterministic; NO model call. Emits the frozen partition, its sha256, the
overlap audit, and rewrites the pinned provenance fields (content_hash, official_dataset_hash, task count)
into bigcodebench_lock.json. These artifacts are then committed + sealed before any paid run."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments.bigcode_r2 import grader as G, partition as P   # noqa: E402

ART = os.path.join("artifacts", "bigcode_r2")
CFG = os.path.join("configs", "bigcode_r2")


def main():
    os.makedirs(ART, exist_ok=True)
    part = P.build_partition()
    audit = P.audit_partition(part)
    sh = P.split_hash(part)
    ch = G.content_hash()
    try:
        dh = G.dataset_hash()
    except Exception as e:
        dh = "ERR:%s" % type(e).__name__
    count = G.task_count()

    payload = {k: part[k] for k, _ in P.SIZES}
    with open(os.path.join(ART, "task_partition.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"sets": payload, "meta": part["_meta"], "split_hash": sh,
                   "sizes": {k: len(v) for k, v in payload.items()}}, f, indent=2, sort_keys=True)
        f.write("\n")
    with open(os.path.join(ART, "task_partition.sha256"), "w", encoding="utf-8", newline="\n") as f:
        f.write(sh + "\n")
    with open(os.path.join(ART, "partition_audit.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(audit, f, indent=2, sort_keys=True)
        f.write("\n")

    lock_path = os.path.join(CFG, "bigcodebench_lock.json")
    lock = json.load(open(lock_path, encoding="utf-8"))
    lock.update({"dataset_content_hash": ch, "official_dataset_hash": dh, "confirmed_task_count": count})
    with open(lock_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(lock, f, indent=2, sort_keys=True)
        f.write("\n")

    print("FREEZE split_hash", sh[:16], "count", count, "content_hash", ch[:12], flush=True)
    print("AUDIT", json.dumps(audit), flush=True)
    hard_ok = audit["overlaps_all_zero"] and audit["source_target_near_dup_pairs"] == 0 \
        and all(audit["sizes"][k] >= n for k, n in [("source", 300), ("main", 500)])
    if not hard_ok:
        print("FREEZE_WARN: hard requirements not met -> inspect before sealing", flush=True)
        sys.exit(3)
    print("FREEZE_OK", flush=True)


if __name__ == "__main__":
    main()
