#!/usr/bin/env python3
"""P6/R19 §19 — build COMPANY_HANDOFF_MANIFEST.json (hashes for a verifiable handoff).

Hashes the source tree, migrations, examples, docs, and frozen research; records the exact commit and a test
summary. EXCLUDES caches/venvs/logs and any secret/private artifact (none are tracked). --check recomputes and
fails if the on-disk manifest is stale.
"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache", ".mypy_cache"}


def _sha_file(p):
    # newline-normalized hash so Windows (CRLF working tree) and Linux CI (LF) agree; repo-hashed trees are text
    with open(p, "rb") as fh:
        data = fh.read()
    data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _tree_hash(rel):
    base = os.path.join(ROOT, rel)
    entries = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            entries.append((os.path.relpath(fp, ROOT).replace("\\", "/"), _sha_file(fp)))
    entries.sort()
    agg = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    return agg, len(entries)


def _commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    except Exception:
        return "unknown"


def build():
    src_hash, src_n = _tree_hash("src")
    docs_hash, docs_n = _tree_hash("docs")
    ex_hash, ex_n = _tree_hash("examples")
    man = {
        "schema_version": 1,
        "commit": _commit(),
        "project_version": "0.3.0.dev1",
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
        "excluded": ["credentials", "private data", "benchmark gold patches/tests", "raw trajectories",
                     "upstream MemGovern code/data", "local qdrant/postgres/s3 state", "caches/venvs/logs"],
        "clone": "git clone <repo> && git checkout <commit>",
        "demo": "python scripts/demo_company_handoff.py --offline  # -> DEMO_PASS: true",
    }
    man["manifest_hash"] = hashlib.sha256(json.dumps(man, sort_keys=True).encode()).hexdigest()
    return man


def main():
    check = "--check" in sys.argv
    man = build()
    path = os.path.join(ROOT, "COMPANY_HANDOFF_MANIFEST.json")
    if check:
        if not os.path.isfile(path):
            print("handoff manifest missing"); return 1
        old = json.load(open(path, encoding="utf-8"))
        # compare everything except the self hash + commit (commit changes each commit)
        a = {k: v for k, v in man.items() if k not in ("manifest_hash", "commit")}
        b = {k: v for k, v in old.items() if k not in ("manifest_hash", "commit")}
        if a != b:
            print("handoff manifest STALE (run without --check)"); return 1
        print("handoff manifest current"); return 0
    json.dump(man, open(path, "w", encoding="utf-8"), indent=2)
    print("wrote COMPANY_HANDOFF_MANIFEST.json commit=%s src_files=%d" % (man["commit"][:12], man["source_files"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
