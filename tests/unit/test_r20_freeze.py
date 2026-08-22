"""R20 — frozen-design invariants (static; no live model). Enforces the parity + non-interference rules (§14)."""
import json
import hashlib
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
R20 = ROOT / "artifacts" / "r20"


def _load(name):
    return json.load(open(R20 / name, encoding="utf-8"))


def test_confirmatory_excludes_r19_observed():
    r20_ids = set(_load("task_manifest.json")["ids"])
    r19_ids = set(json.load(open(ROOT / "configs" / "p6" / "r19_small_targets.json"))["ids"])
    assert r20_ids and r19_ids
    assert r20_ids.isdisjoint(r19_ids), "R20 confirmatory set must exclude the R19-observed 60"


def test_task_manifest_hash_matches():
    tm = _load("task_manifest.json")
    assert hashlib.sha256(",".join(tm["ids"]).encode()).hexdigest() == tm["content_hash"]


def test_source_pair_invariants_recorded():
    sp = _load("source_pair_manifest.json")
    assert sp["invariant_holds_by_construction"] is True
    assert sp["n"] == _load("task_manifest.json")["n"]
    # every target records both a relevant and a shuffled source set (same set reused for router on/off)
    for q, rec in sp["pairs"].items():
        assert "relevant_source_ids" in rec and "shuffled_source_ids" in rec


def test_all_six_arm_files_present_and_frozen():
    for a in ["B0", "B1", "F00", "F10", "F01", "F11"]:
        assert (R20 / "arms_in" / ("memory_%s.json" % a)).is_file(), a
    cs = _load("card_snapshot.json")
    for a in ["B1", "F00", "F10", "F01", "F11"]:
        p = R20 / "arms_in" / ("memory_%s.json" % a)
        got = hashlib.sha256(open(p, "rb").read().replace(b"\r\n", b"\n")).hexdigest()
        assert got == cs["arms_in_hashes"]["memory_%s.json" % a], a


def test_b1_length_parity_with_f10():
    b1 = _load("arms_in/memory_B1.json"); f10 = _load("arms_in/memory_F10.json")
    ids = [q for q in f10 if q in b1 and f10[q]]
    ratios = [len(b1[q]) / max(1, len(f10[q])) for q in ids]
    mean = sum(ratios) / len(ratios)
    assert 0.8 <= mean <= 1.25, "B1 must be compute-length-matched to F10 (got %.2f)" % mean


def test_freeze_master_locks_intact():
    fr = _load("freeze.json")
    for name, short in fr["locks"].items():
        full = _load("%s.json" % name)["content_hash"]
        assert full.startswith(short), name


def test_router_policy_is_frozen_r19_policy():
    a = _load("router_policy.json"); b = json.load(open(ROOT / "artifacts" / "p6" / "router_policy.json"))
    assert a["content_hash"] == b["content_hash"], "R20 must reuse the frozen R19 router policy unchanged"


def test_all_r20_locks_content_hash_valid():
    import glob, os
    for p in glob.glob(str(R20 / "*.json")):
        if os.path.basename(p) == "task_manifest.json":
            continue  # semantic id-hash (see test_task_manifest_hash_matches), not a full-body seal
        b = json.load(open(p, encoding="utf-8"))
        if "content_hash" not in b:
            continue
        stored = b.pop("content_hash")
        calc = hashlib.sha256(json.dumps(b, sort_keys=True, default=str).encode()).hexdigest()
        assert stored == calc, p


def test_analysis_did_fixture():
    # tiny synthetic 2x2 DID: relevant+router should net +1 over the shuffled router delta
    F11 = {"t1": 1, "t2": 0}; F10 = {"t1": 0, "t2": 0}; F01 = {"t1": 0, "t2": 0}; F00 = {"t1": 0, "t2": 0}
    did = {q: (F11[q] - F10[q]) - (F01[q] - F00[q]) for q in F11}
    assert sum(did.values()) / len(did) == 0.5
