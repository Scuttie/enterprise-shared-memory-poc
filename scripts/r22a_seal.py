#!/usr/bin/env python3
"""R22-P0.9.2 §7/§8 — construct + SEAL R22A from the COMPLETED dev55 audit (55 terminal labels).

Uses the already-committed deterministic generator (scripts/r22a_build_manifests.py). Builds P2 (40) + P1 (12),
validates all post-conditions, verifies P1 gold/noop discrimination FROM the completed audit (the 12 selected P1
targets are GRADEABLE => gold resolved + noop unresolved), and seals the R22A manifests. If <40 gradeable ->
R22_BENCHMARK_INSTRUMENT_NOT_VIABLE (no N shrink). No model/paid calls."""
import hashlib
import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART09 = os.path.join(ROOT, "artifacts", "r22_p09")
ART092 = os.path.join(ROOT, "artifacts", "r22_p092")
R22A = os.path.join(ROOT, "artifacts", "r22a")
CONFIGS = os.path.join(ROOT, "configs", "r22a")


def _load(mod_path):
    spec = importlib.util.spec_from_file_location("r22a_gen", mod_path)
    m = importlib.util.module_from_spec(spec)
    import sys
    sys.path.insert(0, ROOT)
    spec.loader.exec_module(m)
    return m


def sha(b):
    return hashlib.sha256(b.encode() if isinstance(b, str) else b).hexdigest()


