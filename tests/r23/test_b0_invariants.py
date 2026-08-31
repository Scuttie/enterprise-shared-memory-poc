"""R23-B0 §12 — credential-free invariants over the benchmark/eligibility foundation. No docker/model/network."""
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ART = os.path.join(ROOT, "artifacts", "r23")


def _j(name):
    return json.load(open(os.path.join(ART, name), encoding="utf-8"))


# ---- benchmark lock ----------------------------------------------------------
def test_benchmark_lock_revision_and_rowcount():
    b = _j("benchmark_lock.json")
    assert b["dataset_id"] == "SWE-bench/SWE-bench_Verified"
    assert b["revision_sha"] == "78f471bf655a3137b2e8a75af1501690ec009ec3"
    assert b["row_count"] == 500 and b["unique_instance_ids"] == 500
    assert len(b["parquet_sha256"]) == 64
    assert len(b["per_instance_hash_index"]) == 500


def test_static_audit_shape_and_timestamp_honesty():
    s = _j("verified_static_audit.json")
    assert s["row_count"] == 500 and len(s["instances"]) == 500
    assert s["duplicate_classes"]["EXACT_DUPLICATE_ROW"] == 0
    assert s["timestamp_coverage"]["issue_created_at_known"] == 500
    assert s["timestamp_coverage"]["fix_pr_merge_at_known"] == 0     # honestly UNKNOWN, not guessed
    for a in s["instances"].values():
        assert a["language"] == "python" and a["fix_pr_merge_at"] == "UNKNOWN"


def test_image_field_completeness():
    im = _j("image_manifest.json")
    assert im["count"] == 500 and im["image_field_present"] == 500


# ---- streaming orders are permutations, no self-memory possible --------------
def test_streaming_orders_are_500_permutations():
    ids = set(json.load(open(os.path.join(ART, "verified_static_audit.json")))["instances"].keys())
    lock = _j("author_stream_order_lock.json")
    seen = set()
    for k in range(3):
        o = _j("author_stream_order_%d.json" % k)
        seq = o["sequence"]
        assert len(seq) == 500 and set(seq) == ids and len(set(seq)) == 500   # permutation, no dup, no missing
        assert hashlib.sha256(json.dumps(seq).encode()).hexdigest() == o["order_sha256"]
        seen.add(o["order_sha256"])
    assert len(seen) == 3 and {e["sha256"] for e in lock["orders"]} == seen


def test_no_self_memory_rule_is_prefix_only():
    # a task t may see only tasks strictly before it in its order (never itself)
    o = _j("author_stream_order_0.json")["sequence"]
    for i, t in enumerate(o):
        visible = set(o[:i])
        assert t not in visible                                       # never sees itself
        assert len(visible) == i                                      # only earlier-in-order


# ---- chronological eligibility: direction + no result fields -----------------
def test_eligibility_direction_and_no_result_fields():
    e = _j("chronological_eligibility_graph.json")
    c = _j("timestamp_cache.json")
    assert e["target_start_at_field"] == "linked GitHub issue.created_at"
    assert e["r23_x_chronology"] == "PENDING_B0_1"
    assert e["source_available_at_known"] == c["coverage"]["source_available_at_known"]
    assert e["target_start_at_known"] == c["coverage"]["linked_issue_created_at_known"]
    assert e["pr_created_proxy_is_eligibility"] is False
    assert e["source_target_pair_selection"] == "NOT_PERFORMED"
    assert e["edge_partition_check"] is True
    blob = json.dumps(e).lower()
    for banned in ("resolved", "pass@1", "gold_patch", "reader", "arm"):
        assert banned not in blob, "eligibility graph must carry NO result/answer fields (%s)" % banned


# ---- R22 preservation + main/tag lock ----------------------------------------
def test_parent_state_lock_preserves_r22_and_main():
    p = _j("parent_state_lock.json")
    assert p["parent_head"] == "289413dcf737d85213eb15233e80a4daf5bf952b"
    assert p["preserved"]["main"] == "ce10ab49586db7a859fbe5cca93051b93f9f5b55"
    assert p["preserved"]["v0.3.0-rc1_tag_object"] == "c1741c6d635bc97e470ea553753c143888a0c0be"
    assert "merge" in p["prohibited"] and "force-push" in p["prohibited"]


def test_novelty_claim_not_overstated():
    lit = _j("literature_lock.json")
    assert "NOT YET ESTABLISHED" in lit["novelty_judgment"]["endpoint_this_gate"]
    assert lit["primary_sources"]["A"]["code_released"] is False
    assert lit["third_party_implementation"]["license"] == "NONE"
