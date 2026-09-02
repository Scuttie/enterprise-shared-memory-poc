from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from trimem_multi_swe_report_semantics import (  # noqa: E402
    FINAL_RESOLVED_PROJECTION,
    MultiSWEReportSemanticsError,
    PUBLIC_SUMMARY_FIELDS,
    REPORT_CHECK_RULES,
    REPORT_VALID_PROJECTION,
    SCHEMA,
    recompute_multi_swe_report_validity,
    report_semantics_truth_table,
    validate_multi_swe_report_semantics,
    validate_public_semantics_summary,
)
import trimem_multi_swe_contract as multi_contract  # noqa: E402


INSTANCE_ID = "vuejs__core-8911"
CANONICAL_ID = "vuejs/core:pr-8911"


def _result(
    *,
    passed: list[str] | None = None,
    failed: list[str] | None = None,
    skipped: list[str] | None = None,
) -> dict[str, object]:
    passed = list(passed or [])
    failed = list(failed or [])
    skipped = list(skipped or [])
    return {
        "passed_count": len(passed),
        "failed_count": len(failed),
        "skipped_count": len(skipped),
        "passed_tests": passed,
        "failed_tests": failed,
        "skipped_tests": skipped,
    }


def _transition(run: str, test: str, fix: str) -> dict[str, str]:
    return {"run": run, "test": test, "fix": fix}


def _source() -> dict[str, object]:
    return {
        "org": "vuejs",
        "repo": "core",
        "number": 8911,
        "run_result": _result(
            passed=["private-stable-a", "private-stable-b"],
            failed=["private-repair-a", "private-repair-b"],
        ),
        "test_patch_result": _result(
            passed=["private-stable-a", "private-stable-b"],
            failed=["private-repair-a", "private-repair-b"],
        ),
        "fix_patch_result": _result(
            passed=[
                "private-stable-a",
                "private-stable-b",
                "private-repair-a",
                "private-repair-b",
            ]
        ),
        "p2p_tests": {
            "private-stable-a": _transition("PASS", "PASS", "PASS"),
            "private-stable-b": _transition("PASS", "PASS", "PASS"),
        },
        "f2p_tests": {
            "private-repair-a": _transition("FAIL", "FAIL", "PASS"),
            "private-repair-b": _transition("FAIL", "FAIL", "PASS"),
        },
        "s2p_tests": {},
        "n2p_tests": {},
    }


def _complete_valid_status() -> dict[str, object]:
    source = _source()
    return {
        "org": "vuejs",
        "repo": "core",
        "number": 8911,
        "valid": True,
        "error_msg": "",
        "run_result": deepcopy(source["run_result"]),
        "test_patch_result": deepcopy(source["test_patch_result"]),
        "fix_patch_result": deepcopy(source["fix_patch_result"]),
        "fixed_tests": deepcopy(source["f2p_tests"]),
        "p2p_tests": deepcopy(source["p2p_tests"]),
        "f2p_tests": deepcopy(source["f2p_tests"]),
        "s2p_tests": {},
        "n2p_tests": {},
    }


def _missing_f2p_status() -> dict[str, object]:
    status = _complete_valid_status()
    status["fix_patch_result"] = _result(
        passed=[
            "private-stable-a",
            "private-stable-b",
            "private-repair-a",
        ],
        failed=["private-repair-b"],
    )
    status["fixed_tests"] = {
        "private-repair-a": _transition("FAIL", "FAIL", "PASS")
    }
    status["f2p_tests"] = deepcopy(status["fixed_tests"])
    return status


def _missing_p2p_status() -> dict[str, object]:
    status = _complete_valid_status()
    status["fix_patch_result"] = _result(
        passed=["private-stable-a", "private-repair-a", "private-repair-b"],
        skipped=["private-stable-b"],
    )
    status["p2p_tests"] = {
        "private-stable-a": _transition("PASS", "PASS", "PASS")
    }
    return status


