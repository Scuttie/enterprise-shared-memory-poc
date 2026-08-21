#!/usr/bin/env python3
"""Render docs/STATUS.yaml into the canonical README status block (and stdout).

Writes the block between the markers:
  <!-- STATUS:BEGIN --> ... <!-- STATUS:END -->
in README.md if present; otherwise prints to stdout. Idempotent. Pure-stdlib fallback parser so it runs in
minimal CI. Run in CI (ci-docs) with --check to fail if the rendered block is out of date.
"""
from __future__ import annotations
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BEGIN, END = "<!-- STATUS:BEGIN -->", "<!-- STATUS:END -->"


def load():
    p = os.path.join(ROOT, "docs", "STATUS.yaml")
    txt = open(p, encoding="utf-8").read()
    try:
        import yaml
        return yaml.safe_load(txt)
    except Exception:
        d = {}
        for k in ("project_version", "service_status", "research_status", "company_handoff_status",
                  "production_certification_status", "migration_head", "workflow_count", "utility_router_result"):
            m = re.search(r"^%s:\s*\"?([^\"#\n]+?)\"?\s*(?:#.*)?$" % k, txt, re.M)
            if m:
                d[k] = m.group(1).strip()
        return d


def block(st) -> str:
    rows = [
        ("Version", st.get("project_version")),
        ("Service plumbing", st.get("service_status")),
        ("Research efficacy", st.get("research_status")),
        ("Utility router (held-out)", st.get("utility_router_result")),
        ("Company handoff", st.get("company_handoff_status")),
        ("Production certification", st.get("production_certification_status")),
        ("Migration head", st.get("migration_head")),
    ]
    lines = [BEGIN,
             "| Dimension | Status |",
             "| --- | --- |"]
    for k, v in rows:
        lines.append("| %s | `%s` |" % (k, v))
    lines.append("")
    handoff = str(st.get("company_handoff_status", "IN_PROGRESS"))
    if handoff == "READY":
        banner = "**COMPANY-HANDOFF-READY — NOT YET COMPANY-STAGING-CERTIFIED.**"
    else:
        banner = "**COMPANY HANDOFF IN PROGRESS — not yet COMPANY-HANDOFF-READY, not COMPANY-STAGING-CERTIFIED.**"
    lines.append("> " + banner + " Service correctness, research efficacy, and staging certification are tracked "
                 "separately; see [`docs/STATUS.yaml`](docs/STATUS.yaml) (single source of truth) and "
                 "[`docs/EVIDENCE_AND_LIMITATIONS.md`](docs/EVIDENCE_AND_LIMITATIONS.md).")
    lines.append(END)
    return "\n".join(lines)


def main() -> int:
    st = load()
    rendered = block(st)
    rp = os.path.join(ROOT, "README.md")
    check = "--check" in sys.argv
    if not os.path.isfile(rp):
        print(rendered)
        return 0
    txt = open(rp, encoding="utf-8").read()
    if BEGIN in txt and END in txt:
        new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), rendered, txt, flags=re.S)
    else:
        new = rendered + "\n\n" + txt
    if check:
        if new != txt:
            print("render_project_status: README status block OUT OF DATE (run without --check).")
            return 1
        print("render_project_status: README status block up to date.")
        return 0
    if new != txt:
        open(rp, "w", encoding="utf-8").write(new)
        print("README status block updated.")
    else:
        print("README status block already current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
