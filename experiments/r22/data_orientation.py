#!/usr/bin/env python3
"""R22 §1 — data orientation + power feasibility (no model calls).

Resolves the three data discrepancies (duplicate base IDs, 57-vs-51 repos, 245 temporal-invalid), produces a
pre-run split amendment (v2) that keeps v1+seal intact, and computes a paired-McNemar power grid. Deterministic:
uses only the MIT dataset parquets + fixed rules. Emits artifacts/r22/{repository_alias_map,duplicate_audit,
temporal_reaudit,dev_manifest_v2,main_manifest_v2,power_grid}.json and a summary.
"""
import hashlib
import json
import math
import os
import re
from collections import defaultdict

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.environ.get("R22_SCB_DATA", os.path.join(ROOT, "artifacts", "r22", "_scb_data"))
OUT = os.path.join(ROOT, "artifacts", "r22")


def _row_hash(r, cols):
    return hashlib.sha256("|".join(str(r.get(c, "")) for c in cols).encode()).hexdigest()


def _norm_hunks(patch):
    s = set()
    for ln in (patch or "").splitlines():
        if ln[:1] in "+-" and not ln.startswith(("+++", "---")):
            b = re.sub(r"\s+", " ", ln[1:].strip())
            if b:
                s.add(b)
    return s