def _invalid_status() -> dict[str, object]:
    source = _source()
    return {
        "org": "vuejs",
        "repo": "core",
        "number": 8911,
        "valid": False,
        "error_msg": (
            "After applying the fix patch, no test cases transitioned from failed "
            "to passed. A brief summary is as follows: restricted"
        ),
        "run_result": deepcopy(source["run_result"]),
        "test_patch_result": deepcopy(source["test_patch_result"]),
        "fix_patch_result": _result(
            passed=["private-stable-a", "private-stable-b"],
            failed=["private-repair-a", "private-repair-b"],
        ),
        "fixed_tests": {},
        "p2p_tests": {},
        "f2p_tests": {},
        "s2p_tests": {},
        "n2p_tests": {},
    }


def _final_report(resolved: bool) -> dict[str, object]:
    return {
        "total_instances": 1,
        "submitted_instances": 1,
        "completed_instances": 1,
        "incomplete_instances": 0,
        "resolved_instances": int(resolved),
        "unresolved_instances": int(not resolved),
        "empty_patch_instances": 0,
        "error_instances": 0,
        "submitted_ids": [CANONICAL_ID],
        "completed_ids": [CANONICAL_ID],
        "incomplete_ids": [],
        "resolved_ids": [CANONICAL_ID] if resolved else [],
        "unresolved_ids": [] if resolved else [CANONICAL_ID],
        "empty_patch_ids": [],
        "error_ids": [],
    }


def _validate(status: dict[str, object], resolved: bool):
    return validate_multi_swe_report_semantics(
        instance_id=INSTANCE_ID,
        source_row=_source(),
        status=status,
        final_report=_final_report(resolved),
    )


def test_a_valid_complete_final_resolved_is_accepted() -> None:
    result = _validate(_complete_valid_status(), True)

    assert result.report_valid_observed is True
    assert result.report_valid_recomputed is True
    assert result.report_valid_match is True
    assert result.expected_coverage_complete is True
    assert result.missing_expected_transition_count == 0
    assert result.computed_resolved is True
    assert result.official_final_report_resolved is True
    assert result.final_report_match is True


def test_b_valid_missing_f2p_final_unresolved_is_accepted() -> None:
    result = _validate(_missing_f2p_status(), False)

    assert result.report_valid_observed is True
    assert result.report_valid_recomputed is True
    assert result.expected_f2p_count == 2
    assert result.observed_expected_f2p_count == 1
    assert result.missing_expected_transition_count == 1
    assert result.expected_coverage_complete is False
    assert result.computed_resolved is False
    assert result.official_final_report_resolved is False


def test_c_valid_missing_p2p_final_unresolved_is_accepted() -> None:
    result = _validate(_missing_p2p_status(), False)

    assert result.expected_p2p_count == 2
    assert result.observed_expected_p2p_count == 1
    assert result.missing_expected_transition_count == 1
    assert result.computed_resolved is False


def test_n2p_domain_difference_is_valid_and_missing_candidate_key_is_unresolved() -> None:
    source = _source()
    source["fix_patch_result"] = _result(
        passed=[
            "private-stable-a",
            "private-stable-b",
            "private-repair-a",
            "private-repair-b",
            "private-new-a",
        ]
    )
    source["n2p_tests"] = {
        "private-new-a": _transition("NONE", "NONE", "PASS")
    }
    complete = _complete_valid_status()
    complete["fix_patch_result"] = deepcopy(source["fix_patch_result"])
    complete["n2p_tests"] = deepcopy(source["n2p_tests"])
    complete["fixed_tests"] = {
        **deepcopy(complete["fixed_tests"]),
        **deepcopy(source["n2p_tests"]),
    }

    accepted = validate_multi_swe_report_semantics(
        instance_id=INSTANCE_ID,
        source_row=source,
        status=complete,
        final_report=_final_report(True),
    )
    assert accepted.expected_n2p_count == 1
    assert accepted.observed_expected_n2p_count == 1
    assert accepted.computed_resolved is True

    incomplete = deepcopy(complete)
    incomplete["fix_patch_result"] = _result(
        passed=[
            "private-stable-a",
            "private-stable-b",
            "private-repair-a",
            "private-repair-b",
        ]
    )
    del incomplete["fixed_tests"]["private-new-a"]
    incomplete["n2p_tests"] = {}
    accepted_incomplete = validate_multi_swe_report_semantics(
        instance_id=INSTANCE_ID,
        source_row=source,
        status=incomplete,
        final_report=_final_report(False),
    )
    assert accepted_incomplete.report_valid_recomputed is True
    assert accepted_incomplete.expected_n2p_count == 1
    assert accepted_incomplete.observed_expected_n2p_count == 0
    assert accepted_incomplete.missing_expected_transition_count == 1
    assert accepted_incomplete.computed_resolved is False


