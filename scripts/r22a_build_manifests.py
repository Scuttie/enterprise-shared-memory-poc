#!/usr/bin/env python3
"""R22-P0.9.1 §9 — R22A stage-aligned gradeable manifest construction (reusable generator).

Deterministic, outcome-blind selection + task-list builder for the R22A benchmark. Reads the per-target
gradeability audit (artifacts/r22_p09/dev58_gradeability_results.json) AT CALL TIME — that file does not exist
until the gated §8 audit runs, so nothing here seals a real manifest; construction only proceeds once the audit
is present. Pure functions (audit/dev55/dual-pair passed in) so a synthetic audit drives the regression test.

Selection rebuilds P2 (40) and the P1 smoke set (12) by dropping non-GRADEABLE targets and back-filling from the
GRADEABLE DEV_RESERVE pool via a fixed reserve priority; sources, O2 derangement, users, payload hashes and arm
budgets are recomputed. No real artifacts/r22a/* file is written by this module."""
from __future__ import annotations

import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from experiments.r22.runtime import arm_payload  # noqa: E402

EXPERIMENT_ID = "REALBENCH_R22A_STAGE_ALIGNED_GRADEABLE_V1"
ARMS = arm_payload.ARMS  # O0..O6
DEFAULT_STAGE = "patch"

# frozen selection inputs (§9)
DUAL_PAIR_TARGETS = ("astropy__astropy-15082", "sympy__sympy-12426", "sympy__sympy-12427")
RUFF_FAILED_P1 = ("astral-sh__ruff-15725", "astral-sh__ruff-16445")
GRADEABLE = "GRADEABLE"

ART = os.path.join(ROOT, "artifacts", "r22")
ART09 = os.path.join(ROOT, "artifacts", "r22_p09")
AUDIT_PATH = os.path.join(ART09, "dev58_gradeability_results.json")          # read at call time; may not exist yet
DEV55_PATH = os.path.join(ART09, "dev55_gradeability_manifest.json")
DUAL_PATH = os.path.join(ART09, "dual_pair_source_selection.json")           # frozen selected dual-pair sources (P0.9.1 §4)
ORACLE = {"p1": os.path.join(ART, "oracle_smoke_manifest.json"),
          "p2": os.path.join(ART, "oracle_dev_manifest.json")}


class BenchmarkNotViable(Exception):
    """Fewer than the required number of GRADEABLE targets remain — do not shrink N (R22_BENCHMARK_INSTRUMENT_NOT_VIABLE)."""


# ---------------------------------------------------------------- primitives
def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _hash_key(target_id):
    return _sha(EXPERIMENT_ID + "|" + target_id)


def _records(dev55):
    return dev55["records"] if isinstance(dev55, dict) and "records" in dev55 else dev55


def _label(audit, tid):
    a = audit.get(tid)
    if isinstance(a, dict):
        return a.get("label") or a.get("gradeability")
    return a


def is_gradeable(audit, tid):
    return _label(audit, tid) == GRADEABLE


def _temporal_valid(rec):
    """source→target temporal validity, read from pair_relations/class (CLEAN_RELATED == valid precedent)."""
    return any((r.get("class") == "CLEAN_RELATED") for r in (rec.get("pair_relations") or []))


# ---------------------------------------------------------------- loaders (call-time reads)
def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_audit(path=AUDIT_PATH):
    """Normalize the per-target audit results file to {target_id: label}. Read at call time."""
    d = load_json(path)
    src = d.get("per_target") or d.get("records") or d
    out = {}
    for tid, v in src.items():
        out[tid] = v.get("label") or v.get("gradeability") if isinstance(v, dict) else v
    return out


def load_dev55(path=DEV55_PATH):
    return _records(load_json(path))


def load_dual_pair_selection(path=DUAL_PATH):
    d = load_json(path)
    sel = d.get("targets") or d.get("selections") or d.get("dual_pair_source_selection") or d
    return {t: (v.get("selected_source_id") or v.get("source_id") if isinstance(v, dict) else v)
            for t, v in sel.items()}


def load_arm_budgets(kind):
    """Per-arm budget copied from the original oracle manifest (uniform per arm)."""
    m = load_json(ORACLE[kind])
    bud = {}
    for row in m["task_list"]:
        bud.setdefault(row["arm"], row["budget"])
    return bud


def load_p1_targets(path=ORACLE["p1"]):
    return sorted({row["target_id"] for row in load_json(path)["task_list"]})


# ---------------------------------------------------------------- reserve priority (deterministic, outcome-blind)
def reserve_priority(removed_target, candidates, audit, *, selected_clusters=frozenset()):
    """Deterministic, outcome-blind order of GRADEABLE reserve candidates for one removed target.

    Order: (1) same language, (2) same subset, (3) preserve repository-cluster disjointness vs the current
    selected set, (4) temporal validity (source before target), (5) ascending sha256(EXPERIMENT_ID|target_id).
    Only GRADEABLE reserves are eligible; no outcome/label beyond GRADEABLE is read. Returns candidate target_ids."""
    lang = removed_target.get("language")
    subset = removed_target.get("subset")
    elig = [c for c in candidates if is_gradeable(audit, c["target_id"])]

    def key(c):
        return (
            0 if c.get("language") == lang else 1,                          # (1) same language
            0 if c.get("subset") == subset else 1,                         # (2) same subset
            0 if c.get("repository_cluster") not in selected_clusters else 1,  # (3) cluster disjointness
            0 if _temporal_valid(c) else 1,                                # (4) temporal validity
            _hash_key(c["target_id"]),                                     # (5) deterministic hash
        )

    return [c["target_id"] for c in sorted(elig, key=key)]


