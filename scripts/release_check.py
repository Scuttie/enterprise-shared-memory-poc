#!/usr/bin/env python
"""Credential-free release integrity checks used by CI and local validation.
  --openapi   regenerate the FastAPI OpenAPI and confirm every committed endpoint path is present
  --manifest  verify RELEASE_MANIFEST.json hashes match the shipped files
  --secrets   scan the whole tree for forbidden path/credential substrings (fail on any)
"""
import os
import sys
import io
import json
import hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

_HOST = "\ub2e4\ub978 \ucef4\ud4e8\ud130"   # the host drive label; must never appear in released text
FORBIDDEN_PATH = ["C:\\Users\\jewon", "C:/Users/jewon", _HOST, "vscode-webview",
                  "AppData\\Local\\Temp\\claude", "AppData/Local/Temp/claude"]
FORBIDDEN_CRED = ["ghp_", "github_pat_", "AKIA", "-----BEGIN ", "up_live_"]
EXEMPT = {"src/enterprise_memory/promotion/security_scan.py", "tests/security/test_scanner.py",
          "tests/unit/test_promotion.py", "scripts/release_check.py", "tests/service/test_service.py"}
SKIP_DIR = ("__pycache__", ".git", ".venv", "venv", "dist", "build", "reports", "data")


def check_openapi():
    from enterprise_memory.serving import api
    spec = api.create_app().openapi()
    committed = json.load(io.open(os.path.join(ROOT, "openapi.json"), encoding="utf-8"))
    missing = set((committed.get("paths") or {}).keys()) - set((spec.get("paths") or {}).keys())
    if missing:
        print("OPENAPI MISSING PATHS:", missing)
        return 1
    print("OPENAPI OK (%d endpoints present)" % len(committed.get("paths") or {}))
    return 0


def check_manifest():
    man = json.load(io.open(os.path.join(ROOT, "RELEASE_MANIFEST.json"), encoding="utf-8"))
    bad = 0
    for f in man["files"]:
        p = os.path.join(ROOT, f["dest"])
        if not os.path.exists(p):
            print("MANIFEST MISSING:", f["dest"])
            bad += 1
            continue
        h = hashlib.sha256(io.open(p, "r", encoding="utf-8").read().encode()).hexdigest()
        if h != f["sha256"]:
            print("MANIFEST HASH MISMATCH:", f["dest"])
            bad += 1
    if bad:
        return 1
    print("MANIFEST OK (%d files verified)" % len(man["files"]))
    return 0


def check_secrets():
    hits = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIR]
        for fn in files:
            if not fn.endswith((".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt", ".lock", ".example", ".cfg")):
                continue
            rel = os.path.relpath(os.path.join(root, fn), ROOT).replace("\\", "/")
            try:
                t = io.open(os.path.join(root, fn), "r", encoding="utf-8").read()
            except Exception:
                continue
            if rel != "scripts/release_check.py":     # the detector defines these patterns as source
                for s in FORBIDDEN_PATH:
                    if s in t:
                        hits.append((rel, "path"))
            if rel not in EXEMPT:
                for s in FORBIDDEN_CRED:
                    if s in t:
                        hits.append((rel, "cred:%s" % s))
    if hits:
        print("SECRET/PATH HITS:", hits[:20])
        return 1
    print("SECRET SCAN CLEAN")
    return 0


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"--openapi": check_openapi, "--manifest": check_manifest, "--secrets": check_secrets}.get(a)
    if not fn:
        print("usage: release_check.py --openapi|--manifest|--secrets")
        sys.exit(2)
    sys.exit(fn())