def test_d_recomputed_invalid_and_final_unresolved_is_accepted() -> None:
    result = _validate(_invalid_status(), False)

    assert result.report_valid_observed is False
    assert result.report_valid_recomputed is False
    assert result.report_invalidity_reason == "NO_NON_PASS_TO_PASS_TRANSITION"
    assert result.computed_resolved is False


@pytest.mark.parametrize(
    ("status_factory", "final_resolved"),
    [
        (_complete_valid_status, False),
        (_invalid_status, True),
        (_missing_f2p_status, True),
    ],
    ids=[
        "e-valid-complete-final-unresolved",
        "f-invalid-final-resolved",
        "g-valid-incomplete-final-resolved",
    ],
)
def test_e_f_g_final_report_mismatch_is_rejected(
    status_factory, final_resolved: bool
) -> None:
    with pytest.raises(MultiSWEReportSemanticsError) as raised:
        _validate(status_factory(), final_resolved)

    assert raised.value.code == "FINAL_REPORT_SEMANTICS_MISMATCH"


def test_h_observed_valid_differs_from_recomputed_is_rejected() -> None:
    status = _complete_valid_status()
    status["valid"] = False
    status["error_msg"] = (
        "After applying the fix patch, no test cases transitioned from failed "
        "to passed."
    )

    with pytest.raises(MultiSWEReportSemanticsError) as raised:
        _validate(status, True)

    assert raised.value.code == "REPORT_VALID_MISMATCH"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda row: row["run_result"].update(
                passed_count=3,
                passed_tests=[
                    "private-stable-a",
                    "private-stable-b",
                    "private-stable-b",
                ],
            ),
            "DUPLICATE_TEST_ID",
        ),
        (
            lambda row: row["run_result"].update(
                failed_count=3,
                failed_tests=[
                    "private-repair-a",
                    "private-repair-b",
                    "private-stable-a",
                ],
            ),
            "TEST_RESULT_CLASSIFICATION_OVERLAP",
        ),
        (
            lambda row: row["run_result"].update(passed_count=99),
            "TEST_RESULT_COUNT_MISMATCH",
        ),
        (lambda row: row.update(valid=1), "NON_BOOLEAN_REPORT_VALID"),
    ],
    ids=["duplicate", "overlap", "count", "non-boolean-valid"],
)
def test_i_malformed_test_result_or_status_is_rejected(mutation, code: str) -> None:
    status = _complete_valid_status()
    mutation(status)

    with pytest.raises(MultiSWEReportSemanticsError) as raised:
        _validate(status, True)

    assert raised.value.code == code


def test_raw_duplicate_is_rejected_even_when_count_matches_deduplicated_set() -> None:
    status = _complete_valid_status()
    status["run_result"]["passed_count"] = 2
    status["run_result"]["passed_tests"] = [
        "private-stable-a",
        "private-stable-b",
        "private-stable-b",
    ]

    with pytest.raises(MultiSWEReportSemanticsError) as raised:
        _validate(status, True)

    assert raised.value.code == "DUPLICATE_TEST_ID"


@pytest.mark.parametrize("field", ["error_msg", "fix_patch_result"])
def test_i_missing_status_field_is_rejected(field: str) -> None:
    status = _complete_valid_status()
    status.pop(field)

    with pytest.raises(MultiSWEReportSemanticsError) as raised:
        _validate(status, True)

    assert raised.value.code == "STATUS_FIELD_SET_DRIFT"