def _fill(vacancies, keep, reserves, recs, audit):
    """Back-fill vacancies from the gradeable reserve pool via reserve_priority. Raises BenchmarkNotViable if a
    vacancy cannot be filled. Vacancies processed in deterministic (hash) order; cluster-disjointness accumulates."""
    avail = set(reserves)
    clusters = {recs[t]["repository_cluster"] for t in keep if t in recs}
    fills = []
    for v in sorted(vacancies, key=_hash_key):
        removed = recs.get(v, {"language": None, "subset": None, "repository_cluster": None, "pair_relations": []})
        cand = [recs[t] for t in sorted(avail)]
        order = reserve_priority(removed, cand, audit, selected_clusters=frozenset(clusters))
        if not order:
            raise BenchmarkNotViable("no gradeable reserve for vacancy %s" % v)
        pick = order[0]
        fills.append(pick)
        avail.discard(pick)
        clusters.add(recs[pick]["repository_cluster"])
    return fills


# ---------------------------------------------------------------- selection (§9.1 / §9.2)
def select_p2(audit, dev55, dual_pair_selection):
    """40 P2 targets: keep gradeable ORIGINAL_P2, back-fill vacancies from gradeable DEV_RESERVE. No held-out main."""
    recs = _records(dev55)
    originals = sorted(t for t, r in recs.items() if r["original_status"] == "ORIGINAL_P2")
    keep = [t for t in originals if is_gradeable(audit, t)]
    vac = [t for t in originals if not is_gradeable(audit, t)]
    reserves = [t for t, r in recs.items() if r["original_status"] == "DEV_RESERVE" and is_gradeable(audit, t)]
    result = keep + _fill(vac, keep, reserves, recs, audit)
    if len(set(result)) < 40:
        raise BenchmarkNotViable("P2 gradeable targets %d < 40" % len(set(result)))
    return sorted(result)


def select_p1(audit, current_p1_12, dual_pair_selection, dev55=None):
    """12 P1 smoke targets: keep gradeable P1, replace the 2 failed ruff (+ any non-gradeable) via the same reserve
    rule (same language rust → same subset → hash; fallback: same subset else any gradeable reserve by hash)."""
    recs = _records(dev55 if dev55 is not None else load_dev55())
    p1 = list(current_p1_12)
    ruff = set(RUFF_FAILED_P1)
    keep = [t for t in p1 if t not in ruff and is_gradeable(audit, t)]
    vac = [t for t in p1 if t in ruff or not is_gradeable(audit, t)]
    reserves = [t for t, r in recs.items() if r["original_status"] == "DEV_RESERVE" and is_gradeable(audit, t)]
    result = keep + _fill(vac, keep, reserves, recs, audit)
    if len(set(result)) != 12:
        raise BenchmarkNotViable("P1 target count %d != 12" % len(set(result)))
    return sorted(result)


# ---------------------------------------------------------------- sources / users / derangement
def pick_source(target_id, dual_pair_selection, dev55):
    """Frozen dual-pair source for the 3 dual-pair targets, else the target's single pair source_id. Users derived
    by sha256; source_user must differ from target_user (no self-memory leakage)."""
    recs = _records(dev55)
    if target_id in DUAL_PAIR_TARGETS:
        src = dual_pair_selection[target_id]
    else:
        rels = recs[target_id].get("pair_relations") or []
        if not rels:
            raise ValueError("no pair source for %s" % target_id)
        src = rels[0]["source_id"]
    target_user = "u_" + _sha(target_id)[:10]
    source_user = "gold_" + _sha(src)[:10]
    if source_user == target_user:
        raise ValueError("source_user == target_user for %s" % target_id)
    return {"source_id": src, "target_user": target_user, "source_user": source_user}


def build_derangement(target_ids):
    """Deterministic O2 source assignment over the selected set with NO fixed point (rotate sorted list by 1)."""
    ids = sorted(set(target_ids))
    n = len(ids)
    if n < 2:
        raise ValueError("derangement needs >= 2 targets")
    mapping = {ids[i]: ids[(i + 1) % n] for i in range(n)}
    for t, s in mapping.items():
        if t == s:
            raise AssertionError("O2 fixed point at %s" % t)
    return mapping


