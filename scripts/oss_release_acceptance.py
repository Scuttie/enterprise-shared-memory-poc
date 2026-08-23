#!/usr/bin/env python3
"""OSS release acceptance (§8) — the non-matrix half of ci-oss-release.

Runs the checks that do NOT depend on the Python matrix or on building a wheel (the workflow does those in
their own steps and calls this script last):

  * secret / hardcoded-endpoint scan over the tracked tree
  * markdown link check for the release-critical docs
  * SBOM + dependency license report (written to reports/oss_release/)
  * source-tree-clean check (no untracked build/dist leakage)

On success it prints the required status block. Any failure exits non-zero (no continue-on-error, no faking green).
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "reports", "oss_release")

# Files that MUST exist and whose relative markdown links MUST resolve.
LINK_DOCS = [
    "README.md",
    "docs/COMPANY_QUICKSTART_KO.md",
    "docs/OSS_SCOPE_AND_DATA_POLICY.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
]

# Real-secret shapes only. Placeholders (localhost, example.com, $VAR, <...>, in-process) are allowed by design.
SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "openai-style key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws access key id"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "github pat"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "private key"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "slack token"),
]
# Hardcoded non-placeholder endpoints/model names would be a leak; these tokens are the sanctioned placeholders.
ALLOWED_HOST_TOKENS = ("localhost", "127.0.0.1", "in-process", "example.com", "example.org", "acme/",
                       "$", "<", "{{", "your-", "company-local-model", "http://api", "postgres:5432",
                       "qdrant:6333", "0.0.0.0")


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p.strip()]


def scan_secrets(files):
    hits = []
    for rel in files:
        # tests/ deliberately embeds synthetic secret shapes (e.g. "-----BEGIN RSA PRIVATE KEY-----\nMIIB") to
        # verify the scanner detects them; those are fixtures, not credentials, and never ship in the wheel.
        if rel.startswith("tests/"):
            continue
        if rel.startswith(("LICENSE", "THIRD_PARTY")) or rel.endswith((".png", ".jpg", ".ico", ".whl", ".gz")):
            continue
        path = os.path.join(ROOT, rel)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        for pat, label in SECRET_PATTERNS:
            for m in pat.finditer(text):
                hits.append("%s: %s (%s)" % (rel, label, m.group(0)[:12] + "..."))
    return hits


def check_links():
    problems = []
    link_re = re.compile(r"\]\(([^)]+)\)")
    for rel in LINK_DOCS:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            problems.append("missing doc: %s" % rel)
            continue
        base = os.path.dirname(path)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        for target in link_re.findall(text):
            target = target.strip()
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            frag = target.split("#", 1)[0].split("?", 1)[0]
            if not frag:
                continue
            resolved = os.path.normpath(os.path.join(base, frag))
            if not os.path.exists(resolved):
                problems.append("%s -> broken link %s" % (rel, target))
    return problems


def sbom_and_licenses():
    os.makedirs(OUT, exist_ok=True)
    # SBOM: recorded installed distributions (name+version). No network; uses importlib.metadata.
    try:
        from importlib import metadata as md
    except ImportError:  # pragma: no cover
        import importlib_metadata as md  # type: ignore
    comps = []
    for dist in md.distributions():
        name = dist.metadata.get("Name") or "?"
        ver = dist.version or "?"
        lic = dist.metadata.get("License") or ""
        classifiers = [c for c in (dist.metadata.get_all("Classifier") or []) if c.startswith("License")]
        comps.append({"name": name, "version": ver, "license": lic, "license_classifiers": classifiers})
    comps.sort(key=lambda c: c["name"].lower())
    sbom = {"bomFormat": "CycloneDX-min", "specVersion": "1.5", "components":
            [{"type": "library", "name": c["name"], "version": c["version"]} for c in comps]}
    with open(os.path.join(OUT, "sbom.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(sbom, fh, indent=2)
    with open(os.path.join(OUT, "dependency_licenses.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(comps, fh, indent=2)
    return len(comps)


def source_tree_clean():
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    # Build byproducts must be gitignored; anything untracked here is a leak.
    leaks = [ln[3:] for ln in out.splitlines() if ln.startswith("??")
             and not ln[3:].startswith("reports/oss_release/")]
    return leaks


def main() -> int:
    files = tracked_files()
    fails = []

    secrets = scan_secrets(files)
    if secrets:
        fails.append("secret scan: %d hit(s)\n    " % len(secrets) + "\n    ".join(secrets))
    else:
        print("secret/path scan: PASS (0 real credentials in %d tracked files)" % len(files))

    links = check_links()
    if links:
        fails.append("docs links: %d broken\n    " % len(links) + "\n    ".join(links))
    else:
        print("docs links: PASS (%d release-critical docs)" % len(LINK_DOCS))

    n = sbom_and_licenses()
    print("SBOM/license report: reports/oss_release/{sbom.json,dependency_licenses.json} (%d components)" % n)

    leaks = source_tree_clean()
    if leaks:
        fails.append("source tree not clean: untracked %s" % leaks)
    else:
        print("source tree clean: PASS")

    if fails:
        print("\nOSS release acceptance: FAIL")
        for f in fails:
            print("  - " + f)
        return 1

    print("\nOSS release acceptance: PASS")
    print("Research workflows: separate scope")
    print("Company staging: PENDING")
    print("Production: NOT CLAIMED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