def test_i_extra_status_field_is_rejected() -> None:
    status = _complete_valid_status()
    status["unexpected"] = "not pinned"

    with pytest.raises(MultiSWEReportSemanticsError) as raised:
        _validate(status, True)

    assert raised.value.code == "STATUS_FIELD_SET_DRIFT"


def test_o_gold_and_noop_can_both_be_valid_with_different_final_outcomes() -> None:
    gold = _validate(_complete_valid_status(), True)
    noop = _validate(_missing_f2p_status(), False)

    assert gold.report_valid_recomputed is noop.report_valid_recomputed is True
    assert gold.official_final_report_resolved is True
    assert noop.official_final_report_resolved is False
    assert gold.expected_coverage_complete is True
    assert noop.expected_coverage_complete is False


def test_public_summary_contains_no_raw_test_names() -> None:
    summary = _validate(_missing_f2p_status(), False).to_public_dict()
    encoded = json.dumps(summary, sort_keys=True)

    assert summary["schema"] == SCHEMA
    assert set(summary) == PUBLIC_SUMMARY_FIELDS
    assert "private-" not in encoded
    assert len(summary["expected_transition_domain_sha256"]) == 64
    assert len(summary["observed_expected_transition_domain_sha256"]) == 64
    assert validate_public_semantics_summary(summary) == summary


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("missing_expected_transition_count", 0, "PUBLIC_SUMMARY_COUNT_INCONSISTENT"),
        ("computed_resolved", True, "PUBLIC_SUMMARY_FINAL_MISMATCH"),
        ("report_valid_match", False, "PUBLIC_SUMMARY_VALIDITY_MISMATCH"),
        ("expected_transition_domain_sha256", "bad", "PUBLIC_SUMMARY_DIGEST_INVALID"),
    ],
)
def test_public_summary_validator_fails_closed(field: str, value: object, code: str) -> None:
    summary = _validate(_missing_f2p_status(), False).to_public_dict()
    summary[field] = value

    with pytest.raises(MultiSWEReportSemanticsError) as raised:
        validate_public_semantics_summary(summary)

    assert raised.value.code == code


@pytest.mark.parametrize("complete", [False, True])
def test_public_summary_binds_coverage_to_domain_digests(complete: bool) -> None:
    summary = _validate(
        _complete_valid_status() if complete else _missing_f2p_status(),
        complete,
    ).to_public_dict()
    if complete:
        summary["observed_expected_transition_domain_sha256"] = "0" * 64
    else:
        summary["observed_expected_transition_domain_sha256"] = summary[
            "expected_transition_domain_sha256"
        ]

    with pytest.raises(MultiSWEReportSemanticsError) as raised:
        validate_public_semantics_summary(summary)

    assert raised.value.code == "PUBLIC_SUMMARY_DOMAIN_DIGEST_INCONSISTENT"


def test_report_check_four_rules_are_recomputed_in_pinned_order() -> None:
    no_fix = recompute_multi_swe_report_validity(
        run_result=_result(),
        test_patch_result=_result(),
        fix_patch_result=_result(),
    )
    regression = recompute_multi_swe_report_validity(
        run_result=_result(passed=["x"]),
        test_patch_result=_result(passed=["x"], failed=["repair"]),
        fix_patch_result=_result(failed=["x"], passed=["repair"]),
    )
    no_fix_something = recompute_multi_swe_report_validity(
        run_result=_result(passed=["x"]),
        test_patch_result=_result(passed=["x"]),
        fix_patch_result=_result(passed=["x"]),
    )
    anomaly = recompute_multi_swe_report_validity(
        run_result=_result(passed=["anomaly"], failed=["repair"]),
        test_patch_result=_result(failed=["repair"]),
        fix_patch_result=_result(passed=["repair"], failed=["anomaly"]),
    )
    valid = recompute_multi_swe_report_validity(
        run_result=_result(failed=["repair"]),
        test_patch_result=_result(failed=["repair"]),
        fix_patch_result=_result(passed=["repair"]),
    )

    assert no_fix.report_invalidity_reason == "NO_FIX_PATCH_TESTS"
    assert regression.report_invalidity_reason == "PASS_TO_FAIL_REGRESSION"
    assert no_fix_something.report_invalidity_reason == (
        "NO_NON_PASS_TO_PASS_TRANSITION"
    )
    assert anomaly.report_invalidity_reason == (
        "ANOMALOUS_NONE_OR_SKIP_TO_FAIL_AFTER_RUN_PASS"
    )
    assert valid.report_valid_recomputed is True
    assert valid.report_invalidity_reason == "NONE"


