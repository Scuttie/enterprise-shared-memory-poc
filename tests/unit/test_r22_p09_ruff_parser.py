"""R22-P0.9.1 §3 — DRY-RUN unit tests for the pure Ruff-forensic helpers (NO docker, NO network, NO model).

Exercises the parse/count/map/classify logic on SYNTHETIC `cargo test` + `cargo test -- --list` strings so the
diagnostic's discrimination logic is verified without executing the gated upstream image. Also asserts the module
IMPORTS without docker and that the docker execution is APPROVAL-GATED."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# credential-free import must succeed with no docker/network
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "r22_p09_ruff_forensics", os.path.join(ROOT, "scripts", "r22_p09_ruff_forensics.py"))
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)


# ---- synthetic fixtures ------------------------------------------------------
# A synthetic `cargo test` stdout: 2 running lines (ok/FAILED) + an ignored + a summary line.
CARGO_STDOUT = """
   Compiling ruff_linter v0.0.0
    Finished test [unoptimized] target(s)
     Running unittests src/lib.rs

running 3 tests
test rules::flake8_bugbear::tests::mutable_argument_default ... ok
test rules::flake8_bugbear::tests::function_call_in_default ... FAILED
test rules::pyflakes::tests::unused_import ... ignored

test result: FAILED. 1 passed; 1 failed; 1 ignored; 0 measured; 0 filtered out
"""

# A synthetic `cargo test -- --list` output listing collected runtime names.
LIST_STDOUT = """
rules::flake8_bugbear::tests::mutable_argument_default: test
rules::flake8_bugbear::tests::function_call_in_default: test
rules::pyflakes::tests::unused_import: test
2 tests, 0 benchmarks
"""


# ---- extractor ---------------------------------------------------------------
def test_extract_raw_counts_counts_run_lines_and_summary():
    raw = F.extract_raw_counts(CARGO_STDOUT)
    assert raw["raw_collected_count"] == 3                      # three `test ... <status>` run lines
    assert raw["by_status"]["ok"] == 1
    assert raw["by_status"]["FAILED"] == 1
    assert raw["by_status"]["ignored"] == 1
    assert raw["summary_total"] == {"passed": 1, "failed": 1, "ignored": 1}


def test_extract_raw_counts_sums_multiple_binaries():
    two = (CARGO_STDOUT
           + "\ntest result: ok. 4 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n")
    raw = F.extract_raw_counts(two)
    assert raw["summary_total"]["passed"] == 5                  # 1 + 4 summed across binaries
    assert len(raw["summaries"]) == 2


def test_extract_raw_counts_zero_collection():
    raw = F.extract_raw_counts("running 0 tests\n\ntest result: ok. 0 passed; 0 failed; 0 ignored\n")
    assert raw["raw_collected_count"] == 0


# ---- list parser + selector mapping -----------------------------------------
def test_parse_list_output():
    names = F.parse_list_output(LIST_STDOUT)
    assert names == [
        "rules::flake8_bugbear::tests::mutable_argument_default",
        "rules::flake8_bugbear::tests::function_call_in_default",
        "rules::pyflakes::tests::unused_import",
    ]


def test_map_selectors_exact_normalized_none():
    collected = F.parse_list_output(LIST_STDOUT)
    f2p = [
        "rules::flake8_bugbear::tests::mutable_argument_default",   # exact
        "flake8_bugbear::tests::function_call_in_default",          # normalized (::-suffix of a collected name)
        "rules::flake8_bugbear::tests::does_not_exist",            # none
    ]
    m = F.map_selectors(f2p, collected)
    assert m["selectors_total"] == 3
    assert m["selectors_matched"] == 2
    assert m["selectors_absent"] == 1
    kinds = {r["selector"]: r["collected_match_kind"] for r in m["rows"]}
    assert kinds["rules::flake8_bugbear::tests::mutable_argument_default"] == "exact"
    assert kinds["flake8_bugbear::tests::function_call_in_default"] == "normalized"
    assert kinds["rules::flake8_bugbear::tests::does_not_exist"] == "none"
    # expected source/symbol best-effort derivation
    row0 = m["rows"][0]
    assert row0["expected_symbol"] == "mutable_argument_default"
    assert "flake8_bugbear" in row0["expected_source"]


def test_as_list_coerces_json_string_and_scalar():
    assert F.as_list('["a::b", "c::d"]') == ["a::b", "c::d"]
    assert F.as_list("solo::t") == ["solo::t"]
    assert F.as_list(None) == []


# ---- classifier --------------------------------------------------------------
def _base_ev(**over):
    ev = {
        "command_matches_official": True,
        "base_commit_match": True,
        "test_patch_rc": 0,
        "gold_patch_rc": 0,
        "compile_ok": True,
        "no_run_rc": 0,
        "raw_collected_count": 0,
        "parser_output_count": 0,
        "selectors_total": 1,
        "selectors_matched": 1,
        "gold_failed": False,
    }
    ev.update(over)
    return ev


def test_classify_R5_tests_ran_but_parser_matched_zero():
    # tests ran (raw>0) but the parser yielded 0 -> upstream parser bug
    cls, reasons = F.classify_target(_base_ev(raw_collected_count=9, parser_output_count=0))
    assert cls == "R5_UPSTREAM_PARSER_BUG"
    assert reasons


def test_classify_R7_compile_failed_precedes_collection():
    cls, reasons = F.classify_target(_base_ev(compile_ok=False, no_run_rc=101,
                                              raw_collected_count=0, parser_output_count=0))
    assert cls == "R7_TOOLCHAIN_INCOMPATIBILITY"


def test_classify_R3_test_patch_apply_failed():
    cls, _ = F.classify_target(_base_ev(test_patch_rc=1))
    assert cls == "R3_TEST_PATCH_BUG"


def test_classify_R4_base_commit_drift():
    cls, _ = F.classify_target(_base_ev(base_commit_match=False))
    assert cls == "R4_IMAGE_CASE_DRIFT"


def test_classify_R2_selectors_absent():
    # compiled, some tests collected & parsed, but none of the expected selectors are present
    cls, _ = F.classify_target(_base_ev(raw_collected_count=5, parser_output_count=5,
                                        selectors_total=3, selectors_matched=0))
    assert cls == "R2_CASE_SELECTOR_BUG"


def test_classify_R6_gold_invalid():
    cls, _ = F.classify_target(_base_ev(raw_collected_count=5, parser_output_count=5,
                                        selectors_total=1, selectors_matched=1, gold_failed=True))
    assert cls == "R6_UPSTREAM_GOLD_INVALID"


def test_classify_R8_unknown():
    cls, _ = F.classify_target(_base_ev(raw_collected_count=5, parser_output_count=5,
                                        selectors_total=1, selectors_matched=1, gold_failed=False))
    assert cls == "R8_UNKNOWN"


# ---- replicated parser -------------------------------------------------------
def test_replicated_parser_maps_statuses():
    p = F.replicated_parser(CARGO_STDOUT)
    assert p["rules::flake8_bugbear::tests::mutable_argument_default"] == "PASSED"
    assert p["rules::flake8_bugbear::tests::function_call_in_default"] == "FAILED"
    assert p["rules::pyflakes::tests::unused_import"] == "SKIPPED"
    assert len(p) == 3


# ---- gate --------------------------------------------------------------------
def test_execution_is_approval_gated(monkeypatch):
    monkeypatch.delenv("R22_SCB_UPSTREAM_EXEC_APPROVED", raising=False)
    with pytest.raises(F.SG.UpstreamExecutionNotApproved):
        F.require_approval()


def test_require_approval_passes_when_set(monkeypatch):
    monkeypatch.setenv("R22_SCB_UPSTREAM_EXEC_APPROVED", "1")
    F.require_approval()   # must not raise