def main():
    os.makedirs(R22A, exist_ok=True)
    os.makedirs(CONFIGS, exist_ok=True)
    G = _load(os.path.join(ROOT, "scripts", "r22a_build_manifests.py"))

    complete = json.load(open(os.path.join(ART092, "dev55_gradeability_results_complete.json"), encoding="utf-8"))
    assert complete["audit_complete"], "audit is not complete; refusing to seal"
    audit = complete["per_target_label"]                         # {tid: label}
    dev55 = G.load_dev55()
    dual = G.load_dual_pair_selection()
    gradeable_total = sum(1 for l in audit.values() if l == "GRADEABLE")
    if gradeable_total < 40:
        print("R22_BENCHMARK_INSTRUMENT_NOT_VIABLE: only %d gradeable (need 40)" % gradeable_total)
        return 2

    # P2 (40) and P1 (12)
    try:
        p2 = G.build_manifest("p2", audit=audit, dev55=dev55, dual_pair_selection=dual)
        p1 = G.build_manifest("p1", audit=audit, dev55=dev55, dual_pair_selection=dual)
    except G.BenchmarkNotViable as e:
        print("R22_BENCHMARK_INSTRUMENT_NOT_VIABLE:", e)
        return 2

    orig40 = [t for t, r in dev55.items() if r["original_status"] == "ORIGINAL_P2"]
    removed = [t for t in orig40 if audit.get(t) != "GRADEABLE"]
    p2_ids = list(dict.fromkeys(r["target_id"] for r in p2["task_list"]))          # 40 UNIQUE targets
    reserves_used = sorted({t for t in p2_ids if dev55[t]["original_status"] == "DEV_RESERVE"})
    v2 = G.validate_manifest(p2, 40, 280, removed=removed, reserves=reserves_used)
    p1_ids = list(dict.fromkeys(r["target_id"] for r in p1["task_list"]))
    v1 = G.validate_manifest(p1, 12, 84)

    # every selected target must be GRADEABLE (P2 40/40, P1 12/12) -> gold resolved + noop unresolved
    p2_all_gradeable = all(audit.get(t) == "GRADEABLE" for t in p2_ids)
    p1_all_gradeable = all(audit.get(t) == "GRADEABLE" for t in p1_ids)
    if not (v2["all_ok"] and v1["all_ok"] and p2_all_gradeable and p1_all_gradeable):
        print("R22A validation FAILED:", {"p2": v2, "p1": v1,
              "p2_all_gradeable": p2_all_gradeable, "p1_all_gradeable": p1_all_gradeable})
        return 1

    # composition (accurate; not "python-only")
    import collections
    lang = dict(collections.Counter(dev55[t]["language"] for t in p2_ids))
    subset = dict(collections.Counter(dev55[t].get("subset") for t in p2_ids))

    # SEAL
    json.dump(p2, open(os.path.join(R22A, "oracle_dev_manifest.json"), "w", encoding="utf-8"), indent=2)
    json.dump(p1, open(os.path.join(R22A, "p1_smoke_manifest.json"), "w", encoding="utf-8"), indent=2)
    arm = {"experiment": G.EXPERIMENT_ID, "arms": ["O0", "O1", "O2", "O3", "O4", "O5", "O6"],
           "memory_enabled": {a: (a not in ("O0", "O1")) for a in ["O0", "O1", "O2", "O3", "O4", "O5", "O6"]},
           "estimands": {"Q1": "O5-O2", "Q2": "O5-O4", "Q3": "O6-O5"}}
    json.dump(arm, open(os.path.join(R22A, "oracle_arm_manifest.json"), "w", encoding="utf-8"), indent=2)
    sel = {"experiment": G.EXPERIMENT_ID, "removed_ungradeable_originals": sorted(removed),
           "reserves_used": sorted(reserves_used), "p2_targets": sorted(p2_ids), "p1_targets": sorted(p1_ids),
           "rule": "retain GRADEABLE originals; back-fill from GRADEABLE DEV_RESERVE by same-language -> same-subset "
                   "-> repo/temporal -> sha256(EXPERIMENT_ID|target)", "dual_pair_sources": dual}
    json.dump(sel, open(os.path.join(R22A, "task_selection_audit.json"), "w", encoding="utf-8"), indent=2)
    src_lock = {"experiment": G.EXPERIMENT_ID,
                "gradeable_audit_sha256": sha(open(os.path.join(ART092, "dev55_gradeability_results_complete.json"), "rb").read()),
                "dev55_manifest_sha256": sha(open(os.path.join(ART09, "dev55_gradeability_manifest.json"), "rb").read()),
                "dual_pair_sha256": sha(open(os.path.join(ART09, "dual_pair_source_selection.json"), "rb").read())}
    json.dump(src_lock, open(os.path.join(R22A, "gradeability_source_lock.json"), "w", encoding="utf-8"), indent=2)
    lock = {"experiment_id": G.EXPERIMENT_ID, "supersedes": None, "does_not_mutate": "R22 (R22_SCB_GRADER_GATE_FAIL)",
            "p2_target_count": 40, "p2_cell_count": 280, "p1_target_count": 12, "p1_cell_count": 84,
            "p2_manifest_sha256": p2["manifest_sha256"], "p1_manifest_sha256": p1["manifest_sha256"],
            "language_composition": lang, "subset_composition": subset,
            "estimand": "memory effect on the pre-model, official-grader-gradeable SWE-ContextBench development subset "
                        "(Python-heavy; retains Multilingual Java/Go/Rust); does NOT represent all SWE-ContextBench languages",
            "p3_confirmatory_main": "NOT RUN / POWER BLOCKED"}
    json.dump(lock, open(os.path.join(CONFIGS, "experiment_lock.json"), "w", encoding="utf-8"), indent=2)
    freeze = {"experiment": G.EXPERIMENT_ID, "sealed_files": {}}
    for p in ("oracle_dev_manifest.json", "p1_smoke_manifest.json", "oracle_arm_manifest.json",
              "task_selection_audit.json", "gradeability_source_lock.json"):
        freeze["sealed_files"][p] = sha(open(os.path.join(R22A, p), "rb").read())
    freeze["sealed_files"]["configs/r22a/experiment_lock.json"] = sha(open(os.path.join(CONFIGS, "experiment_lock.json"), "rb").read())
    json.dump(freeze, open(os.path.join(R22A, "freeze.json"), "w", encoding="utf-8"), indent=2)

    print("R22A SEALED: P2 40/280 all_ok=%s | P1 12/84 all_ok=%s | P2 gradeable=%s P1 gradeable=%s"
          % (v2["all_ok"], v1["all_ok"], p2_all_gradeable, p1_all_gradeable))
    print("removed originals:", sorted(removed))
    print("reserves used:", sorted(reserves_used))
    print("P2 language:", lang, "| subset:", subset)
    print("P2 manifest_sha256:", p2["manifest_sha256"][:16], "| P1 manifest_sha256:", p1["manifest_sha256"][:16])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
