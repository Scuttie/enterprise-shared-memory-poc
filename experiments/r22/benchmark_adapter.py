#!/usr/bin/env python3
"""R22 §2/§4 — clean-room SWE-ContextBench audit + deterministic repository-level split.

No model calls. Reads only the MIT-licensed dataset parquets (never the unlicensed eval code). Emits:
  artifacts/r22/benchmark_lock.json
  artifacts/r22/source_target_relationships.json
  artifacts/r22/leakage_audit.json
  artifacts/r22/dev_manifest.json
  artifacts/r22/main_manifest.json
  artifacts/r22/partition_log.json
and returns a summary dict (also written to artifacts/r22/_audit_summary.json).

Grading itself is delegated to the official SWE-bench harness (see ci-r22-grader-smoke.yml); this module never
reimplements grading.
"""
import hashlib
import json
import os
import re
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.environ.get("R22_SCB_DATA",
                      "C:/Users/jewon/third_party_r22/swe-contextbench/data")
OUT = os.path.join(ROOT, "artifacts", "r22")
GH_COMMIT = "31bb04155f52b184bf31b220e3cff0607ac9c953"
DATASET = "jiayuanz3/SWEContextBench"
DATASET_LICENSE = "MIT"
EVAL_CODE_LICENSE = "NONE (no LICENSE file in eval repo) -> not vendored"


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(65536), b""):
            h.update(c)
    return h.hexdigest()


def _norm_hunks(patch):
    """Normalized set of added/removed code lines (ignore hunk headers, paths, whitespace)."""
    lines = set()
    for ln in (patch or "").splitlines():
        if ln[:1] in "+-" and not ln.startswith(("+++", "---")):
            body = re.sub(r"\s+", " ", ln[1:].strip())
            if body:
                lines.add(body)
    return lines


def _files(patch):
    return set(re.findall(r"^\+\+\+ b/(.+)$", patch or "", flags=re.M))


