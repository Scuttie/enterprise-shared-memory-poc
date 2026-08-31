#!/usr/bin/env python3
"""Build the *product* COMPANY_HANDOFF_MANIFEST.json.

This manifest is deliberately independent from R23 research state.  Tree hashes are computed from Git-tracked
files, never a live ``os.walk`` (which can accidentally absorb ``.pyc``/egg-info/build output).  Tracked generated
artifacts are rejected.  R23 research state is sealed separately under ``artifacts/r23``.
"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORBIDDEN_TRACKED_PARTS = {"__pycache__", "build", "dist"}
FORBIDDEN_TRACKED_SUFFIXES = (".pyc", ".pyo")


def _sha_file(p):
    # newline-normalized hash so Windows (CRLF working tree) and Linux CI (LF) agree; repo-hashed trees are text
    with open(p, "rb") as fh:
        data = fh.read()
    data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _git_files(rel=None):
    cmd = ["git", "ls-files", "-z"]
    if rel:
        cmd.extend(["--", rel])
    raw = subprocess.check_output(cmd, cwd=ROOT)
    return [p.decode("utf-8", "surrogateescape") for p in raw.split(b"\0") if p]


def _is_forbidden_tracked(path):
    parts = path.replace("\\", "/").split("/")
    return (
        any(part in FORBIDDEN_TRACKED_PARTS or part.endswith(".egg-info") for part in parts)
        or path.lower().endswith(FORBIDDEN_TRACKED_SUFFIXES)
    )


def _assert_tracked_tree_clean():
    bad = sorted(p for p in _git_files() if _is_forbidden_tracked(p))
    if bad:
        raise RuntimeError("tracked generated artifacts are forbidden: %s" % ", ".join(bad))


def _tree_hash(rel):
    entries = []
    for tracked in _git_files(rel):
        fp = os.path.join(ROOT, *tracked.split("/"))
        if not os.path.isfile(fp):
            raise RuntimeError("tracked handoff file missing from worktree: %s" % tracked)
        entries.append((tracked, _sha_file(fp)))
    entries.sort()
    agg = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    return agg, len(entries)


def _commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    except Exception:
        return "unknown"


def _manifest_hash(manifest):
    body = {k: v for k, v in manifest.items() if k != "manifest_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def build():
    _assert_tracked_tree_clean()
    src_hash, src_n = _tree_hash("src")
    docs_hash, docs_n = _tree_hash("docs")
    ex_hash, ex_n = _tree_hash("examples")
    man = {
        "schema_version": 2,
        "commit": _commit(),
        "manifest_scope": "PRODUCT_HANDOFF_ONLY_NOT_R23_RESEARCH_STATE",
        "hash_basis": "git ls-files (tracked files only; newline-normalized content)",
        "project_version": "0.3.0rc1",
        "label": "COMPANY-HANDOFF-READY (gated on fresh-clone + offline demo) — NOT COMPANY-STAGING-CERTIFIED",
        "source_tree_sha256": src_hash, "source_files": src_n,
        "docs_tree_sha256": docs_hash, "docs_files": docs_n,
        "examples_tree_sha256": ex_hash, "examples_files": ex_n,
        "migration_head": "0014",
        "key_hashes": {rel: _sha_file(os.path.join(ROOT, rel)) for rel in [
            "migrations/sql/0014_up.sql", "migrations/sql/0014_up.sha256", "openapi_v1.json", "pyproject.toml",
            "artifacts/p6/router_policy.json", "artifacts/p6/governance_thresholds.json",
            "examples/company_harness/tool_schema.json", "README.md", "docs/STATUS.yaml",
            "THIRD_PARTY_RESEARCH_REFERENCES.json"] if os.path.isfile(os.path.join(ROOT, rel))},
        "rejected_if_tracked": ["__pycache__", "*.pyc", "*.pyo", "*.egg-info", "build", "dist"],
        "excluded": ["credentials", "private data", "benchmark gold patches/tests", "raw trajectories",
                     "upstream MemGovern code/data", "local qdrant/postgres/s3 state", "untracked runtime output"],
        "clone": "git clone <repo> && git checkout <commit>",
        "demo": "python scripts/demo_company_handoff.py --offline  # -> DEMO_PASS: true",
    }
    man["manifest_hash"] = _manifest_hash(man)
    return man


def main():
    check = "--check" in sys.argv
    man = build()
    path = os.path.join(ROOT, "COMPANY_HANDOFF_MANIFEST.json")
    if check:
        if not os.path.isfile(path):
            print("handoff manifest missing"); return 1
        old = json.load(open(path, encoding="utf-8"))
        if old.get("manifest_hash") != _manifest_hash(old):
            print("handoff manifest self-hash INVALID"); return 1
        # compare everything except the self hash + commit (commit changes each commit)
        a = {k: v for k, v in man.items() if k not in ("manifest_hash", "commit")}
        b = {k: v for k, v in old.items() if k not in ("manifest_hash", "commit")}
        if a != b:
            print("handoff manifest STALE (run without --check)"); return 1
        print("handoff manifest current"); return 0
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT).decode().strip()
    if branch.startswith("codex/r23-"):
        print("refusing to rewrite product handoff manifest from an R23 research branch")
        return 2
    json.dump(man, open(path, "w", encoding="utf-8"), indent=2)
    print("wrote COMPANY_HANDOFF_MANIFEST.json commit=%s src_files=%d" % (man["commit"][:12], man["source_files"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
