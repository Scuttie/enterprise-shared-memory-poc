"""R22-P0.9.2 §4 — DRY-RUN unit tests for the pure Ruff SELECTOR-level helpers (NO docker, NO network, NO model).

Exercises list-membership (exact + normalized), per-selector status parsing (ok / FAILED / ignored / absent),
FAIL_TO_PASS parsing (JSON + Python-repr), agreement, and classify() (R2 / R5 / R6 / MIXED) on SYNTHETIC
`cargo test` strings — so the discrimination logic is verified without executing the gated upstream image. Also
asserts the module IMPORTS credential-free and that docker execution is APPROVAL-GATED."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# credential-free import must succeed with no docker/network
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "r22_p092_ruff_selector", os.path.join(ROOT, "scripts", "r22_p092_ruff_selector.py"))
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


# ---- synthetic fixtures ------------------------------------------------------
# A synthetic MERGED `cargo test -- --list` capture (Running headers -> package attribution).
LIST_MERGED = """
   Compiling ruff v0.9.3 (/testbed/crates/ruff)
    Finished `test` profile [unoptimized + debuginfo] target(s)
     Running unittests src/lib.rs (target/debug/deps/ruff-b9b823e9e09c449b)
rules::pyupgrade::tests::alpha: test
rules::pyupgrade::tests::beta: test
     Running unittests src/lib.rs (target/debug/deps/red_knot_python_semantic-614b42bd993e00c0)
rules::refurb::tests::gamma: test
3 tests, 0 benchmarks
"""

# Per-selector `cargo test "<sel>" -- --exact` outputs (one matching binary + many filtered binaries).
SEL_OK = """
running 1 test
test rules::pyupgrade::tests::alpha ... ok

test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 3210 filtered out
test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 88 filtered out
"""
SEL_FAILED = """
running 1 test
test rules::pyupgrade::tests::beta ... FAILED

failures:
    rules::pyupgrade::tests::beta

test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 3210 filtered out
"""
SEL_IGNORED = """
running 1 test
test rules::refurb::tests::gamma ... ignored

test result: ok. 0 passed; 0 failed; 1 ignored; 0 measured; 3210 filtered out
"""
SEL_ABSENT = """
running 0 tests

