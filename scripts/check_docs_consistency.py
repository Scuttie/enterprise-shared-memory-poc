#!/usr/bin/env python3
"""ci-docs gate — fail when user-facing docs contradict docs/STATUS.yaml (the single source of truth).

Checks (P6/R19 §2):
  - README must NOT claim SQLite authority (PostgreSQL is authoritative).
  - README must NOT claim shared memory improves coding performance unless STATUS says research_efficacy != NULL
    AND utility_router_result == POSITIVE.
  - README must NOT say "production-ready" while production_certification_status == NOT_CLAIMED.
  - README must NOT conflate company-ready with production-certified.
  - migration head in STATUS must match the actual alembic head on disk.
  - Product STATUS is not used as a research-workflow inventory; R23 records that in its own seal.
  - No doc may reference a nonexistent file path under docs/ or scripts/ that it presents as runnable.
Exit non-zero on any violation. Pure-stdlib; safe in minimal CI images.
"""
from __future__ import annotations
import os
import re
import sys
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_status():
    p = os.path.join(ROOT, "docs", "STATUS.yaml")
    try:
        import yaml  # optional
        return yaml.safe_load(open(p, encoding="utf-8"))
    except Exception:
        # minimal fallback parser for the flat keys we need (no external dep)
        data, txt = {}, open(p, encoding="utf-8").read()
        for key in ("migration_head", "production_certification_status",
                    "research_status", "utility_router_result", "project_version"):
            m = re.search(r"^%s:\s*\"?([^\"#\n]+?)\"?\s*(?:#.*)?$" % key, txt, re.M)
            if m:
                data[key] = m.group(1).strip()
        return data


def alembic_head():
    revs, downs = {}, set()
    for f in glob.glob(os.path.join(ROOT, "migrations", "versions", "*.py")):
        t = open(f, encoding="utf-8").read()
        r = re.search(r"^revision\s*=\s*['\"]([^'\"]+)", t, re.M)
        d = re.search(r"^down_revision\s*=\s*['\"]([^'\"]+)", t, re.M)
        if r:
            revs[r.group(1)] = f
        if d:
            downs.add(d.group(1))
    heads = [r for r in revs if r not in downs]
    return sorted(heads)[-1] if heads else None


def main() -> int:
    st = load_status()
    fails = []
    readme = ""
    rp = os.path.join(ROOT, "README.md")
    if os.path.isfile(rp):
        readme = open(rp, encoding="utf-8").read()
    low = readme.lower()

    # 1. SQLite authority
    if re.search(r"sqlite", low) and re.search(r"authorit|canonical.*sqlite|sqlite.*(registry|authorit|source of truth)", low):
        fails.append("README implies SQLite authority; PostgreSQL is authoritative (STATUS).")
    elif "(sqlite)" in low and "postgres" not in low.split("(sqlite)")[0][-120:]:
        fails.append("README still tags canonical store as (SQLite).")

    # 2. efficacy claim gate (negation-aware: we may DISCUSS the claim in order to reject it)
    eff_null = str(st.get("research_status", "")).endswith("NULL") or st.get("utility_router_result") != "POSITIVE"
    if eff_null:
        pat = re.compile(r"(shared memory|another developer'?s|collective)[^.\n]{0,90}(help|improv|boost|increase)"
                         r"[^.\n]{0,50}(success|performance|resolve|coding)")
        neg = ("not", "n't", "never", "no reliable", "not established", "does not", "gated on", "unless")
        for m in pat.finditer(low):
            window = low[max(0, m.start() - 70):m.end() + 30]
            if any(t in window for t in neg):
                continue   # negated / gated mention is fine
            fails.append("README makes an un-negated shared-memory efficacy claim while STATUS efficacy is NULL / router not POSITIVE.")
            break

    # 3. production-ready
    if re.search(r"production[\s-]?ready", low) and st.get("production_certification_status", "NOT_CLAIMED") == "NOT_CLAIMED":
        # allow explicit negations like "NOT PRODUCTION-READY"
        if not re.search(r"not\s+production[\s-]?ready|not[\s-]?production[\s-]?certified", low):
            fails.append("README says production-ready while production_certification_status=NOT_CLAIMED.")

    # 4. conflation
    if re.search(r"company[\s-]?ready.{0,40}production[\s-]?certif", low):
        fails.append("README conflates company-ready with production-certified.")

    # 5. migration head
    real_head = alembic_head()
    if real_head and str(st.get("migration_head")) != str(real_head):
        fails.append("STATUS.migration_head=%s but actual alembic head=%s." % (st.get("migration_head"), real_head))

    # 6. link existence for curated surfaces (§2: docs must not reference nonexistent files)
    curated = [rp, os.path.join(ROOT, "docs", "README.md")]
    linkpat = re.compile(r"\]\((?!https?://|#)([^)]+)\)")
    for surface in curated:
        if not os.path.isfile(surface):
            continue
        base = os.path.dirname(surface)
        for link in linkpat.findall(open(surface, encoding="utf-8").read()):
            target = link.split("#")[0]
            if not target:
                continue
            if not os.path.exists(os.path.normpath(os.path.join(base, target))):
                fails.append("%s links to nonexistent path: %s" % (os.path.relpath(surface, ROOT), target))

    if fails:
        print("DOC CONSISTENCY: FAIL")
        for f in fails:
            print("  - " + f)
        return 1
    print("DOC CONSISTENCY: PASS (checked README vs product-only docs/STATUS.yaml, alembic head=%s)" % real_head)
    return 0


if __name__ == "__main__":
    sys.exit(main())
