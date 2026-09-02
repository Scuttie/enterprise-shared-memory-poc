from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import trimem_benchmark_matrix as benchmark_matrix  # noqa: E402
import trimem_grader_smoke as grader_smoke  # noqa: E402
import trimem_public_artifact as public_artifact  # noqa: E402
from enterprise_memory.trimem.grader import GradeResult  # noqa: E402


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _smoke_accounting(grader_count: int) -> dict[str, int]:
    return {
        field: grader_count
        if field in {"grader_calls", "grader_containers", "official_grader_runs"}
        else 0
        for field in grader_smoke.SMOKE_ACCOUNTING_FIELDS
    }


ZERO_SMOKE_ACCOUNTING_FIELDS = tuple(
    field
    for field in grader_smoke.SMOKE_ACCOUNTING_FIELDS
    if field not in {"grader_calls", "grader_containers", "official_grader_runs"}
)


def _target(benchmark_id: str = "multi_swe_bench_mini") -> dict[str, object]:
    return {
        "target_id": f"{benchmark_id}--fixture--gold",
        "benchmark_id": benchmark_id,
        "instance_id": (
            "astropy__astropy-13579"
            if benchmark_id == "swebench_verified"
            else "vuejs__core-8911"
        ),
        "probe": "GOLD",
        "order_index": 0,
    }


def _grade(contract: dict[str, object]) -> GradeResult:
    return GradeResult(
        task_id="fixture",
        resolved=True,
        exit_code=0,
        stdout="",
        stderr="",
        report={"_trimem": {"execution_contract": contract}},
        grader_id="fixture",
        container_digest="fixture@sha256:" + "d" * 64,
        official=True,
        wall_time_ms=1,
        container_started=True,
    )


@pytest.mark.parametrize(
    "benchmark_id", ["swebench_verified", "multi_swe_bench_mini"]
)
def test_runtime_requires_exact_patch_bound_execution_contract(
    benchmark_id: str,
) -> None:
    patch = b"diff --git a/a b/a\n"
    target = _target(benchmark_id)
    expected = grader_smoke._expected_execution_contract(target, patch)

    assert grader_smoke._validated_execution_contract(
        _grade(expected), target=target, patch_raw=patch
    ) == expected

    drifted = {**expected, "submitted_patch_sha256": "0" * 64}
    with pytest.raises(
        grader_smoke.BenchmarkExecutionError,
        match="drifted from the submitted patch",
    ):
        grader_smoke._validated_execution_contract(
            _grade(drifted), target=target, patch_raw=patch
        )


