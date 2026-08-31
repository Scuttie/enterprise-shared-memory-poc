#!/usr/bin/env python3
"""Build/check the R23 research seal without touching product handoff artifacts.

The candidate file set comes from Git's index plus non-ignored R23 worktree additions; no live directory walk is
used.  A seal containing untracked additions is explicitly labelled a worktree candidate, never a commit or final
experiment endpoint.  After commit, the same builder naturally becomes a tracked-files-only seal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEAL_REL = "artifacts/r23/research_seal.json"
FORBIDDEN_PARTS = {"__pycache__", "build", "dist"}


def _git_files(*args: str) -> list[str]:
    raw = subprocess.check_output(["git", *args, "-z"], cwd=ROOT)
    return [p.decode("utf-8", "surrogateescape") for p in raw.split(b"\0") if p]


def _is_r23_path(path: str) -> bool:
    p = path.replace("\\", "/")
    return (
        p.startswith("artifacts/r23/")
        or p.startswith("experiments/r23/")
        or p.startswith("tests/r23/")
        or (p.startswith("reports/R23_") and p.endswith(".md"))
        or (p.startswith("scripts/r23_") and p.endswith(".py"))
        or (p.startswith(".github/workflows/ci-r23-") and p.endswith(".yml"))
    )


def _forbidden(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return (
        any(part in FORBIDDEN_PARTS or part.endswith(".egg-info") for part in parts)
        or path.lower().endswith((".pyc", ".pyo"))
    )


def _sha(path: str) -> str:
    with open(os.path.join(ROOT, *path.split("/")), "rb") as handle:
        data = handle.read().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _manifest_hash(obj: dict) -> str:
    body = {k: v for k, v in obj.items() if k != "manifest_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build() -> dict:
    tracked = {p for p in _git_files("ls-files") if _is_r23_path(p)}
    additions = {
        p for p in _git_files("ls-files", "--others", "--exclude-standard") if _is_r23_path(p)
    }
    paths = sorted((tracked | additions) - {SEAL_REL})
    bad = [p for p in paths if _forbidden(p)]
    if bad:
        raise RuntimeError("generated artifacts are forbidden in R23 seal: %s" % ", ".join(bad))
    missing = [p for p in paths if not os.path.isfile(os.path.join(ROOT, *p.split("/")))]
    if missing:
        raise RuntimeError("R23 seal input missing: %s" % ", ".join(missing))
    entries = [{"path": p, "sha256": _sha(p)} for p in paths]
    tree_hash = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    state_path = os.path.join(ROOT, "artifacts", "r23", "research_state.json")
    state = json.load(open(state_path, encoding="utf-8"))["state"]
    result = {
        "schema_version": "r23/research_seal/1.1.0",
        "experiment": "REALBENCH_R23_SEMANTIC_SUBTASK_GRAPH_V1",
        "seal_phase": "WORKTREE_CANDIDATE_NOT_FINAL_ENDPOINT" if additions else "TRACKED_TREE_NOT_FINAL_ENDPOINT",
        "commit_binding": "CONTENT_HASH_ONLY; verify the enclosing Git commit and remote head externally",
        "file_basis": "git index plus non-ignored R23 additions; never os.walk",
        "tracked_file_count": len(tracked - {SEAL_REL}),
        "untracked_candidate_count": len(additions - {SEAL_REL}),
        "r23_file_count": len(entries),
        "r23_tree_sha256": tree_hash,
        "files": entries,
        "state": state,
        "product_artifacts_excluded": ["COMPANY_HANDOFF_MANIFEST.json", "docs/STATUS.yaml"],
        "paid_model_calls": 0,
        "final_endpoint": False,
    }
    result["manifest_hash"] = _manifest_hash(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.check and args.write:
        parser.error("--check and --write are mutually exclusive")
    current = build()
    if args.write:
        path = os.path.join(ROOT, *SEAL_REL.split("/"))
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(current, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
        print("wrote R23 research seal")
        return 0
    if not args.check:
        print(json.dumps(current, indent=2, ensure_ascii=True))
        return 0
    path = os.path.join(ROOT, *SEAL_REL.split("/"))
    if not os.path.isfile(path):
        print("R23 research seal missing")
        return 1
    old = json.load(open(path, encoding="utf-8"))
    if old.get("manifest_hash") != _manifest_hash(old):
        print("R23 research seal self-hash invalid")
        return 1
    if old != current:
        print("R23 research seal stale")
        return 1
    print("R23 research seal current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
