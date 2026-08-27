"""R22 §2/§4 — repository tool surface + patch extraction + a LOCAL grader fixture for the offline harness E2E.

Tool design mirrors scripts/r7_repo_agent.py (list_dir/read_file/search/replace_lines/create_file/submit); the
REAL paid path grades with the official swebench Docker harness (scripts/r22_grader_run.py), while the offline E2E
grades a tiny local fixture repo here (no Docker, no credential). The agent never sees the target gold patch/tests.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile


def _safe(root, path):
    p = os.path.normpath(os.path.join(root, path))
    if not p.startswith(os.path.normpath(root)):
        raise ValueError("path escapes repo: %s" % path)
    return p


class RepoWorkspace:
    """A checked-out working copy with the R7-style tool surface. `EDITED` tracks whether a real edit happened."""

    def __init__(self, root: str):
        self.root = root
        self.edited = False

    def list_dir(self, path="."):
        d = _safe(self.root, path)
        return "\n".join(sorted(os.listdir(d))) if os.path.isdir(d) else "not a dir"

    def read_file(self, path, start_line=1, end_line=None):
        p = _safe(self.root, path)
        if not os.path.isfile(p):
            return "no such file"
        lines = open(p, encoding="utf-8", errors="ignore").read().splitlines()
        end_line = end_line or len(lines)
        return "\n".join("%d\t%s" % (i, lines[i - 1]) for i in range(start_line, min(end_line, len(lines)) + 1))

    def search(self, pattern, path="."):
        out = []
        base = _safe(self.root, path)
        for dp, _, fns in os.walk(base):
            if ".git" in dp:
                continue
            for fn in fns:
                fp = os.path.join(dp, fn)
                try:
                    for i, ln in enumerate(open(fp, encoding="utf-8", errors="ignore").read().splitlines(), 1):
                        if re.search(pattern, ln):
                            out.append("%s:%d:%s" % (os.path.relpath(fp, self.root), i, ln))
                except OSError:
                    pass
        return "\n".join(out[:50]) or "no matches"

    def replace_lines(self, path, start_line, end_line, new_content):
        p = _safe(self.root, path)
        lines = open(p, encoding="utf-8").read().splitlines()
        lines[start_line - 1:end_line] = new_content.splitlines()
        open(p, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
        self.edited = True
        return "replaced %s:%d-%d" % (path, start_line, end_line)

    def create_file(self, path, content):
        p = _safe(self.root, path)
        os.makedirs(os.path.dirname(p) or self.root, exist_ok=True)
        open(p, "w", encoding="utf-8", newline="\n").write(content)
        self.edited = True
        return "created %s" % path

    def git_diff(self):
        try:
            subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True)
            r = subprocess.run(["git", "diff", "--cached"], cwd=self.root, capture_output=True, text=True)
            return r.stdout
        except Exception:  # noqa: BLE001
            return ""


TOOL_NAMES = ["list_dir", "read_file", "search", "replace_lines", "create_file", "submit"]


def dispatch(ws: RepoWorkspace, name: str, args: dict) -> str:
    if name == "submit":
        return "submitted"
    fn = {"list_dir": ws.list_dir, "read_file": ws.read_file, "search": ws.search,
          "replace_lines": ws.replace_lines, "create_file": ws.create_file}.get(name)
    if fn is None:
        return "unknown tool"
    try:
        return str(fn(**args))
    except Exception as ex:  # noqa: BLE001
        return "tool error: %s" % ex


# ---- local grader fixture (offline E2E only) --------------------------------
def make_fixture(root: str) -> dict:
    """A tiny repo with a bug and a test. Returns {path,start_line,end_line,new_content} that fixes it (the FIX;
    the agent's fake provider is scripted from this). git-init so git_diff works."""
    os.makedirs(root, exist_ok=True)
    open(os.path.join(root, "bug.py"), "w", encoding="utf-8", newline="\n").write(
        "def add(a, b):\n    return a - b\n")   # bug: minus
    open(os.path.join(root, "test_bug.py"), "w", encoding="utf-8", newline="\n").write(
        "from bug import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    subprocess.run(["git", "init", "-q"], cwd=root, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
    subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=x", "commit", "-qm", "init"],
                   cwd=root, capture_output=True)
    return {"path": "bug.py", "start_line": 2, "end_line": 2, "new_content": "    return a + b"}


def local_grade(root: str) -> bool:
    """Run the fixture's test in a fresh env; resolved iff FAIL_TO_PASS now passes."""
    r = subprocess.run(["python", "-m", "pytest", "-q", "test_bug.py"], cwd=root, capture_output=True, text=True)
    return r.returncode == 0