def _contract_evidence_fixture(
    tmp_path: Path,
) -> tuple[Path, dict[str, object], dict[str, object], bytes, dict[str, object]]:
    target = _target()
    patch = b"submitted sentinel patch\n"
    contract = benchmark_matrix._expected_smoke_execution_contract(target, patch)
    contract_sha256 = hashlib.sha256(_canonical(contract)).hexdigest()
    document = {
        "schema": "trimem/grader-smoke-execution-contract-evidence/1.0",
        "target_id": target["target_id"],
        "execution_contract_sha256": contract_sha256,
        "execution_contract": contract,
    }
    raw = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode(
        "utf-8"
    ) + b"\n"
    evidence_path = tmp_path / "execution-contract-evidence.json"
    evidence_path.write_bytes(raw)
    result_file = tmp_path / "fixture.result.json"
    record: dict[str, object] = {
        "execution_contract_sha256": contract_sha256,
        "execution_evidence": {
            "patch_applied": True,
            "tests_executed": True,
            "digest_match": True,
            "submitted_patch_identity": True,
            "host_prepare_sh_access_count": 0,
            "source_image_build_count": 0,
            "api_calls": 0,
        },
        "evidence": {
            "execution_contract": {
                "path": evidence_path.name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
        },
    }
    report = {"_trimem": {"execution_contract": contract}}
    return result_file, target, record, patch, report


def test_aggregate_contract_validator_binds_report_file_record_and_patch(
    tmp_path: Path,
) -> None:
    result_file, target, record, patch, report = _contract_evidence_fixture(tmp_path)

    sealed = benchmark_matrix._validate_smoke_execution_contract(
        result_file, target, patch, report, record
    )
    assert sealed == {
        "execution_contract_sha256": record["execution_contract_sha256"],
        "execution_contract": report["_trimem"]["execution_contract"],
    }

    report["_trimem"]["execution_contract"]["host_prepare_script_reads"] = 1
    with pytest.raises(benchmark_matrix.MatrixError, match="contract evidence drift"):
        benchmark_matrix._validate_smoke_execution_contract(
            result_file, target, patch, report, record
        )


def _private_input_rows(
    target: dict[str, object], patch: bytes
) -> list[dict[str, object]]:
    prediction = grader_smoke._prediction_input_bytes(target, patch)
    rows = []
    names = (
        ["dataset.json", "prediction.jsonl"]
        if target["benchmark_id"] == "swebench_verified"
        else ["dataset.jsonl", "prediction.jsonl", "config.json"]
    )
    for name in names:
        raw = prediction if name == "prediction.jsonl" else (name + "\n").encode()
        rows.append({
            "name": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "retention": "PURGED_AFTER_HASH_BOUND_GRADING",
        })
    return rows


def _submitted_identity_fixture(
    tmp_path: Path, benchmark_id: str
) -> tuple[Path, dict[str, object], bytes, dict[str, object], dict[str, object]]:
    target = _target(benchmark_id)
    patch = b"submitted sentinel patch\n"
    grader_root = tmp_path / "official-grader"
    grader_root.mkdir()
    applied_ref = {
        "path": "restricted-input/applied.patch",
        "sha256": hashlib.sha256(patch).hexdigest(),
        "bytes": len(patch),
    }
    trimem: dict[str, object] = {
        "materialized_private_inputs": _private_input_rows(target, patch),
    }
    if benchmark_id != "swebench_verified":
        digest = hashlib.sha256(patch).hexdigest()
        restricted_relative = (
            f"restricted-evidence/submitted-patch-materialized-{digest}.bin"
        )
        restricted_path = grader_root / restricted_relative
        restricted_path.parent.mkdir()
        restricted_path.write_bytes(patch)
        task_relative = str(target["target_id"]).replace("/", "_")
        trimem["materialized_patch_evidence"] = {
            "schema": "trimem/materialized-submitted-patch-evidence/1.0",
            "host_path": (
                f"{task_relative}/work/vuejs/core/evals/pr-8911/fix.patch"
            ),
            "container_destination": "/home/fix.patch",
            "mode": "rw",
            "bytes": len(patch),
            "sha256": digest,
            "request_identity_match": True,
            "restricted_materialized_patch": {
                "path": restricted_relative,
                "sha256": digest,
                "bytes": len(patch),
                "access": "RESTRICTED_RAW_NOT_FOR_PUBLIC_LOGS",
            },
            "purged_after_capture": True,
        }
    grade = _grade({})
    grade = GradeResult(**{**grade.__dict__, "report": {"_trimem": trimem}})
    identity = grader_smoke._validated_submitted_patch_identity(
        grade,
        target=target,
        patch_raw=patch,
        grader_root=grader_root,
        restricted_submitted_patch=applied_ref,
    )
    identity_sha = hashlib.sha256(_canonical(identity)).hexdigest()
    raw = json.dumps(
        {**identity, "identity_evidence_sha256": identity_sha},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    direct_path = tmp_path / "submitted-patch-identity-evidence.json"
    direct_path.write_bytes(raw)
    result_file = tmp_path / "fixture.result.json"
    record: dict[str, object] = {
        "submitted_patch_identity_sha256": identity_sha,
        "evidence": {
            "applied_patch": applied_ref,
            "submitted_patch_identity": {
                "path": direct_path.name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            },
        },
    }
    report = {"_trimem": trimem}
    return result_file, target, patch, report, record


@pytest.mark.parametrize(
    "benchmark_id", ["swebench_verified", "multi_swe_bench_mini"]
)
def test_submitted_patch_identity_requires_prediction_and_materialized_bytes(
    tmp_path: Path, benchmark_id: str
) -> None:
    result_file, target, patch, report, record = _submitted_identity_fixture(
        tmp_path, benchmark_id
    )
    assert benchmark_matrix._validate_smoke_submitted_patch_identity(
        result_file, target, patch, report, record
    )["submitted_patch_identity"] is True

    report["_trimem"]["materialized_private_inputs"][1]["sha256"] = "0" * 64
    with pytest.raises(benchmark_matrix.MatrixError, match="prediction input"):
        benchmark_matrix._validate_smoke_submitted_patch_identity(
            result_file, target, patch, report, record
        )


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "not_purged"])
def test_multi_submitted_patch_identity_fails_closed_on_malformed_evidence(
    tmp_path: Path, mutation: str
) -> None:
    result_file, target, patch, report, record = _submitted_identity_fixture(
        tmp_path, "multi_swe_bench_mini"
    )
    trimem = report["_trimem"]
    if mutation == "missing":
        del trimem["materialized_patch_evidence"]
    elif mutation == "duplicate":
        trimem["materialized_private_inputs"].append(
            dict(trimem["materialized_private_inputs"][1])
        )
    else:
        trimem["materialized_patch_evidence"]["purged_after_capture"] = False

    with pytest.raises(benchmark_matrix.MatrixError):
        benchmark_matrix._validate_smoke_submitted_patch_identity(
            result_file, target, patch, report, record
        )


