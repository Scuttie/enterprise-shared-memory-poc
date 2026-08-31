#!/usr/bin/env python3
"""Build the product-only ``COMPANY_HANDOFF_MANIFEST.json``.

The product handoff inventory is deliberately independent from TriMem/R23
research state. It hashes Git-tracked files only, never a live ``os.walk``
that could absorb local caches or build output. Research readiness is sealed
separately by its own artifact.
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


def _sha_file(path):
    # Newline-normalized so Windows and Linux agree for product text files.
    with open(path, "rb") as handle:
        data = handle.read()
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _git_files(relative=None):
    command = ["git", "ls-files", "-z"]
    if relative:
        command.extend(["--", relative])
    raw = subprocess.check_output(command, cwd=ROOT)
    return [item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item]


def _is_forbidden_tracked(path):
    parts = path.replace("\\", "/").split("/")
    return (
        any(part in FORBIDDEN_TRACKED_PARTS or part.endswith(".egg-info") for part in parts)
        or path.lower().endswith(FORBIDDEN_TRACKED_SUFFIXES)
    )


def _assert_tracked_tree_clean():
    bad = sorted(path for path in _git_files() if _is_forbidden_tracked(path))
    if bad:
        raise RuntimeError("tracked generated artifacts are forbidden: %s" % ", ".join(bad))


def _tree_hash(relative):
    entries = []
    for tracked in _git_files(relative):
        path = os.path.join(ROOT, *tracked.split("/"))
        if not os.path.isfile(path):
            raise RuntimeError("tracked handoff file missing from worktree: %s" % tracked)
        entries.append((tracked, _sha_file(path)))
    entries.sort()
    digest = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    return digest, len(entries)


def _commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    except Exception:
        return "unknown"


def _branch():
    try:
        return subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=ROOT
        ).decode().strip()
    except Exception:
        return ""


def _manifest_hash(manifest):
    body = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def build():
    _assert_tracked_tree_clean()
    source_hash, source_count = _tree_hash("src")
    docs_hash, docs_count = _tree_hash("docs")
    examples_hash, examples_count = _tree_hash("examples")
    manifest = {
        "schema_version": 2,
        "commit": _commit(),
        "manifest_scope": "PRODUCT_HANDOFF_ONLY_NOT_TRIMEM_RESEARCH_STATE",
        "hash_basis": "git ls-files -z (tracked files only; newline-normalized content)",
        "trimem_research_state_authority": "artifacts/trimem_v1/freeze.json",
        "project_version": "0.3.0rc1",
        "label": "COMPANY-HANDOFF-READY (gated on fresh-clone + offline demo) — NOT COMPANY-STAGING-CERTIFIED",
        "source_tree_sha256": source_hash,
        "source_files": source_count,
        "docs_tree_sha256": docs_hash,
        "docs_files": docs_count,
        "examples_tree_sha256": examples_hash,
        "examples_files": examples_count,
        "migration_head": "0015",
        "key_hashes": {
            relative: _sha_file(os.path.join(ROOT, relative))
            for relative in [
                "migrations/sql/0015_up.sql",
                "migrations/sql/0015_up.sha256",
                "openapi_v1.json",
                "pyproject.toml",
                "artifacts/p6/router_policy.json",
                "artifacts/p6/governance_thresholds.json",
                "examples/company_harness/tool_schema.json",
                "README.md",
                "docs/STATUS.yaml",
                "THIRD_PARTY_RESEARCH_REFERENCES.json",
            ]
            if os.path.isfile(os.path.join(ROOT, relative))
        },
        "rejected_if_tracked": ["__pycache__", "*.pyc", "*.pyo", "*.egg-info", "build", "dist"],
        "excluded": [
            "credentials",
            "private data",
            "benchmark gold patches/tests",
            "raw trajectories",
            "upstream MemGovern code/data",
            "local qdrant/postgres/s3 state",
            "untracked runtime output",
        ],
        "clone": "git clone <repo> && git checkout <commit>",
        "demo": "python scripts/demo_company_handoff.py --offline  # -> DEMO_PASS: true",
    }
    manifest["manifest_hash"] = _manifest_hash(manifest)
    return manifest


def main():
    check = "--check" in sys.argv
    if not check and _branch().startswith("codex/r23-"):
        print("refusing to rewrite product handoff manifest from an R23 research branch")
        return 2
    manifest = build()
    path = os.path.join(ROOT, "COMPANY_HANDOFF_MANIFEST.json")
    if check:
        if not os.path.isfile(path):
            print("handoff manifest missing")
            return 1
        with open(path, encoding="utf-8") as handle:
            old = json.load(handle)
        if old.get("manifest_hash") != _manifest_hash(old):
            print("handoff manifest self-hash INVALID")
            return 1
        # The commit changes when this generated manifest is committed. The
        # product inventory and its self-hash remain the authoritative check.
        expected = {key: value for key, value in manifest.items() if key not in ("manifest_hash", "commit")}
        observed = {key: value for key, value in old.items() if key not in ("manifest_hash", "commit")}
        if expected != observed:
            print("handoff manifest STALE (run without --check)")
            return 1
        print("handoff manifest current")
        return 0
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(
        "wrote COMPANY_HANDOFF_MANIFEST.json commit=%s src_files=%d"
        % (manifest["commit"][:12], manifest["source_files"])
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