def test_final_report_rejects_unknown_duplicate_and_invalid_identity() -> None:
    unknown = _final_report(True)
    unknown["submitted_ids"] = ["unknown/repo:pr-1"]
    with pytest.raises(MultiSWEReportSemanticsError) as raised:
        validate_multi_swe_report_semantics(
            instance_id=INSTANCE_ID,
            source_row=_source(),
            status=_complete_valid_status(),
            final_report=unknown,
        )
    assert raised.value.code == "UNKNOWN_FINAL_REPORT_ID"

    duplicate = _final_report(True)
    duplicate["submitted_instances"] = 2
    duplicate["submitted_ids"] = [CANONICAL_ID, CANONICAL_ID]
    with pytest.raises(MultiSWEReportSemanticsError) as raised:
        validate_multi_swe_report_semantics(
            instance_id=INSTANCE_ID,
            source_row=_source(),
            status=_complete_valid_status(),
            final_report=duplicate,
        )
    assert raised.value.code == "DUPLICATE_FINAL_REPORT_ID"

    with pytest.raises(MultiSWEReportSemanticsError) as raised:
        validate_multi_swe_report_semantics(
            instance_id="vuejs/core#8911",
            source_row=_source(),
            status=_complete_valid_status(),
            final_report=_final_report(True),
        )
    assert raised.value.code == "INVALID_IDENTITY"

    status = _complete_valid_status()
    status["number"] = True
    with pytest.raises(MultiSWEReportSemanticsError) as raised:
        _validate(status, True)
    assert raised.value.code == "IDENTITY_MISMATCH"


def test_strict_json_rejects_duplicate_object_keys() -> None:
    source_json = json.dumps(_source(), sort_keys=True)
    status_json = json.dumps(_complete_valid_status(), sort_keys=True)
    duplicate_status = status_json.replace(
        '"valid": true', '"valid": true, "valid": true', 1
    )

    with pytest.raises(MultiSWEReportSemanticsError) as raised:
        validate_multi_swe_report_semantics(
            instance_id=INSTANCE_ID,
            source_row=source_json,
            status=duplicate_status,
            final_report=json.dumps(_final_report(True), sort_keys=True),
        )

    assert raised.value.code == "DUPLICATE_JSON_KEY"


@pytest.mark.parametrize(
    "source",
    [
        """
class PullRequestBase:
    def id(self):
        return f"{self.org}/{self.repo}:pr-{self.number}"
""",
        """
class PullRequestBase:
    @property
    def id(self):
        return f"{self.org}__{self.repo}-{self.number}"
""",
    ],
    ids=["property-removed", "identity-format-drift"],
)
def test_pinned_final_report_identity_ast_binding_rejects_drift(
    source: str,
) -> None:
    canonical = ast.parse(
        """
class PullRequestBase:
    @property
    def id(self):
        return f"{self.org}/{self.repo}:pr-{self.number}"
"""
    )
    multi_contract._verify_pull_request_identity(canonical)

    with pytest.raises(multi_contract.ContractError):
        multi_contract._verify_pull_request_identity(ast.parse(source))


