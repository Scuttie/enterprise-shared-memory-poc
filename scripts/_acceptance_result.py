#!/usr/bin/env python3
"""Shared writer for reports/company_acceptance_result.json (called by company_acceptance_check.sh/.ps1).
Args: test_passed test_count demo_passed docs_passed pkg_passed manifest_ok secret_scan_clean overall_pass"""
import sys, json, hashlib, platform, subprocess, datetime, os, re, glob


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if p and os.path.isfile(p) else None


def gitv(a):
    try:
        return subprocess.check_output(["git"] + a).decode().strip()
    except Exception:
        return "unknown"


def yn(s):
    return str(s).lower() in ("true", "1", "yes")


def main():
    a = (sys.argv + ["", "", "", "", "", "", "", ""])[1:9]
    testp, testc, demop, docsp, pkgp, manok, scan, overall = a
    ver = "unknown"
    try:
        ver = re.search(r'version\s*=\s*"([^"]+)"', open("pyproject.toml", encoding="utf-8").read()).group(1)
    except Exception:
        pass
    whl = (glob.glob("dist/*.whl") or [None])[0]
    sdist = (glob.glob("dist/*.tar.gz") or [None])[0]
    res = {
        "commit_sha": gitv(["rev-parse", "HEAD"]), "branch": gitv(["rev-parse", "--abbrev-ref", "HEAD"]),
        "package_version": ver, "timestamp_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "python_version": platform.python_version(), "os": platform.system() + " " + platform.release(),
        "test_passed": yn(testp), "test_count": int(testc) if str(testc).isdigit() else None,
        "demo_passed": yn(demop), "docs_check_passed": yn(docsp), "package_passed": yn(pkgp),
        "release_check_passed": yn(manok), "manifest_current": yn(manok), "secret_scan_clean": yn(scan),
        "wheel_filename": os.path.basename(whl) if whl else None, "wheel_sha256": sha(whl),
        "sdist_filename": os.path.basename(sdist) if sdist else None, "sdist_sha256": sha(sdist),
        "known_limitations": [
            "General memory coding-performance lift NOT ESTABLISHED (R14-R20 null).",
            "Utility-router incremental efficacy NULL / NOT ESTABLISHED (R19 small-sample positive did not replicate in R20).",
            "Not company-staging-certified; no company sign-off. Not production-certified.",
        ],
        "required_company_inputs": [
            "model/harness manifest (id+revision+protocol)", "OIDC issuer/JWKS",
            "PostgreSQL + Qdrant deployment targets", "repository access policy", "secret manager",
            "staging env + sign-off",
        ],
        "overall_pass": yn(overall),
    }
    json.dump(res, open("reports/company_acceptance_result.json", "w"), indent=2)
    print("wrote reports/company_acceptance_result.json overall_pass=%s" % res["overall_pass"])


if __name__ == "__main__":
    main()