def test_execution_control_is_direct_and_matches_contract(tmp_path: Path) -> None:
    target = _target("multi_swe_bench_mini")
    patch = b"submitted patch\n"
    contract = benchmark_matrix._expected_smoke_execution_contract(target, patch)
    control = grader_smoke._expected_execution_control(target)
    grade = _grade(contract)
    grade = GradeResult(**{
        **grade.__dict__,
        "report": {"_trimem": {
            "execution_contract": contract,
            "execution_control_evidence": control,
        }},
    })
    assert grader_smoke._validated_execution_control(
        grade, target=target, execution_contract=contract
    ) == control

    control_sha = hashlib.sha256(_canonical(control)).hexdigest()
    document = {
        "schema": "trimem/grader-smoke-execution-control-evidence/1.0",
        "target_id": target["target_id"],
        "execution_control_sha256": control_sha,
        "execution_control": control,
    }
    raw = json.dumps(document, indent=2, sort_keys=True).encode() + b"\n"
    path = tmp_path / "execution-control-evidence.json"
    path.write_bytes(raw)
    record = {
        "execution_control_sha256": control_sha,
        "evidence": {"execution_control": {
            "path": path.name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }},
    }
    report = grade.report
    sealed = benchmark_matrix._validate_smoke_execution_control(
        tmp_path / "fixture.result.json",
        target,
        grader_smoke.MULTI_HARNESS_REVISION,
        report,
        record,
        contract,
    )
    assert sealed["host_prepare_sh_access_count"] == 0
    assert sealed["source_image_build_count"] == 0

    report["_trimem"]["execution_control_evidence"][
        "host_prepare_script_reads"
    ] = 1
    with pytest.raises(benchmark_matrix.MatrixError, match="control evidence drift"):
        benchmark_matrix._validate_smoke_execution_control(
            tmp_path / "fixture.result.json",
            target,
            grader_smoke.MULTI_HARNESS_REVISION,
            report,
            record,
            contract,
        )


def test_summary_does_not_infer_blanket_success_from_no_failures() -> None:
    targets = [
        {
            "target_id": f"target-{index}",
            "benchmark_id": (
                "swebench_verified" if index < 4 else "multi_swe_bench_mini"
            ),
            "probe": "GOLD" if index % 2 == 0 else "NOOP_BASELINE",
            "expected_resolved": index % 2 == 0,
        }
        for index in range(12)
    ]
    evidence = [
        {
            "target_id": target["target_id"],
            "patch_applied": index != 4,
            "tests_executed": True,
            "digest_match": True,
            "submitted_patch_identity": True,
            "host_prepare_sh_access_count": 0,
            "source_image_build_count": 0,
            "api_calls": 0,
            "container_exit_status_code": None if index < 4 else (0 if index % 2 == 0 else 1),
            "container_exit_acceptance": (
                None
                if index < 4
                else (
                    "ZERO_EXIT"
                    if index % 2 == 0
                    else "NONZERO_ACCEPTED_AFTER_FULL_DOMAIN_UNRESOLVED_VALIDATION"
                )
            ),
            "container_exit_status_sha256": None if index < 4 else "f" * 64,
            "actual_accounting": _smoke_accounting(1),
        }
        for index, target in enumerate(targets)
    ]

    summary = grader_smoke._smoke_execution_summary(
        targets,
        evidence,
        failures=[],
        infrastructure_failures=[],
    )

    assert summary["patch_applied_count"] == 11
    assert summary["submitted_patch_identity_count"] == 12
    assert summary["host_prepare_sh_access_count"] == 0
    assert summary["source_image_build_count"] == 0
    assert summary["api_calls"] == 0
    assert summary["container_exit_status_captured_count"] == 8
    assert summary["container_exit_status_validated_count"] == 8
    assert summary["resolved_container_zero_exit_count"] == 4
    assert {field: summary[field] for field in grader_smoke.SMOKE_ACCOUNTING_FIELDS} == (
        _smoke_accounting(12)
    )
    assert summary["status"] == "FAIL"
    assert "PATCH_APPLIED_COUNT" in summary["failures"]

    evidence[0]["patch_applied"] = True
    evidence[0]["actual_accounting"]["input_tokens"] = 1
    accounting_failure = grader_smoke._smoke_execution_summary(
        targets,
        evidence,
        failures=[],
        infrastructure_failures=[],
    )
    assert accounting_failure["status"] == "FAIL"
    assert "ACTUAL_ACCOUNTING" in accounting_failure["failures"]


