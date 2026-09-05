"""OSS v0.3 release-hygiene regression tests (no DB required).

Locks in the three real changes made for the release and the invariants around them:
  * migration-aware workflows call the shared head checker (not a hard-coded revision),
  * no stale `0013.*(head)` guard remains, and the real Alembic script head is a single head,
  * the frozen R14/R15/R18/R19 amendment is path-only (scripts still parse; scratch root is env-driven),
  * no personal Windows absolute path leaks into the tree,
  * the product path scanner's coverage was NOT narrowed, and
  * the detector credential-scan exemption lists exact existing files only.
"""
import ast
import glob
import importlib.util
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WF = os.path.join(ROOT, ".github", "workflows")
# Built from fragments so this test file itself carries no forbidden personal-path literal (keeps the product
# path scanner's coverage of tests/ intact — which test_path_scanner_scope_not_reduced asserts).
PERSONAL = "C:/Users/" + "jewon"
PERSONAL_WIN = "C:\\Users\\" + "jewon"
MIGRATION_AWARE = ["ci-postgres", "ci-qdrant", "ci-qdrant-outage", "ci-mem0", "ci-artifacts", "ci-e2e",
                   "ci-experiment-readiness"]
FROZEN_R = ["r14_relevance_audit", "r15_semantic_retrieval", "r18_multi_memory", "r19_build_arms"]


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _load_release_check():
    spec = importlib.util.spec_from_file_location("release_check", os.path.join(ROOT, "scripts", "release_check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- migration head guard -------------------------------------------------

def test_migration_aware_workflows_call_shared_checker():
    for name in MIGRATION_AWARE:
        src = _read(os.path.join(WF, name + ".yml"))
        assert "scripts/check_migration_head.py" in src, "%s must call the shared head checker" % name


def test_no_stale_0013_head_guard_anywhere():
    # Detect per-line: a stale guard names revision 0013 together with `head` (the YAML source escapes the parens
    # as `\(head\)`, so a naive r"0013.*\(head\)" regex false-negatives — match 0013-near-head instead).
    for path in glob.glob(os.path.join(WF, "*.yml")):
        for i, line in enumerate(_read(path).splitlines(), 1):
            assert not ("0013" in line and "head" in line), \
                "stale 0013 head guard in %s:%d" % (os.path.basename(path), i)


def test_real_alembic_script_head_is_single_0015():
    spec = importlib.util.spec_from_file_location(
        "check_migration_head", os.path.join(ROOT, "scripts", "check_migration_head.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    heads = mod.script_heads()
    assert heads == ["0015"], "expected single script head 0015, got %s" % heads


# ---- frozen R14/R15/R18/R19 path-only amendment ---------------------------

def test_frozen_research_scripts_are_path_only_portable():
    for name in FROZEN_R:
        path = os.path.join(ROOT, "scripts", name + ".py")
        src = _read(path)
        ast.parse(src)  # still valid Python / logic intact
        assert "ESM_SCRATCH" in src, "%s scratch root must be env-overridable" % name
        assert PERSONAL not in src, "%s must not hardcode a personal path" % name


# ---- no personal path leak + scanner scope intact -------------------------

def test_no_personal_windows_path_leaks_via_product_scanner():
    rc = _load_release_check()
    # The product scanner walks the whole tree; CLEAN (return 0) proves no personal path leaked.
    assert rc.check_secrets() == 0


def test_path_scanner_scope_not_reduced():
    rc = _load_release_check()
    # Personal-path tokens still forbidden, and scripts/ is still in scan scope (not skipped).
    assert PERSONAL in rc.FORBIDDEN_PATH and PERSONAL_WIN in rc.FORBIDDEN_PATH
    assert "scripts" not in rc.SKIP_DIR


# ---- detector exemption is exact-files only -------------------------------

def test_detector_exemption_lists_exact_existing_files_only():
    rc = _load_release_check()
    assert "scripts/oss_release_acceptance.py" in rc.EXEMPT
    for entry in rc.EXEMPT:
        assert not any(ch in entry for ch in "*?[]"), "exemption %s must be an exact path, not a glob" % entry
        assert os.path.isfile(os.path.join(ROOT, entry)), "exempted file %s does not exist" % entry
