"""Pure, fail-closed reconstruction of pinned Multi-SWE report semantics.

The pinned harness has two distinct decisions.  ``Report.check`` first
classifies the local transition evidence as valid or invalid.  The evaluation
reporter then checks that every frozen transition key is present in the
corresponding generated-report category.  Only both decisions together imply
``FinalReport.resolved``.

This module intentionally imports no Multi-SWE or TriMem runtime component.
It accepts already captured JSON-shaped values and returns a public summary
containing only counts, digests, booleans, and a reason code.  Test names are
never placed in the returned object or in validation error messages.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any


SCHEMA = "trimem/multi-swe-report-semantics/1.0"
PINNED_HARNESS_REVISION = "24f493f8a103e72312ded4f6b9c89f081d69cb09"
REPORT_VALID_PROJECTION = "LOCAL_TRANSITION_PREDICATE"
FINAL_RESOLVED_PROJECTION = (
    "REPORT_VALID AND ALL_FROZEN_EXPECTED_TRANSITION_KEYS_COVERED"
)
REPORT_CHECK_RULES = (
    "fix_patch_result contains at least one classified test",
    "no test has test=PASS and fix=FAIL",
    "at least one test has test!=PASS and fix=PASS",
    "no test has test in {NONE,SKIP}, fix=FAIL, and run=PASS",
)
REPORT_CHECK_REASON_CODES = (
    "NO_FIX_PATCH_TESTS",
    "PASS_TO_FAIL_REGRESSION",
    "NO_NON_PASS_TO_PASS_TRANSITION",
    "ANOMALOUS_NONE_OR_SKIP_TO_FAIL_AFTER_RUN_PASS",
)
PUBLIC_SUMMARY_FIELDS = frozenset(
    {
        "schema",
        "report_valid_observed",
        "report_valid_recomputed",
        "report_valid_match",
        "expected_coverage_complete",
        "expected_p2p_count",
        "observed_expected_p2p_count",
        "expected_f2p_count",
        "observed_expected_f2p_count",
        "expected_s2p_count",
        "observed_expected_s2p_count",
        "expected_n2p_count",
        "observed_expected_n2p_count",
        "missing_expected_transition_count",
        "expected_transition_domain_sha256",
        "observed_expected_transition_domain_sha256",
        "computed_resolved",
        "official_final_report_resolved",
        "final_report_match",
        "report_invalidity_reason",
    }
)
TRANSITION_CATEGORIES = (
    "p2p_tests",
    "f2p_tests",
    "s2p_tests",
    "n2p_tests",
)
_TEST_RESULT_FIELDS = {
    "passed_count",
    "failed_count",
    "skipped_count",
    "passed_tests",
    "failed_tests",
    "skipped_tests",
}
_STATUS_FIELDS = {
    "org",
    "repo",
    "number",
    "valid",
    "error_msg",
    "fixed_tests",
    "p2p_tests",
    "f2p_tests",
    "s2p_tests",
    "n2p_tests",
    "run_result",
    "test_patch_result",
    "fix_patch_result",
}
_FINAL_COUNT_TO_LIST = {
    "total_instances": None,
    "submitted_instances": "submitted_ids",
    "completed_instances": "completed_ids",
    "incomplete_instances": "incomplete_ids",
    "resolved_instances": "resolved_ids",
    "unresolved_instances": "unresolved_ids",
    "empty_patch_instances": "empty_patch_ids",
    "error_instances": "error_ids",
}
_FINAL_FIELDS = set(_FINAL_COUNT_TO_LIST) | {
    value for value in _FINAL_COUNT_TO_LIST.values() if value is not None
}
_INSTANCE_ID = re.compile(
    r"(?P<org>[A-Za-z0-9_.-]+)__(?P<repo>[A-Za-z0-9_.-]+)-"
    r"(?P<number>[1-9][0-9]*)"
)
_STATUS_VALUES = frozenset({"PASS", "FAIL", "SKIP", "NONE"})
_INVALID_ERROR_PREFIX = {
    "NO_FIX_PATCH_TESTS": (
        "After applying the fix patch, no test results were captured when "
        "executing the test command."
    ),
    "PASS_TO_FAIL_REGRESSION": (
        "Before applying the fix patch, the test passed; however, after "
        "applying the fix patch, the test failed."
    ),
    "NO_NON_PASS_TO_PASS_TRANSITION": (
        "After applying the fix patch, no test cases transitioned from failed "
        "to passed."
    ),
    "ANOMALOUS_NONE_OR_SKIP_TO_FAIL_AFTER_RUN_PASS": (
        "By comparing the test results before and after applying the fix patch, "
        "an anomalous pattern was detected."
    ),
}


class MultiSWEReportSemanticsError(ValueError):
    """A captured report cannot be accepted under the pinned semantics."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class MultiSWEReportSemantics:
    """Name-free canonical summary of one official Multi-SWE report."""

    report_valid_observed: bool
    report_valid_recomputed: bool
    report_valid_match: bool
    expected_coverage_complete: bool
    expected_p2p_count: int
    observed_expected_p2p_count: int
    expected_f2p_count: int
    observed_expected_f2p_count: int
    expected_s2p_count: int
    observed_expected_s2p_count: int
    expected_n2p_count: int
    observed_expected_n2p_count: int
    missing_expected_transition_count: int
    expected_transition_domain_sha256: str
    observed_expected_transition_domain_sha256: str
    computed_resolved: bool
    official_final_report_resolved: bool
    final_report_match: bool
    report_invalidity_reason: str

    def to_public_dict(self) -> dict[str, object]:
        """Return the stable public representation without raw test names."""

        return {
            "schema": SCHEMA,
            "report_valid_observed": self.report_valid_observed,
            "report_valid_recomputed": self.report_valid_recomputed,
            "report_valid_match": self.report_valid_match,
            "expected_coverage_complete": self.expected_coverage_complete,
            "expected_p2p_count": self.expected_p2p_count,
            "observed_expected_p2p_count": self.observed_expected_p2p_count,
            "expected_f2p_count": self.expected_f2p_count,
            "observed_expected_f2p_count": self.observed_expected_f2p_count,
            "expected_s2p_count": self.expected_s2p_count,
            "observed_expected_s2p_count": self.observed_expected_s2p_count,
            "expected_n2p_count": self.expected_n2p_count,
            "observed_expected_n2p_count": self.observed_expected_n2p_count,
            "missing_expected_transition_count": (
                self.missing_expected_transition_count
            ),
            "expected_transition_domain_sha256": (
                self.expected_transition_domain_sha256
            ),
            "observed_expected_transition_domain_sha256": (
                self.observed_expected_transition_domain_sha256
            ),
            "computed_resolved": self.computed_resolved,
            "official_final_report_resolved": (
                self.official_final_report_resolved
            ),
            "final_report_match": self.final_report_match,
            "report_invalidity_reason": self.report_invalidity_reason,
        }