def _sealed_public_aggregate() -> dict[str, object]:
    outcomes = [
        {
            "target_id": f"target-{index}",
            "benchmark_id": (
                "swebench_verified" if index < 4 else "multi_swe_bench_mini"
            ),
            "order_index": index,
            "probe": "GOLD" if index % 2 == 0 else "NOOP_BASELINE",
            "resolved": index % 2 == 0,
            "applied_patch_sha256": "a" * 64,
            "official_test_output_sha256": "b" * 64,
            "official_test_status_sha256": "c" * 64,
            "execution_contract_sha256": "d" * 64,
            "execution_control_sha256": "e" * 64,
            "submitted_patch_identity_sha256": "f" * 64,
            "patch_applied": True,
            "tests_executed": True,
            "digest_match": True,
            "submitted_patch_identity": True,
            "host_prepare_sh_access_count": 0,
            "source_image_build_count": 0,
            "api_calls": 0,
            "container_exit_status_code": None if index < 4 else (0 if index % 2 == 0 else 1),
            "container_exit_acceptance": (
                None
                if index < 4
                else (
                    "ZERO_EXIT"
                    if index % 2 == 0
                    else "NONZERO_ACCEPTED_AFTER_FULL_DOMAIN_UNRESOLVED_VALIDATION"
                )
            ),
            "container_exit_status_sha256": None if index < 4 else "9" * 64,
        }
        for index in range(12)
    ]
    evidence_counts = {
        name: 12
        for name in (
            "patch",
            "tests",
            "container",
            "evaluator",
            "report",
            "digest",
            "execution_contract",
            "execution_control",
            "submitted_patch_identity",
            "applied_patch",
            "test_output",
            "official_test_status",
        )
    }
    evidence_counts["container_exit_status"] = 8
    body: dict[str, object] = {
        "schema": "trimem/verified-aggregate/1.0",
        "status": "PASS",
        "manifest": "grader-smoke",
        "outcomes": outcomes,
        "stream_totals": [],
        "approval_binding": {
            "approval_artifact_sha256": "1" * 64,
            "approved_request_sha256": "2" * 64,
            "approved_workflow_run_id": "1",
            "approved_workflow_run_attempt": "1",
            "freeze_sha256": "3" * 64,
            "git_head": "4" * 40,
            "phase": "GRADER_SMOKE",
        },
        "actual_accounting": _smoke_accounting(12),
        "api_calls": 0,
        "digest_match_count": 12,
        "container_exit_status_captured_count": 8,
        "container_exit_status_validated_count": 8,
        "empty_patch_ids": [],
        "evidence_counts": evidence_counts,
        "expected_target_count": 12,
        "host_prepare_sh_access_count": 0,
        "image_lifecycle": {"status": "PASS"},
        "infrastructure_failure_count": 0,
        "observed_target_count": 12,
        "patch_applied_count": 12,
        "probe_counts": {"GOLD": 6, "NOOP_BASELINE": 6},
        "resolved_counts": {"GOLD": 6, "NOOP_BASELINE": 0},
        "resolved_container_zero_exit_count": 4,
        "source_image_build_count": 0,
        "submitted_patch_identity_count": 12,
        "tests_executed_count": 12,
        "unresolved_counts": {"GOLD": 0, "NOOP_BASELINE": 6},
    }
    return {
        **body,
        "aggregate_sha256": hashlib.sha256(_canonical(body)).hexdigest(),
    }


def test_public_artifact_requires_execution_contract_counters(tmp_path: Path) -> None:
    aggregate = _sealed_public_aggregate()
    path = tmp_path / "aggregate.json"
    path.write_bytes(_canonical(aggregate))
    assert public_artifact._verified_aggregate(path) == aggregate

    aggregate["submitted_patch_identity_count"] = 11
    body = {key: value for key, value in aggregate.items() if key != "aggregate_sha256"}
    aggregate["aggregate_sha256"] = hashlib.sha256(_canonical(body)).hexdigest()
    path.write_bytes(_canonical(aggregate))
    with pytest.raises(public_artifact.PublicArtifactError, match="summary differs"):
        public_artifact._verified_aggregate(path)


@pytest.mark.parametrize("field", ZERO_SMOKE_ACCOUNTING_FIELDS)
def test_public_artifact_rejects_resealed_nonzero_zero_accounting(
    tmp_path: Path, field: str
) -> None:
    aggregate = _sealed_public_aggregate()
    aggregate["actual_accounting"][field] = 1
    body = {key: value for key, value in aggregate.items() if key != "aggregate_sha256"}
    aggregate["aggregate_sha256"] = hashlib.sha256(_canonical(body)).hexdigest()
    path = tmp_path / "aggregate.json"
    path.write_bytes(_canonical(aggregate))
    with pytest.raises(public_artifact.PublicArtifactError, match="summary differs"):
        public_artifact._verified_aggregate(path)
