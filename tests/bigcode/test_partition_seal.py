"""BIGCODE-R2 partition seal — recompute the split hash from the committed partition and assert the frozen
audit invariants, WITHOUT importing bigcodebench (pure over the committed JSON so it runs on any host)."""
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
ART = ROOT / "artifacts" / "bigcode_r2"
SIZES = [("source", 300), ("retrieval_dev", 80), ("discovery", 120),
         ("calibration", 80), ("main", 500), ("reserve", 60)]


def _load():
    return json.loads((ART / "task_partition.json").read_text(encoding="utf-8"))


def test_split_hash_matches_committed_sha256():
    p = _load()
    payload = {name: p["sets"][name] for name, _ in SIZES}
    h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    assert h == p["split_hash"]
    assert h == (ART / "task_partition.sha256").read_text(encoding="utf-8").strip()


def test_sizes_exact():
    p = _load()["sets"]
    for name, n in SIZES:
        assert len(p[name]) == n, (name, len(p[name]), n)
    total = sum(len(p[name]) for name, _ in SIZES)
    assert total == 1140


def test_all_pairwise_disjoint():
    p = _load()["sets"]
    names = [n for n, _ in SIZES]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            assert not (set(p[names[i]]) & set(p[names[j]])), (names[i], names[j])


def test_audit_hard_requirements():
    a = json.loads((ART / "partition_audit.json").read_text(encoding="utf-8"))
    assert a["overlaps_all_zero"] is True
    assert a["source_target_near_dup_pairs"] == 0
    # shared-harness: BigCodeBench uses one entry-point name for all tasks -> collision statistic is 1
    assert a["funcname_collision_source_target"] <= 1


def test_lock_pinned():
    lock = json.loads((ROOT / "configs" / "bigcode_r2" / "bigcodebench_lock.json").read_text(encoding="utf-8"))
    assert lock["confirmed_task_count"] == 1140
    assert lock["dataset_content_hash"] != "PENDING_CI_PROBE"
    assert lock["license"] == "Apache-2.0"