@dataclass(frozen=True, slots=True)
class MultiSWEReportValidity:
    """Name-free Stage-A result for direct pinned-rule verification."""

    report_valid_recomputed: bool
    report_invalidity_reason: str
    fixed_transition_count: int
    p2p_count: int
    f2p_count: int
    s2p_count: int
    n2p_count: int


@dataclass(frozen=True, slots=True)
class _TestResult:
    passed: frozenset[str]
    failed: frozenset[str]
    skipped: frozenset[str]

    @property
    def domain(self) -> frozenset[str]:
        return self.passed | self.failed | self.skipped

    def classification(self, test_id: str) -> str:
        if test_id in self.passed:
            return "PASS"
        if test_id in self.failed:
            return "FAIL"
        if test_id in self.skipped:
            return "SKIP"
        return "NONE"


@dataclass(frozen=True, slots=True)
class _RecomputedReport:
    valid: bool
    invalidity_reason: str
    tests: Mapping[str, tuple[str, str, str]]
    fixed: Mapping[str, tuple[str, str, str]]
    categories: Mapping[str, Mapping[str, tuple[str, str, str]]]


def _fail(code: str, message: str) -> None:
    raise MultiSWEReportSemanticsError(code, message)


def _reject_constant(value: str) -> None:
    _fail("INVALID_JSON_CONSTANT", f"non-finite JSON constant is forbidden: {value}")


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("DUPLICATE_JSON_KEY", "captured JSON contains a duplicate object key")
        result[key] = value
    return result


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MultiSWEReportSemanticsError(
                "INVALID_UTF8", f"{label} is not strict UTF-8"
            ) from exc
    if isinstance(value, str):
        try:
            value = json.loads(
                value,
                object_pairs_hook=_strict_object_pairs,
                parse_constant=_reject_constant,
            )
        except MultiSWEReportSemanticsError:
            raise
        except json.JSONDecodeError as exc:
            raise MultiSWEReportSemanticsError(
                "INVALID_JSON", f"{label} is not strict JSON"
            ) from exc
    if not isinstance(value, Mapping):
        _fail("EXPECTED_OBJECT", f"{label} is not an object")
    return value