test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 3211 filtered out
"""


# ---- FAIL_TO_PASS parsing ----------------------------------------------------
def test_parse_f2p_python_repr_string():
    # single-quoted Python repr: json.loads fails, ast.literal_eval fallback succeeds
    assert S.parse_f2p("['rules::m::tests::a', 'rules::m::tests::b']") == \
        ["rules::m::tests::a", "rules::m::tests::b"]


def test_parse_f2p_json_and_list_and_scalar_and_none():
    assert S.parse_f2p('["a::b", "c::d"]') == ["a::b", "c::d"]
    assert S.parse_f2p(["x::y"]) == ["x::y"]
    assert S.parse_f2p("solo::t") == ["solo::t"]
    assert S.parse_f2p(None) == []


# ---- list membership + package attribution -----------------------------------
def test_parse_list_with_packages_attributes_pkg():
    names, pkg = S.parse_list_with_packages(LIST_MERGED)
    assert names == [
        "rules::pyupgrade::tests::alpha",
        "rules::pyupgrade::tests::beta",
        "rules::refurb::tests::gamma",
    ]
    assert pkg["rules::pyupgrade::tests::alpha"] == "ruff"
    assert pkg["rules::pyupgrade::tests::beta"] == "ruff"
    assert pkg["rules::refurb::tests::gamma"] == "red_knot_python_semantic"


def test_list_membership_exact_normalized_none():
    collected = S.parse_list_output(LIST_MERGED)
    # exact
    m = S.list_membership("rules::pyupgrade::tests::alpha", collected)
    assert m["listed_exact"] is True and m["listed_normalized"] is True
    assert m["matched_name"] == "rules::pyupgrade::tests::alpha"
    # normalized (::-suffix of a collected name / same leaf)
    m = S.list_membership("pyupgrade::tests::beta", collected)
    assert m["listed_exact"] is False and m["listed_normalized"] is True
    assert m["matched_name"] == "rules::pyupgrade::tests::beta"
    # none
    m = S.list_membership("rules::pyupgrade::tests::zzz_missing", collected)
    assert m["listed_exact"] is False and m["listed_normalized"] is False
    assert m["matched_name"] is None


# ---- per-selector status parsing --------------------------------------------
def test_parse_selector_status_ok():
    st = S.parse_selector_status(SEL_OK)
    assert st["status"] == "pass"
    assert st["passed"] == 1 and st["failed"] == 0 and st["ran"] == 1


def test_parse_selector_status_failed():
    st = S.parse_selector_status(SEL_FAILED)
    assert st["status"] == "fail"
    assert st["failed"] == 1


def test_parse_selector_status_ignored():
    st = S.parse_selector_status(SEL_IGNORED)
    assert st["status"] == "ignored"
    assert st["ignored"] == 1


def test_parse_selector_status_absent():
    st = S.parse_selector_status(SEL_ABSENT)
    assert st["status"] == "absent"
    assert st["ran"] == 0 and st["passed"] == 0 and st["failed"] == 0


# ---- agreement ---------------------------------------------------------------
def test_agreement_direct_vs_official_not_passed():
    assert S.agreement("pass", "not_passed") == "DISAGREE"     # direct pass contradicts official
    assert S.agreement("fail", "not_passed") == "AGREE"        # direct fail confirms official
    assert S.agreement("ignored", "not_passed") == "AGREE"
    assert S.agreement("absent", "not_passed") == "AGREE"


def test_agreement_direct_vs_official_passed_control():
    assert S.agreement("pass", "passed") == "AGREE"            # control: direct reproduces official pass
    assert S.agreement("fail", "passed") == "DISAGREE"


def test_official_status_for_from_campaign():
    assert S.official_status_for({"gold_f2p_complete": False}) == "not_passed"
    assert S.official_status_for({"gold_f2p_complete": True}) == "passed"
    assert S.official_status_for({}) == "not_passed"


# ---- classify (pure, per-selector) ------------------------------------------
def _row(status, agreement, exact=True, normalized=True):
    return {"status": status, "agreement": agreement,
            "listed_exact": exact, "listed_normalized": normalized}


def test_classify_R2_selector_absent():
    # >=1 intended selector ABSENT (not collected) -> case/selector bug, even with a passing sibling
    rows = [_row("absent", "AGREE", exact=False, normalized=False),
            _row("pass", "DISAGREE")]
    cls, reason, counts = S.classify(rows)
    assert cls == "R2_CASE_SELECTOR_BUG"
    assert counts["absent"] == 1 and reason


def test_classify_R5_present_pass_but_official_not_passed():
    rows = [_row("pass", "DISAGREE"), _row("pass", "DISAGREE")]
    cls, reason, counts = S.classify(rows)
    assert cls == "R5_UPSTREAM_PARSER_BUG"
    assert counts["pass"] == 2 and counts["disagree"] == 2 and counts["fail"] == 0


def test_classify_R6_present_fail_under_gold():
    rows = [_row("fail", "AGREE"), _row("fail", "AGREE")]
    cls, reason, counts = S.classify(rows)
    assert cls == "R6_UPSTREAM_GOLD_INVALID"
    assert counts["fail"] == 2 and counts["agree"] == 2


def test_classify_MIXED_some_pass_some_fail():
    rows = [_row("pass", "DISAGREE"), _row("fail", "AGREE")]
    cls, reason, counts = S.classify(rows)
    assert cls == "MIXED"
    assert counts["pass"] == 1 and counts["fail"] == 1


def test_classify_R8_unknown_all_ignored():
    rows = [_row("ignored", "AGREE"), _row("ignored", "AGREE")]
    cls, _, counts = S.classify(rows)
    assert cls == "R8_UNKNOWN"
    assert counts["ignored"] == 2


# ---- end-to-end pure composition (no docker) --------------------------------
def test_pure_pipeline_composes_membership_status_agreement_classify():
    collected = S.parse_list_output(LIST_MERGED)
    fixtures = {"rules::pyupgrade::tests::alpha": SEL_OK,
                "rules::pyupgrade::tests::beta": SEL_FAILED}
    rows = []
    for sel, out in fixtures.items():
        mem = S.list_membership(sel, collected)
        status = S.parse_selector_status(out)["status"]
        rows.append({"selector": sel, "status": status,
                     "listed_exact": mem["listed_exact"], "listed_normalized": mem["listed_normalized"],
                     "agreement": S.agreement(status, "not_passed")})
    cls, _, counts = S.classify(rows)
    assert cls == "MIXED"                      # alpha passes (DISAGREE) + beta fails (AGREE)
    assert counts["disagree"] == 1 and counts["agree"] == 1


# ---- gate --------------------------------------------------------------------
def test_execution_is_approval_gated(monkeypatch):
    monkeypatch.delenv("R22_SCB_UPSTREAM_EXEC_APPROVED", raising=False)
    with pytest.raises(S.SG.UpstreamExecutionNotApproved):
        S.require_approval()


def test_require_approval_passes_when_set(monkeypatch):
    monkeypatch.setenv("R22_SCB_UPSTREAM_EXEC_APPROVED", "1")
    S.require_approval()   # must not raise