def main():
    os.makedirs(OUT, exist_ok=True)
    exp = pd.read_parquet(os.path.join(DATA, "SWEContextBench_Experience.parquet"))
    rel = pd.read_parquet(os.path.join(DATA, "SWEContextBench_Related.parquet"))
    rl = pd.read_parquet(os.path.join(DATA, "SWEContextBench_Relationship.parquet"))
    exp_by = {r["instance_id"]: r for _, r in exp.iterrows()}
    rel_by = {r["instance_id"]: r for _, r in rel.iterrows()}

    # ---- benchmark_lock ----
    lock = {
        "schema": "r22/benchmark_lock/1.0.0",
        "dataset": DATASET, "dataset_license": DATASET_LICENSE,
        "github_repo": "jiayuanz3/SWEContextBench", "github_commit": GH_COMMIT,
        "eval_code_license": EVAL_CODE_LICENSE,
        "grader": "official SWE-bench harness (clean-room adapter; eval code NOT vendored)",
        "files_sha256": {f: _sha(os.path.join(DATA, f)) for f in sorted(os.listdir(DATA))
                         if f.endswith(".parquet")},
        "rows": {"experience_base": int(len(exp)), "related_target": int(len(rel)),
                 "relationship": int(len(rl))},
        "repositories": sorted(set(exp["repo"]) | set(rel["repo"])),
        "repository_count": int(len(set(exp["repo"]) | set(rel["repo"]))),
        "base_repository_count": int(exp["repo"].nunique()),
        "field_completeness": {},
    }
    for col in ["base_commit", "environment_setup_commit", "FAIL_TO_PASS", "PASS_TO_PASS",
                "problem_statement", "patch", "test_patch", "created_at"]:
        miss_e = int(exp[col].isna().sum() + (exp[col] == "").sum()) if col in exp else -1
        miss_r = int(rel[col].isna().sum() + (rel[col] == "").sum()) if col in rel else -1
        lock["field_completeness"][col] = {"missing_in_base": miss_e, "missing_in_related": miss_r}
    lock["duplicate_base_instance_ids"] = int(exp["instance_id"].duplicated().sum())
    lock["duplicate_related_instance_ids"] = int(rel["instance_id"].duplicated().sum())
    json.dump(lock, open(os.path.join(OUT, "benchmark_lock.json"), "w", encoding="utf-8"),
              indent=2, default=str)

    # ---- relationships + temporal + leakage ----
    pairs = []
    leak = []
    counts = {"CLEAN_RELATED": 0, "NEAR_DUPLICATE": 0, "TARGET_ADJACENT": 0,
              "TARGET_PATCH_MATCH": 0, "TEMPORAL_INVALID": 0, "UNKNOWN": 0}
    for _, r in rl.iterrows():
        tgt_id = r["related_instance_id"]
        src_id = r["experience_instance_id"]
        t = rel_by.get(tgt_id)
        s = exp_by.get(src_id)
        rec = {"target_id": tgt_id, "source_id": src_id,
               "target_repo": None if t is None else t["repo"],
               "source_repo": None if s is None else s["repo"],
               "related_pr_url": r.get("related_pr_url"), "experience_pr_url": r.get("experience_pr_url")}
        if t is None or s is None:
            rec["class"] = "UNKNOWN"; rec["reason"] = "missing_row"
            counts["UNKNOWN"] += 1; pairs.append(rec); leak.append(rec); continue

        # temporal: source created before target
        try:
            s_t = pd.to_datetime(s["created_at"], utc=True)
            t_t = pd.to_datetime(t["created_at"], utc=True)
            temporal_ok = bool(s_t < t_t)
            rec["source_created_at"] = str(s["created_at"]); rec["target_created_at"] = str(t["created_at"])
        except Exception:
            temporal_ok = None
        rec["temporal_source_before_target"] = temporal_ok

        s_patch, t_patch = s["patch"] or "", t["patch"] or ""
        s_hash = hashlib.sha256(s_patch.encode()).hexdigest()
        t_hash = hashlib.sha256(t_patch.encode()).hexdigest()
        s_hunks, t_hunks = _norm_hunks(s_patch), _norm_hunks(t_patch)
        overlap = (len(s_hunks & t_hunks) / max(1, len(t_hunks))) if t_hunks else 0.0
        rec["patch_hash_equal"] = bool(s_hash == t_hash)
        rec["normalized_hunk_overlap"] = round(overlap, 4)
        rec["shared_files"] = sorted(_files(s_patch) & _files(t_patch))

        # target identity/answer leakage into source memory (problem/hints/patch/test)
        src_blob = " ".join(str(s.get(c, "")) for c in
                            ["problem_statement", "hints_text", "patch", "test_patch"])
        tgt_tokens = [str(tgt_id)]
        for u in [r.get("related_pr_url"), r.get("related_issue_url")]:
            if isinstance(u, str) and u:
                tgt_tokens.append(u.rsplit("/", 1)[-1])  # PR/issue number
        ftp = t.get("FAIL_TO_PASS") or ""
        target_id_in_source = any(tok and tok in src_blob for tok in tgt_tokens)
        target_test_in_source = bool(ftp) and str(ftp)[:40] in src_blob
        rec["target_id_or_url_in_source"] = bool(target_id_in_source)
        rec["target_failtopass_in_source"] = bool(target_test_in_source)

        # classify (order matters)
        if temporal_ok is False:
            cls = "TEMPORAL_INVALID"
        elif rec["patch_hash_equal"]:
            cls = "TARGET_PATCH_MATCH"
        elif target_id_in_source or target_test_in_source:
            cls = "TARGET_ADJACENT"
        elif overlap >= 0.60:
            cls = "NEAR_DUPLICATE"
        elif temporal_ok is None:
            cls = "UNKNOWN"
        else:
            cls = "CLEAN_RELATED"
        rec["class"] = cls
        counts[cls] += 1
        pairs.append(rec)
        leak.append({k: rec[k] for k in ("target_id", "source_id", "class",
                     "temporal_source_before_target", "patch_hash_equal", "normalized_hunk_overlap",
                     "target_id_or_url_in_source", "target_failtopass_in_source")})

    json.dump({"schema": "r22/relationships/1.0.0", "pairs": pairs},
              open(os.path.join(OUT, "source_target_relationships.json"), "w", encoding="utf-8"),
              indent=2, default=str)
    json.dump({"schema": "r22/leakage/1.0.0", "class_counts": counts, "pairs": leak},
              open(os.path.join(OUT, "leakage_audit.json"), "w", encoding="utf-8"),
              indent=2, default=str)

    # ---- §4 deterministic repository-level split (CLEAN_RELATED primary pool) ----
    clean = [p for p in pairs if p["class"] == "CLEAN_RELATED"]
    # build repository relation graph over CLEAN pairs; keep components on one side
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    repos_in_clean = set()
    for p in clean:
        union(p["source_repo"], p["target_repo"])
        repos_in_clean.add(p["source_repo"]); repos_in_clean.add(p["target_repo"])
    comps = {}
    for rp in repos_in_clean:
        comps.setdefault(find(rp), []).append(rp)
    # deterministic order components by SHA-256 of sorted member repos
    comp_list = sorted(comps.values(),
                       key=lambda ms: hashlib.sha256(",".join(sorted(ms)).encode()).hexdigest())
    total_pairs = len(clean)
    dev_repos, main_repos = set(), set()
    dev_pairs = 0
    log = []
    for comp in comp_list:
        cpairs = sum(1 for p in clean if p["source_repo"] in comp or p["target_repo"] in comp)
        # ~25% of CLEAN pairs to dev; assign whole components (never crossing the relation graph)
        if dev_pairs < 0.25 * total_pairs:
            dev_repos |= set(comp); dev_pairs += cpairs; side = "dev"
        else:
            main_repos |= set(comp); side = "main"
        log.append({"component_repos": sorted(comp), "pairs": cpairs, "assigned": side})

    def pool(side_repos):
        return [p for p in clean if p["source_repo"] in side_repos and p["target_repo"] in side_repos]

    dev = pool(dev_repos)
    mn = pool(main_repos)
    crossing = [p for p in clean if (p["source_repo"] in dev_repos) != (p["target_repo"] in dev_repos)]

    dev_manifest = {"schema": "r22/dev_manifest/1.0.0", "repositories": sorted(dev_repos),
                    "pairs": dev, "pair_count": len(dev)}
    main_manifest = {"schema": "r22/main_manifest/1.0.0", "repositories": sorted(main_repos),
                     "pairs": mn, "pair_count": len(mn),
                     "note": "SEALED before any model result is observed"}
    main_manifest["seal_sha256"] = hashlib.sha256(
        json.dumps({"repos": main_manifest["repositories"],
                    "ids": sorted(p["target_id"] for p in mn)}, sort_keys=True).encode()).hexdigest()
    part_log = {"schema": "r22/partition_log/1.0.0",
                "method": "CLEAN_RELATED only; repo-relation union-find components; SHA-256 component ordering; "
                          "~25% pairs to dev by whole-component assignment; graph never crosses split",
                "clean_pairs": total_pairs, "dev_pairs": len(dev), "main_pairs": len(mn),
                "crossing_pairs_excluded": len(crossing),
                "dev_repository_count": len(dev_repos), "main_repository_count": len(main_repos),
                "repository_overlap": sorted(dev_repos & main_repos), "components": log}
    json.dump(dev_manifest, open(os.path.join(OUT, "dev_manifest.json"), "w", encoding="utf-8"),
              indent=2, default=str)
    json.dump(main_manifest, open(os.path.join(OUT, "main_manifest.json"), "w", encoding="utf-8"),
              indent=2, default=str)
    json.dump(part_log, open(os.path.join(OUT, "partition_log.json"), "w", encoding="utf-8"),
              indent=2, default=str)

    summary = {"rows": lock["rows"], "repository_count": lock["repository_count"],
               "duplicate_base": lock["duplicate_base_instance_ids"],
               "duplicate_related": lock["duplicate_related_instance_ids"],
               "leakage_class_counts": counts,
               "split": {"dev_repos": len(dev_repos), "main_repos": len(main_repos),
                         "dev_pairs": len(dev), "main_pairs": len(mn),
                         "overlap": sorted(dev_repos & main_repos),
                         "crossing_excluded": len(crossing),
                         "main_seal": main_manifest["seal_sha256"]}}
    json.dump(summary, open(os.path.join(OUT, "_audit_summary.json"), "w", encoding="utf-8"),
              indent=2, default=str)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