def test_semantics_lock_is_self_sealed_and_validates_without_upstream_checkout() -> None:
    path = ROOT / "artifacts/trimem_v1/multi_swe_report_semantics_lock.json"
    lock = json.loads(path.read_bytes())
    body = dict(lock)
    self_hash = body.pop("lock_sha256")

    assert self_hash == hashlib.sha256(
        json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    projection = lock["contract_projection"]
    assert projection["REPORT_VALID"] == REPORT_VALID_PROJECTION
    assert projection["FINAL_RESOLVED"] == FINAL_RESOLVED_PROJECTION
    assert projection["final_report_target_identity"] == {
        "format": "{org}/{repo}:pr-{number}",
        "upstream_symbol": "PullRequestBase.id",
    }
    assert projection["test_result_strictness"] == {
        "trimem_fail_closed_raw_input": {
            "count_matches_raw_list_length": True,
            "duplicate_ids_rejected_before_set_construction": True,
            "pass_fail_skip_disjoint": True,
        },
        "upstream_materialized_test_result": {
            "count_matches_materialized_set_size": True,
            "pass_fail_skip_sets_disjoint": True,
            "raw_json_duplicates_unconditionally_rejected": False,
            "required_collection_type": "set",
        },
    }
    assert [
        row["accept"]
        for row in projection["stage_a_local_transition_predicate"]["ordered_rules"]
    ] == list(REPORT_CHECK_RULES)
    assert lock["truth_table"] == report_semantics_truth_table()
    evaluation_lock = json.loads(
        (ROOT / "artifacts/trimem_v1/multi_swe_evaluation_contract_lock.json").read_bytes()
    )
    assert lock["revision_tree_oid"] == evaluation_lock["commit_tree_oid"]
    assert multi_contract.validate_report_semantics_lock() == {
        "contract_projection_sha256": lock["contract_projection_sha256"],
        "lock_sha256": self_hash,
        "module_sha256": lock["implementation"]["sha256"],
        "schema": "trimem/multi-swe-report-semantics-lock-validation/1.0",
        "source_blobs": 5,
        "status": "PASS",
    }


def test_semantics_lock_pins_exact_semantic_upstream_git_blobs() -> None:
    semantics_lock = json.loads(
        (
            ROOT / "artifacts/trimem_v1/multi_swe_report_semantics_lock.json"
        ).read_bytes()
    )
    evaluation_lock = json.loads(
        (
            ROOT / "artifacts/trimem_v1/multi_swe_evaluation_contract_lock.json"
        ).read_bytes()
    )
    expected = {
        "multi_swe_bench/harness/report.py": {
            "bytes": 12942,
            "git_blob_oid": "a0b23ab1bf3c2407e15338fd0e644c0138fd3d90",
            "git_mode": "100644",
            "line_count": 347,
            "sha256": "5a025fd496d42c4b7377fc0702d64c6d0e356b117eaf2face47e73a52c29902f",
        },
        "multi_swe_bench/harness/gen_report.py": {
            "bytes": 21331,
            "git_blob_oid": "251e8b01059a18a9af5ae176c696eb4be8950ae4",
            "git_mode": "100644",
            "line_count": 589,
            "sha256": "02ebc8a5414898d12f4f5a9ba0c11a8f57c9f34a0bdc02c2311afac9f654847d",
        },
        "multi_swe_bench/harness/pull_request.py": {
            "bytes": 6015,
            "git_blob_oid": "0c2c99a4602bc6dc127cc0bb3ecaff56a6550d17",
            "git_mode": "100644",
            "line_count": 211,
            "sha256": "32b49f48b39124f67727f408898bd96cce91c0a362faa716ac858dcb0b0b47c7",
        },
        "multi_swe_bench/harness/dataset.py": {
            "bytes": 2833,
            "git_blob_oid": "19aeb4370fcfdaeccef99b3a47d06c5a572d468c",
            "git_mode": "100644",
            "line_count": 79,
            "sha256": "dd49f55baf63b60fff309b6a5b2a1826697e2b85ad1a9bccff18321dcdc200fc",
        },
        "multi_swe_bench/harness/test_result.py": {
            "bytes": 5164,
            "git_blob_oid": "bbdd5dc729582a1d06c79f416058bbc4d7db9c91",
            "git_mode": "100644",
            "line_count": 157,
            "sha256": "5411af794920cf4b170fe9dbe8c21c12cc63e2bbe2280d6d82acb850f4808be3",
        },
    }

    assert semantics_lock["exact_upstream_blobs"] == expected
    assert {
        path: evaluation_lock["source_blobs"][path] for path in expected
    } == expected