def _string_list(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        _fail("INVALID_TEST_LIST", f"{label} is not a JSON list")
    if any(not isinstance(item, str) or not item for item in value):
        _fail("INVALID_TEST_ID", f"{label} contains an invalid test identifier")
    if len(value) != len(set(value)):
        _fail("DUPLICATE_TEST_ID", f"{label} contains duplicate test identifiers")
    return tuple(value)


def _final_id_list(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        _fail("INVALID_FINAL_REPORT_ID_LIST", f"{label} is not a JSON list")
    if any(not isinstance(item, str) or not item for item in value):
        _fail("INVALID_FINAL_REPORT_ID", f"{label} contains an invalid target")
    if len(value) != len(set(value)):
        _fail(
            "DUPLICATE_FINAL_REPORT_ID",
            f"{label} contains duplicated target identifiers",
        )
    return tuple(value)


def _test_result(value: Any, label: str) -> _TestResult:
    row = _object(value, label)
    if set(row) != _TEST_RESULT_FIELDS:
        _fail("TEST_RESULT_FIELD_SET_DRIFT", f"{label} field set differs")
    groups: dict[str, tuple[str, ...]] = {}
    for kind in ("passed", "failed", "skipped"):
        tests = _string_list(row[f"{kind}_tests"], f"{label}.{kind}_tests")
        count = row[f"{kind}_count"]
        if type(count) is not int or count < 0 or count != len(tests):
            _fail("TEST_RESULT_COUNT_MISMATCH", f"{label}.{kind}_count differs")
        groups[kind] = tests
    if (
        set(groups["passed"]) & set(groups["failed"])
        or set(groups["passed"]) & set(groups["skipped"])
        or set(groups["failed"]) & set(groups["skipped"])
    ):
        _fail("TEST_RESULT_CLASSIFICATION_OVERLAP", f"{label} classifications overlap")
    return _TestResult(
        passed=frozenset(groups["passed"]),
        failed=frozenset(groups["failed"]),
        skipped=frozenset(groups["skipped"]),
    )


def _transition_map(
    value: Any, label: str
) -> dict[str, tuple[str, str, str]]:
    row = _object(value, label)
    parsed: dict[str, tuple[str, str, str]] = {}
    for test_id, raw_transition in row.items():
        if not isinstance(test_id, str) or not test_id:
            _fail("INVALID_TEST_ID", f"{label} contains an invalid test identifier")
        transition = _object(raw_transition, f"{label}.transition")
        if set(transition) != {"run", "test", "fix"}:
            _fail("TRANSITION_FIELD_SET_DRIFT", f"{label} transition field set differs")
        values = tuple(transition[name] for name in ("run", "test", "fix"))
        if any(type(item) is not str or item not in _STATUS_VALUES for item in values):
            _fail("INVALID_TRANSITION_STATUS", f"{label} contains an invalid status")
        parsed[test_id] = (values[0], values[1], values[2])
    return parsed


def _results(row: Mapping[str, Any], label: str) -> dict[str, _TestResult]:
    result: dict[str, _TestResult] = {}
    for name in ("run_result", "test_patch_result", "fix_patch_result"):
        if name not in row:
            _fail("MISSING_TEST_RESULT", f"{label}.{name} is missing")
        result[name] = _test_result(row[name], f"{label}.{name}")
    return result


def _recompute(results: Mapping[str, _TestResult]) -> _RecomputedReport:
    run = results["run_result"]
    test = results["test_patch_result"]
    fix = results["fix_patch_result"]
    domain = run.domain | test.domain | fix.domain
    tests = {
        name: (
            run.classification(name),
            test.classification(name),
            fix.classification(name),
        )
        for name in domain
    }
    empty_categories: dict[str, Mapping[str, tuple[str, str, str]]] = {
        name: {} for name in TRANSITION_CATEGORIES
    }
    if not fix.domain:
        return _RecomputedReport(
            False, "NO_FIX_PATCH_TESTS", tests, {}, empty_categories
        )
    if any(
        test_status == "PASS" and fix_status == "FAIL"
        for _, test_status, fix_status in tests.values()
    ):
        return _RecomputedReport(
            False, "PASS_TO_FAIL_REGRESSION", tests, {}, empty_categories
        )
    fixed = {
        name: triple
        for name, triple in tests.items()
        if triple[1] != "PASS" and triple[2] == "PASS"
    }
    if not fixed:
        return _RecomputedReport(
            False, "NO_NON_PASS_TO_PASS_TRANSITION", tests, {}, empty_categories
        )
    if any(
        test_status in {"NONE", "SKIP"}
        and fix_status == "FAIL"
        and run_status == "PASS"
        for run_status, test_status, fix_status in tests.values()
    ):
        return _RecomputedReport(
            False,
            "ANOMALOUS_NONE_OR_SKIP_TO_FAIL_AFTER_RUN_PASS",
            tests,
            fixed,
            empty_categories,
        )
    categories: dict[str, dict[str, tuple[str, str, str]]] = {
        name: {} for name in TRANSITION_CATEGORIES
    }
    category_for_test_status = {
        "PASS": "p2p_tests",
        "FAIL": "f2p_tests",
        "SKIP": "s2p_tests",
        "NONE": "n2p_tests",
    }
    for name, triple in tests.items():
        if triple[2] == "PASS":
            categories[category_for_test_status[triple[1]]][name] = triple
    return _RecomputedReport(True, "NONE", tests, fixed, categories)


def _require_identity(
    instance_id: str,
    source_row: Mapping[str, Any],
    status: Mapping[str, Any],
) -> tuple[str, str, int, str]:
    org, repo, number, canonical_id = _canonical_identity(instance_id)
    expected = (org, repo, number)
    for row, label in ((source_row, "source"), (status, "status")):
        observed = tuple(row.get(name) for name in ("org", "repo", "number"))
        if (
            type(observed[0]) is not str
            or type(observed[1]) is not str
            or type(observed[2]) is not int
            or observed != expected
        ):
            _fail("IDENTITY_MISMATCH", f"{label} identity differs from the frozen target")
    return org, repo, number, canonical_id


def _canonical_identity(instance_id: str) -> tuple[str, str, int, str]:
    """Return the pinned dataset and FinalReport identities for one target."""

    if not isinstance(instance_id, str):
        _fail("INVALID_IDENTITY", "instance identity is not a string")
    match = _INSTANCE_ID.fullmatch(instance_id)
    if match is None:
        _fail("INVALID_IDENTITY", "instance identity format differs")
    org = match.group("org")
    repo = match.group("repo")
    number = int(match.group("number"))
    return org, repo, number, f"{org}/{repo}:pr-{number}"


def _expected_categories(
    source_row: Mapping[str, Any], source_report: _RecomputedReport
) -> dict[str, dict[str, tuple[str, str, str]]]:
    if not source_report.valid:
        _fail("INVALID_FROZEN_SOURCE", "frozen source Report.check is invalid")
    expected = {
        name: _transition_map(source_row.get(name), f"source.{name}")
        for name in TRANSITION_CATEGORIES
    }
    all_ids: set[str] = set()
    for name in TRANSITION_CATEGORIES:
        overlap = all_ids & set(expected[name])
        if overlap:
            _fail(
                "EXPECTED_TRANSITION_OVERLAP",
                "frozen expected transition categories overlap",
            )
        all_ids.update(expected[name])
        if expected[name] != source_report.categories[name]:
            _fail(
                "INVALID_FROZEN_TRANSITIONS",
                f"frozen {name} differs from its TestResult reconstruction",
            )
    return expected


def _observed_categories(
    status: Mapping[str, Any], recomputed: _RecomputedReport
) -> dict[str, dict[str, tuple[str, str, str]]]:
    observed = {
        name: _transition_map(status.get(name), f"status.{name}")
        for name in TRANSITION_CATEGORIES
    }
    fixed = _transition_map(status.get("fixed_tests"), "status.fixed_tests")
    if fixed != recomputed.fixed:
        _fail("FIXED_TRANSITION_MISMATCH", "observed fixed transitions differ")
    for name in TRANSITION_CATEGORIES:
        if observed[name] != recomputed.categories[name]:
            _fail(
                "OBSERVED_TRANSITION_MISMATCH",
                f"observed {name} differs from TestResult reconstruction",
            )
    return observed


def _result_identity(results: Mapping[str, _TestResult]) -> tuple[object, ...]:
    return tuple(
        (
            results[name].passed,
            results[name].failed,
            results[name].skipped,
        )
        for name in ("run_result", "test_patch_result")
    )


def _validate_source_result_binding(
    source_results: Mapping[str, _TestResult],
    observed_results: Mapping[str, _TestResult],
) -> None:
    if _result_identity(source_results) != _result_identity(observed_results):
        _fail(
            "FROZEN_CLASSIFICATION_MISMATCH",
            "observed run or test-patch classifications differ from frozen source",
        )


def _final_resolved(final_report: Mapping[str, Any], canonical_id: str) -> bool:
    if set(final_report) != _FINAL_FIELDS:
        _fail("FINAL_REPORT_FIELD_SET_DRIFT", "FinalReport field set differs")
    lists: dict[str, tuple[str, ...]] = {}
    for count_name, list_name in _FINAL_COUNT_TO_LIST.items():
        count = final_report[count_name]
        if type(count) is not int or count < 0:
            _fail("FINAL_REPORT_COUNT_INVALID", f"FinalReport {count_name} is invalid")
        if list_name is not None:
            items = _final_id_list(
                final_report[list_name], f"FinalReport.{list_name}"
            )
            if count != len(items):
                _fail("FINAL_REPORT_COUNT_MISMATCH", f"FinalReport {count_name} differs")
            if any(item != canonical_id for item in items):
                _fail("UNKNOWN_FINAL_REPORT_ID", "FinalReport contains an unknown target")
            lists[list_name] = items
    if final_report["total_instances"] != 1:
        _fail("FINAL_REPORT_TOTAL_MISMATCH", "FinalReport is not one-target scoped")
    if (
        lists["submitted_ids"] != (canonical_id,)
        or lists["completed_ids"] != (canonical_id,)
        or lists["incomplete_ids"]
        or lists["empty_patch_ids"]
        or lists["error_ids"]
    ):
        _fail("FINAL_REPORT_LIFECYCLE_MISMATCH", "FinalReport lifecycle differs")
    resolved = lists["resolved_ids"] == (canonical_id,)
    unresolved = lists["unresolved_ids"] == (canonical_id,)
    if resolved == unresolved:
        _fail(
            "FINAL_REPORT_CLASSIFICATION_MISMATCH",
            "FinalReport does not classify the target exactly once",
        )
    return resolved


def _domain_digest(categories: Mapping[str, set[str]]) -> str:
    payload = {
        name: sorted(categories[name]) for name in TRANSITION_CATEGORIES
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def recompute_multi_swe_report_validity(
    *,
    run_result: Mapping[str, Any] | str | bytes,
    test_patch_result: Mapping[str, Any] | str | bytes,
    fix_patch_result: Mapping[str, Any] | str | bytes,
) -> MultiSWEReportValidity:
    """Recompute the four ordered rules applied by pinned ``Report.check()``."""

    recomputed = _recompute(
        {
            "run_result": _test_result(run_result, "run_result"),
            "test_patch_result": _test_result(
                test_patch_result, "test_patch_result"
            ),
            "fix_patch_result": _test_result(fix_patch_result, "fix_patch_result"),
        }
    )
    return MultiSWEReportValidity(
        report_valid_recomputed=recomputed.valid,
        report_invalidity_reason=recomputed.invalidity_reason,
        fixed_transition_count=len(recomputed.fixed),
        p2p_count=len(recomputed.categories["p2p_tests"]),
        f2p_count=len(recomputed.categories["f2p_tests"]),
        s2p_count=len(recomputed.categories["s2p_tests"]),
        n2p_count=len(recomputed.categories["n2p_tests"]),
    )


def validate_multi_swe_final_report_outcome(
    *,
    instance_id: str,
    final_report: Mapping[str, Any] | str | bytes,
) -> bool:
    """Strictly classify one pinned Multi-SWE ``FinalReport``.

    This is the Stage-B lifecycle/classification parser used before the
    per-instance report is available.  It deliberately does not claim that the
    classification is semantically correct; callers must subsequently invoke
    :func:`validate_multi_swe_report_semantics` to bind it to ``Report.check``
    and frozen expected-transition coverage.
    """

    _, _, _, canonical_id = _canonical_identity(instance_id)
    return _final_resolved(_object(final_report, "final report"), canonical_id)


def report_semantics_truth_table() -> list[dict[str, bool]]:
    """Return the canonical two-stage truth table used by the contract lock."""

    rows: list[dict[str, bool]] = []
    for report_valid in (False, True):
        for expected_coverage_complete in (False, True):
            computed_resolved = report_valid and expected_coverage_complete
            for final_resolved in (False, True):
                rows.append(
                    {
                        "accept": final_resolved is computed_resolved,
                        "computed_resolved": computed_resolved,
                        "expected_coverage_complete": expected_coverage_complete,
                        "final_resolved": final_resolved,
                        "report_valid": report_valid,
                    }
                )
    return rows


def validate_public_summary(value: Mapping[str, Any]) -> dict[str, object]:
    """Validate a name-free summary without access to restricted raw evidence."""

    if not isinstance(value, Mapping) or set(value) != PUBLIC_SUMMARY_FIELDS:
        _fail("PUBLIC_SUMMARY_FIELD_SET_DRIFT", "public semantics field set differs")
    if value.get("schema") != SCHEMA:
        _fail("PUBLIC_SUMMARY_SCHEMA_DRIFT", "public semantics schema differs")
    boolean_fields = (
        "report_valid_observed",
        "report_valid_recomputed",
        "report_valid_match",
        "expected_coverage_complete",
        "computed_resolved",
        "official_final_report_resolved",
        "final_report_match",
    )
    if any(type(value.get(name)) is not bool for name in boolean_fields):
        _fail("PUBLIC_SUMMARY_BOOLEAN_INVALID", "public semantics boolean is invalid")
    count_fields = tuple(
        name for name in PUBLIC_SUMMARY_FIELDS if name.endswith("_count")
    )
    if any(type(value.get(name)) is not int or value[name] < 0 for name in count_fields):
        _fail("PUBLIC_SUMMARY_COUNT_INVALID", "public semantics count is invalid")
    missing = 0
    for category in ("p2p", "f2p", "s2p", "n2p"):
        expected = value[f"expected_{category}_count"]
        observed = value[f"observed_expected_{category}_count"]
        if observed > expected:
            _fail(
                "PUBLIC_SUMMARY_COUNT_INCONSISTENT",
                "observed expected-transition count exceeds frozen count",
            )
        missing += expected - observed
    if value["missing_expected_transition_count"] != missing:
        _fail("PUBLIC_SUMMARY_COUNT_INCONSISTENT", "public missing count differs")
    if value["expected_coverage_complete"] is not (missing == 0):
        _fail("PUBLIC_SUMMARY_COVERAGE_INCONSISTENT", "public coverage differs")
    for name in (
        "expected_transition_domain_sha256",
        "observed_expected_transition_domain_sha256",
    ):
        digest = value.get(name)
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            _fail("PUBLIC_SUMMARY_DIGEST_INVALID", "public semantics digest is invalid")
    digest_domains_match = (
        value["expected_transition_domain_sha256"]
        == value["observed_expected_transition_domain_sha256"]
    )
    if value["expected_coverage_complete"] is not digest_domains_match:
        _fail(
            "PUBLIC_SUMMARY_DOMAIN_DIGEST_INCONSISTENT",
            "public coverage and transition-domain digests differ",
        )
    if (
        value["report_valid_match"] is not True
        or value["report_valid_observed"] is not value["report_valid_recomputed"]
    ):
        _fail("PUBLIC_SUMMARY_VALIDITY_MISMATCH", "public validity fields differ")
    computed = (
        value["report_valid_recomputed"] and value["expected_coverage_complete"]
    )
    if (
        value["computed_resolved"] is not computed
        or value["final_report_match"] is not True
        or value["official_final_report_resolved"] is not computed
    ):
        _fail("PUBLIC_SUMMARY_FINAL_MISMATCH", "public final semantics fields differ")
    reason = value.get("report_invalidity_reason")
    expected_reasons = {"NONE"} if value["report_valid_recomputed"] else set(
        REPORT_CHECK_REASON_CODES
    )
    if reason not in expected_reasons:
        _fail("PUBLIC_SUMMARY_REASON_INVALID", "public invalidity reason differs")
    return dict(value)


validate_public_semantics_summary = validate_public_summary


def validate_multi_swe_report_semantics(
    *,
    instance_id: str,
    source_row: Mapping[str, Any] | str | bytes,
    status: Mapping[str, Any] | str | bytes,
    final_report: Mapping[str, Any] | str | bytes,
) -> MultiSWEReportSemantics:
    """Validate one captured two-stage report and return its public summary.

    ``source_row`` is the exact frozen Dataset row. ``status`` is the generated
    per-instance ``Report`` and ``final_report`` is the one-target
    ``FinalReport``.  A valid local report is allowed to be finally unresolved
    precisely when at least one frozen transition key is missing.
    """

    source = _object(source_row, "source row")
    observed = _object(status, "per-instance report")
    final = _object(final_report, "final report")
    if set(observed) != _STATUS_FIELDS:
        _fail(
            "STATUS_FIELD_SET_DRIFT",
            "per-instance Report field set differs from the pinned Report schema",
        )
    _, _, _, canonical_id = _require_identity(instance_id, source, observed)

    source_results = _results(source, "source")
    observed_results = _results(observed, "status")
    _validate_source_result_binding(source_results, observed_results)
    source_recomputed = _recompute(source_results)
    recomputed = _recompute(observed_results)

    expected = _expected_categories(source, source_recomputed)
    actual_categories = _observed_categories(observed, recomputed)
    observed_valid = observed.get("valid")
    if type(observed_valid) is not bool:
        _fail("NON_BOOLEAN_REPORT_VALID", "per-instance Report.valid is not boolean")
    valid_match = observed_valid is recomputed.valid
    if not valid_match:
        _fail(
            "REPORT_VALID_MISMATCH",
            "observed Report.valid differs from pinned Report.check",
        )
    error_msg = observed.get("error_msg")
    if observed_valid:
        if error_msg != "":
            _fail("VALID_REPORT_ERROR_MISMATCH", "valid report error text is not empty")
    else:
        prefix = _INVALID_ERROR_PREFIX[recomputed.invalidity_reason]
        if not isinstance(error_msg, str) or not error_msg.startswith(prefix):
            _fail(
                "INVALID_REPORT_ERROR_MISMATCH",
                "invalid report reason is not structurally upstream-equivalent",
            )

    expected_names = {name: set(expected[name]) for name in TRANSITION_CATEGORIES}
    observed_expected_names = {
        name: expected_names[name] & set(actual_categories[name])
        for name in TRANSITION_CATEGORIES
    }
    expected_counts = {name: len(expected_names[name]) for name in TRANSITION_CATEGORIES}
    observed_counts = {
        name: len(observed_expected_names[name]) for name in TRANSITION_CATEGORIES
    }
    missing = sum(
        expected_counts[name] - observed_counts[name]
        for name in TRANSITION_CATEGORIES
    )
    coverage_complete = missing == 0
    computed_resolved = recomputed.valid and coverage_complete
    official_resolved = _final_resolved(final, canonical_id)
    final_match = official_resolved is computed_resolved
    if not final_match:
        _fail(
            "FINAL_REPORT_SEMANTICS_MISMATCH",
            "FinalReport classification differs from two-stage recomputation",
        )
    if observed_valid and not official_resolved and missing <= 0:
        _fail(
            "UNEXPLAINED_VALID_UNRESOLVED",
            "valid unresolved report has no missing frozen transition",
        )

    return MultiSWEReportSemantics(
        report_valid_observed=observed_valid,
        report_valid_recomputed=recomputed.valid,
        report_valid_match=valid_match,
        expected_coverage_complete=coverage_complete,
        expected_p2p_count=expected_counts["p2p_tests"],
        observed_expected_p2p_count=observed_counts["p2p_tests"],
        expected_f2p_count=expected_counts["f2p_tests"],
        observed_expected_f2p_count=observed_counts["f2p_tests"],
        expected_s2p_count=expected_counts["s2p_tests"],
        observed_expected_s2p_count=observed_counts["s2p_tests"],
        expected_n2p_count=expected_counts["n2p_tests"],
        observed_expected_n2p_count=observed_counts["n2p_tests"],
        missing_expected_transition_count=missing,
        expected_transition_domain_sha256=_domain_digest(expected_names),
        observed_expected_transition_domain_sha256=_domain_digest(
            observed_expected_names
        ),
        computed_resolved=computed_resolved,
        official_final_report_resolved=official_resolved,
        final_report_match=final_match,
        report_invalidity_reason=recomputed.invalidity_reason,
    )


__all__ = [
    "MultiSWEReportSemantics",
    "MultiSWEReportSemanticsError",
    "MultiSWEReportValidity",
    "FINAL_RESOLVED_PROJECTION",
    "PINNED_HARNESS_REVISION",
    "PUBLIC_SUMMARY_FIELDS",
    "REPORT_CHECK_REASON_CODES",
    "REPORT_CHECK_RULES",
    "REPORT_VALID_PROJECTION",
    "SCHEMA",
    "TRANSITION_CATEGORIES",
    "recompute_multi_swe_report_validity",
    "report_semantics_truth_table",
    "validate_public_semantics_summary",
    "validate_public_summary",
    "validate_multi_swe_final_report_outcome",
    "validate_multi_swe_report_semantics",
]