# ---------------------------------------------------------------- task list / manifest
def build_task_list(targets, sources_by_target, o2_by_target, arm_budgets=None):
    """targets × arms O0..O6 → rows {target_id, arm, mem_source, target_user, source_user, payload_hash, budget}.
    mem_source: O2 deranged source; pair source for other memory-enabled arms (O3..O6); null for O0/O1."""
    if arm_budgets is None:
        arm_budgets = load_arm_budgets("p2")
    rows = []
    for t in targets:
        si = sources_by_target[t]
        tu, su, pair_src = si["target_user"], si["source_user"], si["source_id"]
        for arm in ARMS:
            if arm in ("O0", "O1"):
                mem, src = None, pair_src
            elif arm == "O2":
                mem = o2_by_target[t]
                src = mem
            else:
                mem = pair_src
                src = pair_src
            p = arm_payload.build_payload(arm, target_id=t, source_id=src, source_user=su,
                                          target_user=tu, stage=DEFAULT_STAGE)
            b = arm_budgets[arm]
            rows.append({"target_id": t, "arm": arm, "mem_source": mem, "target_user": tu, "source_user": su,
                         "payload_hash": p["byte_hash"],
                         "budget": {"search": b["search"], "browse": b["browse"], "exec_tokens": b["exec_tokens"]}})
    return rows


def build_manifest(kind, audit=None, dev55=None, dual_pair_selection=None, current_p1_12=None, arm_budgets=None):
    """Assemble the R22A manifest dict for kind in {'p1','p2'}. Reads audit/dev55/dual-pair at call time when not
    supplied. Returns the dict (caller decides whether/where to seal — this function writes nothing)."""
    audit = audit if audit is not None else load_audit()
    dev55 = dev55 if dev55 is not None else load_dev55()
    dual = dual_pair_selection if dual_pair_selection is not None else load_dual_pair_selection()
    if kind == "p1":
        current_p1_12 = current_p1_12 if current_p1_12 is not None else load_p1_targets()
        targets = select_p1(audit, current_p1_12, dual, dev55=dev55)
        schema, exp_targets = "r22a/p1_smoke_manifest/1.0.0", 12
        arm_budgets = arm_budgets if arm_budgets is not None else load_arm_budgets("p1")
    elif kind == "p2":
        targets = select_p2(audit, dev55, dual)
        schema, exp_targets = "r22a/oracle_dev_manifest/1.0.0", 40
        arm_budgets = arm_budgets if arm_budgets is not None else load_arm_budgets("p2")
    else:
        raise ValueError("unknown kind %s" % kind)
    assert len(targets) == exp_targets  # 12 (p1) / 40 (p2); selection raises BenchmarkNotViable otherwise
    sources = {t: pick_source(t, dual, dev55) for t in targets}
    o2 = build_derangement(targets)
    task_list = build_task_list(targets, sources, o2, arm_budgets=arm_budgets)
    return {"schema": schema, "experiment": EXPERIMENT_ID,
            "manifest_sha256": _sha(json.dumps(task_list, sort_keys=True)),
            "task_list": task_list, "target_count": len(targets), "cell_count": len(task_list)}


def validate_manifest(manifest, expected_targets, expected_cells, *, removed=(), reserves=()):
    """Post-condition checks. expected_targets may be an int count or an explicit id set. Returns a checks dict."""
    tl = manifest["task_list"]
    targets = [r["target_id"] for r in tl]
    uniq = set(targets)
    et_ok = (len(uniq) == expected_targets) if isinstance(expected_targets, int) else (uniq == set(expected_targets))
    self_src = [r for r in tl if r["mem_source"] is not None and r["mem_source"] == r["target_id"]]
    bad_users = [r for r in tl if r["source_user"] == r["target_user"]]
    o2_fp = [r for r in tl if r["arm"] == "O2" and r["mem_source"] == r["target_id"]]
    checks = {
        "unique_targets": len(uniq),
        "unique_targets_ok": et_ok,
        "cell_count": len(tl),
        "cell_count_ok": len(tl) == expected_cells,
        "removed_absent": all(x not in uniq for x in removed),
        "reserves_present": all(x in uniq for x in reserves),
        "self_source_rows": len(self_src),
        "source_target_overlap0": len(self_src) == 0,
        "leakage0": len(self_src) == 0,
        "user_distinct_ok": len(bad_users) == 0,
        "o2_fixed_points": len(o2_fp),
        "o2_fixed_points_ok": len(o2_fp) == 0,
    }
    checks["all_ok"] = all([
        et_ok, checks["cell_count_ok"], checks["removed_absent"], checks["reserves_present"],
        checks["source_target_overlap0"], checks["user_distinct_ok"], checks["o2_fixed_points_ok"],
        checks["leakage0"],
    ])
    return checks


if __name__ == "__main__":
    # Construction requires the gated audit results; nothing is sealed here.
    if not os.path.exists(AUDIT_PATH):
        print("R22A construction BLOCKED: %s absent (gated §8 audit not run). No manifest sealed." % AUDIT_PATH)
        raise SystemExit(0)
    for kind, ntargets, cells in (("p1", 12, 84), ("p2", 40, 280)):
        m = build_manifest(kind)
        chk = validate_manifest(m, ntargets, cells)
        print(kind, "targets=%d cells=%d sha=%s all_ok=%s"
              % (m["target_count"], m["cell_count"], m["manifest_sha256"][:12], chk["all_ok"]))