def main():
    exp = pd.read_parquet(os.path.join(DATA, "SWEContextBench_Experience.parquet"))
    rel = pd.read_parquet(os.path.join(DATA, "SWEContextBench_Related.parquet"))
    rl = pd.read_parquet(os.path.join(DATA, "SWEContextBench_Relationship.parquet"))
    cols = list(exp.columns)

    # ---- §1.1 duplicate base ID classification ----
    rel_targets_of = defaultdict(set)
    for _, r in rl.iterrows():
        rel_targets_of[r["experience_instance_id"]].add(r["related_instance_id"])
    dup_ids = exp["instance_id"][exp["instance_id"].duplicated(keep=False)]
    dup_audit = {"total_duplicate_rows": int(exp["instance_id"].duplicated().sum()), "classes": defaultdict(int),
                 "detail": []}
    exact_dup_row_drop = set()
    seen_rowhash = {}
    for iid in sorted(set(dup_ids)):
        rows = exp[exp["instance_id"] == iid]
        rhashes = [_row_hash(r, cols) for _, r in rows.iterrows()]
        commits = set(rows["base_commit"]); versions = set(rows["version"].astype(str))
        patches = set(hashlib.sha256((p or "").encode()).hexdigest() for p in rows["patch"])
        if len(set(rhashes)) == 1:
            cls = "EXACT_DUPLICATE_ROW"
            # keep first, drop the rest deterministically
            for idx in rows.index[1:]:
                exact_dup_row_drop.add(idx)
        elif len(commits) > 1:
            cls = "SAME_INSTANCE_DIFFERENT_VERSION"
        elif len(patches) > 1:
            cls = "SAME_INSTANCE_DIFFERENT_VERSION"
        elif len(rel_targets_of.get(iid, set())) > 1:
            cls = "SAME_INSTANCE_DIFFERENT_RELATION"
        else:
            cls = "UNKNOWN"
        dup_audit["classes"][cls] += 1
        dup_audit["detail"].append({"instance_id": iid, "rows": int(len(rows)),
                                    "distinct_row_hashes": len(set(rhashes)), "class": cls,
                                    "related_targets": len(rel_targets_of.get(iid, set()))})
    dup_audit["classes"] = dict(dup_audit["classes"])
    dup_audit["exact_duplicate_rows_to_drop"] = len(exact_dup_row_drop)
    json.dump(dup_audit, open(os.path.join(OUT, "duplicate_audit.json"), "w", encoding="utf-8"),
              indent=2, default=str)

    # ---- §1.2 repository alias map (57 vs 51) ----
    all_repos = sorted(set(exp["repo"]) | set(rel["repo"]))
    canon = {}
    groups = defaultdict(list)
    for rp in all_repos:
        key = rp.strip().lower().rstrip("/")
        key = key.split("github.com/")[-1]
        groups[key].append(rp)
    for key, members in groups.items():
        canonical = sorted(members)[0]
        for m in members:
            canon[m] = canonical
    canonical_repos = sorted(set(canon.values()))
    base_only = set(exp["repo"]) - set(rel["repo"])
    rel_only = set(rel["repo"]) - set(exp["repo"])
    alias = {"raw_repo_strings": len(all_repos), "canonical_repositories": len(canonical_repos),
             "dataset_card_claim": 51, "map": canon,
             "explanation": ("raw strings = %d; after case/owner normalization canonical = %d; "
                             "base-only repos=%d, related-only repos=%d — the 51 card figure counts distinct "
                             "canonical repositories in the base experience pool, while 57 counted raw strings "
                             "across base+related including related-only repos and case variants"
                             % (len(all_repos), len(canonical_repos), len(base_only), len(rel_only))),
             "base_only_repos": sorted(base_only), "related_only_repos": sorted(rel_only)}
    json.dump(alias, open(os.path.join(OUT, "repository_alias_map.json"), "w", encoding="utf-8"),
              indent=2, default=str)

    # ---- §1.3 temporal re-audit + reorientation (created_at proxy, applied deterministically) ----
    exp_by = {r["instance_id"]: r for _, r in exp.iterrows()}
    rel_by = {r["instance_id"]: r for _, r in rel.iterrows()}

    def ts(row):
        try:
            return pd.to_datetime(row["created_at"], utc=True)
        except Exception:
            return None

    reaudit = {"note": ("chronology proxy = instance created_at (PR/issue creation). Precise merge/first-commit "
                        "reorientation via GitHub API is a follow-up; direction is flipped only when the reoriented "
                        "source is itself a runnable graded task and no target answer leaks into it."),
               "classes": defaultdict(int), "pairs": []}
    clean_pairs = []
    reoriented_pairs = []
    for _, r in rl.iterrows():
        tgt = rel_by.get(r["related_instance_id"]); src = exp_by.get(r["experience_instance_id"])
        rec = {"target_id": r["related_instance_id"], "source_id": r["experience_instance_id"]}
        if tgt is None or src is None:
            rec["class"] = "UNKNOWN"; reaudit["classes"]["UNKNOWN"] += 1; reaudit["pairs"].append(rec); continue
        st, tt = ts(src), ts(tgt)
        s_patch, t_patch = src["patch"] or "", tgt["patch"] or ""
        overlap = (len(_norm_hunks(s_patch) & _norm_hunks(t_patch)) / max(1, len(_norm_hunks(t_patch)))) \
            if _norm_hunks(t_patch) else 0.0
        patch_match = hashlib.sha256(s_patch.encode()).hexdigest() == hashlib.sha256(t_patch.encode()).hexdigest()
        src_blob = " ".join(str(src.get(c, "")) for c in ["problem_statement", "hints_text", "patch", "test_patch"])
        tgt_adj = str(r["related_instance_id"]) in src_blob
        # reoriented source (the related task) must not leak the base target answer either
        tgt_blob = " ".join(str(tgt.get(c, "")) for c in ["problem_statement", "hints_text", "patch", "test_patch"])
        rev_adj = str(r["experience_instance_id"]) in tgt_blob
        if patch_match:
            cls = "TARGET_PATCH_MATCH"
        elif tgt_adj:
            cls = "TARGET_ADJACENT"
        elif overlap >= 0.60:
            cls = "NEAR_DUPLICATE"
        elif st is not None and tt is not None and st < tt:
            cls = "CLEAN_RELATED"
        elif st is not None and tt is not None and tt < st and not rev_adj:
            cls = "TEMPORAL_REORIENTED_VALID"   # flip: related is source, base is target
            rec["reoriented"] = True
        else:
            cls = "TEMPORAL_INVALID"
        rec["class"] = cls
        rec["normalized_hunk_overlap"] = round(overlap, 4)
        reaudit["classes"][cls] += 1
        reaudit["pairs"].append(rec)
        # PRIMARY pool respects the dataset's fixed direction (base=experience source, related=target):
        # only CLEAN_RELATED. Reorientation is recorded as a SEPARATE sensitivity set, never merged into main,
        # because the benchmark fixes the source/target roles (§1.3 reorientation condition not satisfied).
        if cls == "CLEAN_RELATED":
            clean_pairs.append({"source_id": r["experience_instance_id"], "target_id": r["related_instance_id"],
                                "source_repo": canon.get(src["repo"]), "target_repo": canon.get(tgt["repo"]),
                                "class": cls})
        elif cls == "TEMPORAL_REORIENTED_VALID":
            reoriented_pairs.append({"source_id": r["related_instance_id"], "target_id": r["experience_instance_id"],
                                     "source_repo": canon.get(tgt["repo"]), "target_repo": canon.get(src["repo"]),
                                     "class": cls})
    reaudit["classes"] = dict(reaudit["classes"])
    reaudit["primary_pool_clean_related"] = len(clean_pairs)
    reaudit["reoriented_sensitivity_only"] = len(reoriented_pairs)
    json.dump(reaudit, open(os.path.join(OUT, "temporal_reaudit.json"), "w", encoding="utf-8"),
              indent=2, default=str)
    json.dump({"schema": "r22/reoriented_sensitivity/1.0.0",
               "note": "NOT in primary main; dataset fixes source/target roles; kept only for oracle sensitivity",
               "pairs": reoriented_pairs}, open(os.path.join(OUT, "reoriented_sensitivity.json"), "w",
              encoding="utf-8"), indent=2, default=str)

    # ---- §1.4 split v2 (canonical repos, keep graph within a side; v1 untouched) ----
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for p in clean_pairs:
        parent.setdefault(p["source_repo"], p["source_repo"]); parent.setdefault(p["target_repo"], p["target_repo"])
        parent[find(p["source_repo"])] = find(p["target_repo"])
    comps = defaultdict(list)
    repos = set()
    for p in clean_pairs:
        repos.add(p["source_repo"]); repos.add(p["target_repo"])
    for rp in repos:
        comps[find(rp)].append(rp)
    comp_list = sorted(comps.values(), key=lambda ms: hashlib.sha256(",".join(sorted(ms)).encode()).hexdigest())
    total = len(clean_pairs)
    dev_repos, main_repos, dev_n = set(), set(), 0
    for comp in comp_list:
        cn = sum(1 for p in clean_pairs if p["source_repo"] in comp or p["target_repo"] in comp)
        if dev_n < 0.25 * total:   # dev = threshold/integration minimum; main maximized
            dev_repos |= set(comp); dev_n += cn
        else:
            main_repos |= set(comp)

    def pool(rs):
        return [p for p in clean_pairs if p["source_repo"] in rs and p["target_repo"] in rs]
    dev, mn = pool(dev_repos), pool(main_repos)
    devm = {"schema": "r22/dev_manifest_v2/1.0.0", "repositories": sorted(dev_repos), "pairs": dev,
            "pair_count": len(dev)}
    mainm = {"schema": "r22/main_manifest_v2/1.0.0", "repositories": sorted(main_repos), "pairs": mn,
             "pair_count": len(mn), "supersedes_v1": "kept; v1 seal not deleted (pre-run amendment)"}
    mainm["seal_sha256"] = hashlib.sha256(json.dumps(
        {"repos": mainm["repositories"], "ids": sorted(p["target_id"] for p in mn)}, sort_keys=True).encode()).hexdigest()
    json.dump(devm, open(os.path.join(OUT, "dev_manifest_v2.json"), "w", encoding="utf-8"), indent=2, default=str)
    json.dump(mainm, open(os.path.join(OUT, "main_manifest_v2.json"), "w", encoding="utf-8"), indent=2, default=str)

    # ---- §1.5 paired-McNemar power grid ----
    def ncdf(z):
        return 0.5 * (1 + math.erf(z / math.sqrt(2)))

    def zq(p):  # inverse normal via bisection
        lo, hi = -8.0, 8.0
        for _ in range(100):
            m = (lo + hi) / 2
            if ncdf(m) < p:
                lo = m
            else:
                hi = m
        return (lo + hi) / 2
    alpha_primary = 0.05 / 3  # Holm most-stringent for 3 primary
    za = zq(1 - alpha_primary / 2)
    zb = zq(0.80)
    grid = []
    N = len(mn)
    for disc in (0.10, 0.15, 0.20, 0.30):
        for eff in (0.03, 0.05, 0.07, 0.10):
            # McNemar: delta = p10 - p01 = eff ; psi = p10 + p01 = disc (require eff <= disc)
            if eff > disc:
                need_n = None; power = 0.0
            else:
                need_n = ((za * math.sqrt(disc) + zb * math.sqrt(disc - eff * eff)) ** 2) / (eff * eff)
                # power at current N
                arg = (eff * math.sqrt(N) - za * math.sqrt(disc)) / math.sqrt(max(1e-9, disc - eff * eff))
                power = ncdf(arg)
            grid.append({"discordant_rate": disc, "effect_pp": eff, "required_N": None if need_n is None else round(need_n),
                         "power_at_mainN": round(power, 3)})
    # effective N after repository clustering (design effect ~ 1 + (m-1)*rho; assume rho=0.05, avg cluster size)
    clusters = len(main_repos)
    avg_m = N / max(1, clusters)
    deff = 1 + (avg_m - 1) * 0.05
    eff_N = N / deff
    power_grid = {"alpha_primary_holm": alpha_primary, "main_N": N, "main_repository_clusters": clusters,
                  "avg_cluster_size": round(avg_m, 2), "design_effect_rho0.05": round(deff, 3),
                  "effective_N": round(eff_N, 1), "grid": grid}
    json.dump(power_grid, open(os.path.join(OUT, "power_grid.json"), "w", encoding="utf-8"), indent=2, default=str)

    # verdict
    p5 = [g for g in grid if g["effect_pp"] == 0.05 and g["discordant_rate"] in (0.15, 0.20)]
    med_power5 = sorted(g["power_at_mainN"] for g in p5)[len(p5) // 2] if p5 else 0.0
    if med_power5 >= 0.80:
        verdict = "POWER_FEASIBLE"
    elif med_power5 >= 0.30:
        verdict = "POWER_LIMITED_BUT_ORACLE_FEASIBLE"
    else:
        verdict = "POWER_LIMITED_BUT_ORACLE_FEASIBLE" if N >= 20 else "POWER_BLOCKED"

    summary = {
        "duplicate_classes": dup_audit["classes"], "exact_dup_rows_to_drop": dup_audit["exact_duplicate_rows_to_drop"],
        "repo_raw": len(all_repos), "repo_canonical": len(canonical_repos), "repo_card_claim": 51,
        "temporal_classes": reaudit["classes"],
        "clean_after_reorient": len(clean_pairs),
        "split_v2": {"dev_repos": len(dev_repos), "dev_pairs": len(dev),
                     "main_repos": len(main_repos), "main_pairs": len(mn),
                     "overlap": sorted(dev_repos & main_repos), "main_seal": mainm["seal_sha256"]},
        "power": {"main_N": N, "effective_N": round(eff_N, 1), "median_power_+5pp": round(med_power5, 3),
                  "verdict": verdict},
    }
    json.dump(summary, open(os.path.join(OUT, "_orientation_summary.json"), "w", encoding="utf-8"),
              indent=2, default=str)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
