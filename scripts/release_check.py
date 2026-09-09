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
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

_HOST = "\ub2e4\ub978 \ucef4\ud4e8\ud130"   # the host drive label; must never appear in released text
FORBIDDEN_PATH = ["C:\\Users\\jewon", "C:/Users/jewon", _HOST, "vscode-webview",
                  "AppData\\Local\\Temp\\claude", "AppData/Local/Temp/claude"]
FORBIDDEN_CRED = ["ghp_", "github_pat_", "AKIA", "-----BEGIN ", "up_live_"]
EXEMPT = {"src/enterprise_memory/promotion/security_scan.py", "tests/security/test_scanner.py",
          "tests/unit/test_promotion.py", "scripts/release_check.py", "tests/service/test_service.py",
          "src/enterprise_memory/persistence/postgres/repos.py", "tests/postgres/test_p2_0.py",
          "tests/postgres/test_p2_start.py", "src/enterprise_memory/providers/redaction.py",
          "tests/solar/test_solar_provider.py",
          # OSS release secret/path detector — legitimately defines credential patterns, like this file itself
          "scripts/oss_release_acceptance.py"}
SKIP_DIR = ("__pycache__", ".git", ".venv", "venv", "dist", "build", "reports", "data")

# Public GitHub API commit objects can contain ASCII-armored *signatures* in
# ``commit.verification.signature``.  They are provenance, not private-key
# material.  Keep the product scan broad and make this one exception only
# after proving that the response is a content-addressed entry in the
# credential-free research capture index.  A malformed, renamed, unindexed,
# non-GitHub, or non-JSON artifact falls back to the ordinary fail-closed scan.
PUBLIC_GITHUB_RAW_PREFIX = "artifacts/trimem_v1/dev_activation_diagnostic/github_raw/"
PUBLIC_GITHUB_CAPTURE_INDEX = (
    "artifacts/trimem_v1/dev_activation_diagnostic/source_chronology_cache.json"
)
GITHUB_JSON_ACCEPT = "application/vnd.github+json"
_CONTENT_ADDRESSED_GITHUB_JSON = re.compile(
    r"artifacts/trimem_v1/dev_activation_diagnostic/github_raw/([0-9a-f]{64})\.json\Z"
)
_GIT_SIGNATURE_ARMOR = {
    "PGP": ("-----BEGIN PGP SIGNATURE-----", "-----END PGP SIGNATURE-----"),
    "SSH": ("-----BEGIN SSH SIGNATURE-----", "-----END SSH SIGNATURE-----"),
}
_BASE64_ARMOR_LINE = re.compile(r"[A-Za-z0-9+/=]+\Z")


def _strict_json_object(raw, label):
    """Decode a BOM-free JSON object without permissive replacement."""

    if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
        raise ValueError("invalid encoded JSON: %s" % label)

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key: %s" % label)
            value[key] = item
        return value

    def reject_constant(_value):
        raise ValueError("non-finite JSON number: %s" % label)

    value = json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("JSON root is not an object: %s" % label)
    return value


def _indexed_public_github_json(rel, raw):
    """Return parsed bytes only for an exact, indexed public GitHub response."""

    match = _CONTENT_ADDRESSED_GITHUB_JSON.fullmatch(rel)
    if match is None or hashlib.sha256(raw).hexdigest() != match.group(1):
        return None
    index_path = os.path.join(ROOT, *PUBLIC_GITHUB_CAPTURE_INDEX.split("/"))
    if not os.path.isfile(index_path) or os.path.islink(index_path):
        return None
    try:
        index = _strict_json_object(io.open(index_path, "rb").read(), "capture index")
        value = _strict_json_object(raw, rel)
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    rows = index.get("request_cache")
    expected_path = "github_raw/%s.json" % match.group(1)
    matches = [
        row
        for row in rows if isinstance(row, dict)
        and row.get("path") == expected_path
        and row.get("raw_sha256") == match.group(1)
        and row.get("accept") == GITHUB_JSON_ACCEPT
        and isinstance(row.get("url"), str)
        and row["url"].startswith("https://api.github.com/repos/")
    ] if isinstance(rows, list) else []
    return value if len(matches) == 1 else None


def _is_public_git_signature(value):
    """Recognize only PGP/SSH signature armor, never key/certificate armor."""

    if not isinstance(value, str) or "\x00" in value or "\r" in value:
        return False
    lines = value.rstrip("\n").split("\n")
    if len(lines) < 3:
        return False
    for begin, end in _GIT_SIGNATURE_ARMOR.values():
        if lines[0] != begin or lines[-1] != end:
            continue
        body = lines[1:-1]
        return any(body) and all(
            not line
            or line == "Version: GnuPG v2"
            or _BASE64_ARMOR_LINE.fullmatch(line) is not None
            for line in body
        )
    return False


def _scrub_verification_object(value):
    """Project one exact GitHub commit ``verification`` object."""

    if not isinstance(value, dict):
        return value
    projected = dict(value)
    signature = projected.get("signature")
    verification_shape = {
        "verified", "reason", "signature", "payload", "verified_at"
    }
    if (
        verification_shape <= set(value)
        and isinstance(value.get("verified"), bool)
        and isinstance(value.get("reason"), str)
        and (value.get("payload") is None or isinstance(value.get("payload"), str))
        and (value.get("verified_at") is None or isinstance(value.get("verified_at"), str))
        and _is_public_git_signature(signature)
    ):
        projected["signature"] = (
            "PUBLIC_GIT_SIGNATURE_SHA256:" + hashlib.sha256(signature.encode("utf-8")).hexdigest()
        )
    return projected


def _scrub_commit_object(value):
    if not isinstance(value, dict):
        return value
    projected = dict(value)
    if "verification" in projected:
        projected["verification"] = _scrub_verification_object(
            projected["verification"]
        )
    return projected


def _scrub_verified_git_signatures(value):
    """Project only documented GitHub commit and compare-response locations."""

    projected = dict(value)
    if "commit" in projected:
        projected["commit"] = _scrub_commit_object(projected["commit"])
    for key in ("base_commit", "merge_base_commit"):
        item = projected.get(key)
        if isinstance(item, dict) and "commit" in item:
            projected[key] = {
                **item,
                "commit": _scrub_commit_object(item.get("commit")),
            }
    commits = projected.get("commits")
    if isinstance(commits, list):
        projected["commits"] = [
            {
                **item,
                "commit": _scrub_commit_object(item.get("commit")),
            }
            if isinstance(item, dict) and "commit" in item
            else item
            for item in commits
        ]
    return projected


def _credential_scan_text(rel, raw, text):
    """Project indexed public signature material; scan everything else verbatim."""

    if not rel.startswith(PUBLIC_GITHUB_RAW_PREFIX) or "-----BEGIN " not in text:
        return text
    value = _indexed_public_github_json(rel, raw)
    if value is None:
        return text
    return json.dumps(
        _scrub_verified_git_signatures(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


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
                raw = io.open(os.path.join(root, fn), "rb").read()
                t = raw.decode("utf-8", errors="strict")
            except Exception:
                continue
            if rel != "scripts/release_check.py":     # the detector defines these patterns as source
                for s in FORBIDDEN_PATH:
                    if s in t:
                        hits.append((rel, "path"))
            if rel not in EXEMPT:
                credential_text = _credential_scan_text(rel, raw, t)
                for s in FORBIDDEN_CRED:
                    if s in credential_text:
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
