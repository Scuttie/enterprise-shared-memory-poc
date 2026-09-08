"""Immutable D1.10-D1.18 history and the current zero-authority D1.19 seal."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_d110_reseal as reseal  # noqa: E402
import trimem_d111_reseal as d111_reseal  # noqa: E402
import trimem_d112_reseal as d112_reseal  # noqa: E402
import trimem_d113_reseal as d113_reseal  # noqa: E402
import trimem_d114_reseal as d114_reseal  # noqa: E402
import trimem_d115_reseal as current_reseal  # noqa: E402
import trimem_development_trigger_d116 as d116_trigger  # noqa: E402
import trimem_development_trigger_d117 as d117_trigger  # noqa: E402
import trimem_development_trigger_d118 as d118_trigger  # noqa: E402
import trimem_development_trigger_d119 as current_trigger  # noqa: E402


CURRENT_STATUS_FIELDS = {
    "OFFICIAL_GRADER_SEMANTICS_AND_DISCRIMINATION": "ESTABLISHED_BY_P0_1_5",
    "OFFICIAL_GRADER_IMAGE_INTEGRITY": "ESTABLISHED",
    "OFFICIAL_GRADER_DEV_RUNNER_PYTHON_LAUNCH": "NOT_REACHED_ON_EXEC_018",
    "OFFICIAL_GRADER_DEV_RUNNER_CONTAINER_START": "NOT_REACHED_ON_EXEC_018",
    "PERFORMANCE": "NOT_MEASURED",
}


def read(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_current_status_uses_exact_split_fields_and_ready_endpoint() -> None:
    readiness = read("artifacts/trimem_v1/readiness_requirements.json")
    status = readiness["current_status"]

    assert "OFFICIAL_GRADER_VIABILITY" not in status
    assert {
        key: status[key] for key in CURRENT_STATUS_FIELDS
    } == CURRENT_STATUS_FIELDS
    assert status["CLASSIFICATION"] == current_trigger.AMENDMENT_CLASSIFICATION
    assert status["ENDPOINT"] == current_trigger.AMENDMENT_ENDPOINT
    assert status["DEV_APPROVAL_ALLOWED"] == "NO"
    assert status["DEV_EXECUTION_ALLOWED"] == "NO"


def test_exec_010_failure_remains_incomplete_and_pre_result() -> None:
    readiness = read("artifacts/trimem_v1/readiness_requirements.json")
    failure = readiness["current_development_execution_failure"]

    assert failure == reseal.current_failure_record()
    assert failure["endpoint"] == "TRIMEM_V1_DEV_INCOMPLETE"
    assert failure["grader_state"] == "GRADER_INFRA_FAILURE_BEFORE_CONTAINER"
    assert failure["failure_boundary"]["container_started"] is False
    assert failure["failure_boundary"]["official_grader_runs"] == 0
    assert failure["failure_boundary"]["cell_terminal_records"] == 0
    assert failure["failure_boundary"]["task_arm_cursor"] == 0
    assert failure["performance_measured"] is False
    assert failure["pass_at_1"] is None
    assert failure["process_disposition"] == {
        "first_disposition": "GLOBAL_GRADER_INFRA_FAILURE",
        "resume_eligible": False,
        "resume_started": False,
    }


def test_exec_018_is_spent_and_only_019_request_creation_is_authorized() -> None:
    readiness = read("artifacts/trimem_v1/readiness_requirements.json")
    authority = readiness["development_authorization_boundary"]
    assert readiness[
        "historical_development_exec_015_preapproval_cancellation"
    ] == d116_trigger.current_failure_record()
    assert readiness[
        "historical_development_exec_016_checkout_portability_failure"
    ] == d117_trigger.current_failure_record()
    assert readiness[
        "historical_development_exec_017_python_launcher_alias_failure"
    ] == d118_trigger.current_failure_record()
    assert readiness[
        "historical_development_exec_018_approval_secret_bom_failure"
    ] == current_trigger.current_failure_record()
    assert readiness["current_development_activation"] == (
        current_trigger.current_recovery_record()
    )
    exec_017_actuals = readiness[
        "historical_development_exec_017_python_launcher_alias_failure"
    ]["observed_execution_actuals"]
    assert exec_017_actuals == d118_trigger.HISTORICAL_EXECUTION_ACTUALS
    assert exec_017_actuals["exact_model_metadata_requests"] == 1
    assert exec_017_actuals["paid_model_calls"] == 18
    assert exec_017_actuals["scientific_model_calls"] == 17
    assert exec_017_actuals["protocol_canary_generation_calls"] == 1
    assert exec_017_actuals["decomposition_calls"] == 1
    assert exec_017_actuals["solve_calls"] == 16
    assert exec_017_actuals["extraction_calls"] == 0
    assert exec_017_actuals["input_tokens"] == 197_498
    assert exec_017_actuals["output_tokens"] == 5_068
    assert exec_017_actuals["reasoning_tokens"] == 3_157
    assert exec_017_actuals["total_usd"] == "0.170929500000"
    exec_018_actuals = readiness[
        "historical_development_exec_018_approval_secret_bom_failure"
    ]["observed_execution_actuals"]
    assert exec_018_actuals == current_trigger.HISTORICAL_EXECUTION_ACTUALS
    assert all(
        value == 0 or value == "0.000000000000"
        for value in exec_018_actuals.values()
    )
    assert authority["historical_failed_request_id"] == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_018"
    )
    assert authority["historical_failed_request_path"] == (
        current_trigger.PREVIOUS_SENTINEL_PATH
    )
    assert authority["fresh_execution_request"] == (
        "REQUEST_019_CREATION_AUTHORIZED_PENDING_EXACT_REMOTE_GATES_AND_REHEARSAL"
    )
    assert authority["fresh_execution_request_creation_authorized"] is True
    assert authority["recovery_authorization"] == (
        "REQUEST_019_CREATION_AUTHORITY_RECEIVED"
    )
    assert authority["required_external_authorization"] == (
        current_trigger.REQUIRED_EXTERNAL_AUTHORIZATION
    )
    assert authority["recovery_authorization_received"] is True
    assert authority["future_recovery_authority_received"] is True
    assert authority["recovery_request_id"] == (
        current_trigger.REQUEST_ID
    )
    assert authority["recovery_request_path"] == current_trigger.SENTINEL_PATH
    assert authority["request_011_allowed_after_exact_remote_gates"] is False
    assert authority["request_011_attempt_one_consumed"] is True
    assert authority["request_011_attempt_two_allowed"] is False
    assert authority["request_011_rerun_allowed"] is False
    assert authority["request_011_created"] is True
    assert authority["request_012_attempt_one_consumed"] is True
    assert authority["request_012_attempt_two_allowed"] is False
    assert authority["request_012_rerun_allowed"] is False
    assert authority["request_012_created"] is True
    assert authority["request_013_attempt_one_consumed"] is True
    assert authority["request_013_attempt_two_allowed"] is False
    assert authority["request_013_authorized"] is False
    assert authority["request_013_allowed_after_exact_remote_gates"] is False
    assert authority["request_013_created"] is True
    assert authority["request_013_rerun_allowed"] is False
    assert authority["request_014_authorized"] is False
    assert authority["request_014_allowed_after_exact_remote_gates"] is False
    assert authority["request_014_attempt_one_consumed"] is True
    assert authority["request_014_attempt_two_allowed"] is False
    assert authority["request_014_created"] is True
    assert authority["request_014_rerun_allowed"] is False
    assert authority[
        "request_015_allowed_after_exact_remote_gates_and_rehearsal"
    ] is False
    assert authority["request_015_attempt_one_consumed"] is True
    assert authority["request_015_attempt_two_allowed"] is False
    assert authority["request_015_authorized"] is False
    assert authority["request_015_created"] is True
    assert authority["request_015_rerun_allowed"] is False
    assert authority[
        "request_016_allowed_after_exact_remote_gates_and_rehearsal"
    ] is False
    assert authority["request_016_attempt_one_consumed"] is True
    assert authority["request_016_attempt_two_allowed"] is False
    assert authority["request_016_authorized"] is True
    assert authority["request_016_created"] is True
    assert authority["request_016_rerun_allowed"] is False
    assert authority[
        "request_017_allowed_after_exact_remote_gates_and_rehearsal"
    ] is False
    assert authority["request_017_attempt_one_consumed"] is True
    assert authority["request_017_attempt_two_allowed"] is False
    assert authority["request_017_authorized"] is True
    assert authority["request_017_created"] is True
    assert authority["request_017_rerun_allowed"] is False
    assert authority[
        "request_018_allowed_after_exact_remote_gates_and_rehearsal"
    ] is False
    assert authority["request_018_attempt_one_consumed"] is True
    assert authority["request_018_attempt_two_allowed"] is False
    assert authority["request_018_authorized"] is True
    assert authority["request_018_created"] is True
    assert authority["request_018_rerun_allowed"] is False
    assert authority[
        "request_019_allowed_after_exact_remote_gates_and_rehearsal"
    ] is True
    assert authority["request_019_authorized"] is False
    assert authority["request_019_created"] is False
    assert authority["request_019_execution_authorized"] is False
    assert authority["active_development_approval"] is False
    assert authority["development_execution_authorized"] is False
    assert authority["fresh_dev_execution_approval_required"] is True


def test_exec_001_through_012_are_byte_locked_and_013_is_spent() -> None:
    d112_reseal.validate_historical_d111()
    assert d111_reseal.EXECUTION_HEAD == "e54d04b0af9e738d311c389dc89cfd510fd7065b"
    assert d111_reseal.SOURCE_HEAD == "155fe314631ef74828ea98b562036bdb0adca495"
    assert d111_reseal.REQUEST_SHA256 == (
        "75acaaa8f1f2f0dc138530dfc533df440e2c70f4ee885732b8297a8150de2fa0"
    )
    historical_d112 = d113_reseal.validate_historical_d112()
    assert historical_d112["execution_head"] == d113_reseal.D112_EXECUTION_HEAD
    assert historical_d112["run_attempt"] == 1
    assert historical_d112["run_id"] == d113_reseal.D112_RUN_ID
    historical_d113 = d114_reseal.validate_historical_d113()
    assert historical_d113["execution_head"] == d114_reseal.D113_EXECUTION_HEAD
    assert historical_d113["run_attempt"] == d114_reseal.D113_RUN_ATTEMPT
    assert historical_d113["run_id"] == d114_reseal.D113_RUN_ID
    historical_d114 = current_reseal.validate_historical_d114()
    assert historical_d114["execution_head"] == current_reseal.D114_EXECUTION_HEAD
    assert historical_d114["run_attempt"] == current_reseal.D114_RUN_ATTEMPT
    assert historical_d114["run_id"] == current_reseal.D114_RUN_ID
    assert len(reseal.HISTORICAL_REQUEST_SHA256) == 10


def test_d19_amendment_and_inventory_remain_immutable_history() -> None:
    for relative in (
        "artifacts/trimem_v1/development_bounded_context_amendment.json",
        "artifacts/trimem_v1/development_bounded_context_inventory.json",
    ):
        assert relative in reseal.PRESERVED_SCIENTIFIC_PATHS
        assert reseal.source_bytes(relative) == reseal.git_blob(
            reseal.EXECUTION_HEAD, relative
        )


def test_d19_and_d110_triggers_are_immutable_history() -> None:
    historical = "scripts/trimem_development_trigger_d19.py"
    active = "scripts/trimem_development_trigger_d110.py"

    assert historical in reseal.PRESERVED_SCIENTIFIC_PATHS
    assert historical not in reseal.IMPLEMENTATION_PATHS
    assert reseal.source_bytes(historical) == reseal.git_blob(
        reseal.EXECUTION_HEAD, historical
    )
    assert d111_reseal.HISTORICAL_D110_SHA256[active] == hashlib.sha256(
        d111_reseal.git_blob(d111_reseal.EXECUTION_HEAD, active)
    ).hexdigest()
    assert "scripts/trimem_d111_gate_contract.py" in d111_reseal.IMPLEMENTATION_PATHS


def test_tool_environment_lock_changes_only_d110_source_identities() -> None:
    reseal.verify_tool_environment_lock_amendment()
    current = read(reseal.TOOL_ENVIRONMENT_LOCK_PATH)
    historical = json.loads(
        reseal.git_blob(
            reseal.EXECUTION_HEAD,
            reseal.TOOL_ENVIRONMENT_LOCK_PATH,
        ).decode("utf-8")
    )
    assert current["runtime_lock_manifest"] == historical["runtime_lock_manifest"]
    assert current["runtime_lock_content_hash"] == historical[
        "runtime_lock_content_hash"
    ]
    assert current["tool_authority_boundary"] == historical[
        "tool_authority_boundary"
    ]
    changed = {
        relative
        for relative, record in current["source_files"].items()
        if record != historical["source_files"][relative]
    }
    assert changed == reseal.TOOL_ENVIRONMENT_SOURCE_AMENDMENTS


def test_d111_artifacts_are_exactly_reproducible_and_zero_cost() -> None:
    d112_reseal.validate_historical_d111()
    amendment = read(
        "artifacts/trimem_v1/development_activation_lifecycle_amendment.json"
    )
    inventory = read(
        "artifacts/trimem_v1/development_activation_lifecycle_inventory.json"
    )

    assert hashlib.sha256(
        (ROOT / "artifacts/trimem_v1/development_activation_lifecycle_amendment.json").read_bytes()
    ).hexdigest() == d112_reseal.HISTORICAL_D111_SHA256[
        "artifacts/trimem_v1/development_activation_lifecycle_amendment.json"
    ]
    assert hashlib.sha256(
        (ROOT / "artifacts/trimem_v1/development_activation_lifecycle_inventory.json").read_bytes()
    ).hexdigest() == d112_reseal.HISTORICAL_D111_SHA256[
        "artifacts/trimem_v1/development_activation_lifecycle_inventory.json"
    ]
    assert amendment["zero_cost_correction_actuals"] == {
        "benchmark_image_pulls": 0,
        "grader_containers": 0,
        "input_tokens": 0,
        "model_api_calls": 0,
        "model_generation_calls": 0,
        "model_metadata_requests": 0,
        "official_grader_runs": 0,
        "output_tokens": 0,
        "paid_model_calls": 0,
        "task_arm_runs": 0,
        "terminal_cells": 0,
        "total_usd": 0.0,
    }
    assert amendment["authority_boundary"]["request_011_attempt_one_consumed"] is True
    assert amendment["authority_boundary"]["request_012_authorized"] is False
    assert amendment["credential_free_replay"]["historical_source_gates"] == 12


def test_d110_seal_remains_exact_at_spent_execution_head() -> None:
    amendment = read(
        "artifacts/trimem_v1/development_grader_launch_stream_commit_amendment.json"
    )
    assert hashlib.sha256(json.dumps(amendment).encode()).hexdigest()
    for relative, expected in d111_reseal.HISTORICAL_D110_SHA256.items():
        assert hashlib.sha256(
            d111_reseal.git_blob(d111_reseal.EXECUTION_HEAD, relative)
        ).hexdigest() == expected


def test_product_handoff_inventory_is_separate_from_research_freeze() -> None:
    inventory = read(
        "artifacts/trimem_v1/development_grader_launch_stream_commit_inventory.json"
    )["company_handoff_inventory"]
    company = read("COMPANY_HANDOFF_MANIFEST.json")

    assert inventory["manifest_rewritten"] is False
    assert inventory["product_manifest_authority"] == (
        "PRODUCT_HANDOFF_ONLY_NOT_TRIMEM_RESEARCH_STATE"
    )
    assert inventory["product_hash_basis"].startswith("git ls-files -z")
    assert inventory["research_state_authority"] == (
        "artifacts/trimem_v1/freeze.json"
    )
    assert company["manifest_scope"] == inventory["product_manifest_authority"]
    assert "docs/STATUS.yaml" not in reseal.IMPLEMENTATION_PATHS
    assert "docs/STATUS.yaml" in reseal.PRODUCT_COMPATIBILITY_PATHS
    reseal.verify_product_status_compatibility()


def test_d114_integration_paths_are_closed_under_the_explicit_seal() -> None:
    expected = {
        "artifacts/trimem_v1/readiness_requirements.json",
        "scripts/trimem_verify_ready.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
        "tests/unit/test_trimem_d110_status_and_reseal.py",
    }
    assert expected <= d114_reseal.ALLOWED_CHANGED_PATHS
    assert all(d114_reseal.REQUIRED_CHANGED_PATHS[path] == "M" for path in expected)


def test_changed_path_coverage_rejects_an_unsealed_commit_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reseal.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=b"scripts/unsealed_d110_path.py\x00",
            stderr=b"",
        ),
    )
    with pytest.raises(reseal.D110ResealError, match="escape the explicit seal"):
        reseal.verify_changed_path_coverage()


def test_reseal_rejects_intermediate_touch_then_revert_of_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    calls: list[list[str]] = []

    def touched_history(argv, **_kwargs):
        calls.append(list(argv))
        return SimpleNamespace(
            returncode=0,
            stdout=(b"f" * 40) + b"\n",
            stderr=b"",
        )

    monkeypatch.setattr(reseal.subprocess, "run", touched_history)
    with pytest.raises(
        reseal.D110ResealError,
        match="commit history touched an immutable historical path",
    ):
        reseal.verify_immutable_history_untouched(
            (
                reseal.REQUEST_PATH,
                "COMPANY_HANDOFF_MANIFEST.json",
            )
        )
    assert calls
    command = calls[0]
    assert "rev-list" in command
    assert "--full-history" in command
    assert f"{reseal.EXECUTION_HEAD}..HEAD" in command
    assert reseal.REQUEST_PATH in command
    assert "COMPANY_HANDOFF_MANIFEST.json" in command


def test_pr_merge_history_audits_exact_same_repository_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head = "1" * 40
    base = "2" * 40
    merge = "3" * 40
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "repository": {"full_name": "Scuttie/enterprise-shared-memory-poc"},
                "pull_request": {
                    "head": {
                        "sha": head,
                        "repo": {
                            "full_name": "Scuttie/enterprise-shared-memory-poc"
                        },
                    },
                    "base": {"sha": base},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv(
        "GITHUB_REPOSITORY", "Scuttie/enterprise-shared-memory-poc"
    )
    monkeypatch.setattr(
        reseal.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=f"{merge} {base} {head}\n",
            stderr="",
        ),
    )
    assert reseal._immutable_history_tip({"PATH": os.environ.get("PATH", "")}) == head


def test_pr_merge_history_rejects_fork_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "repository": {"full_name": "Scuttie/enterprise-shared-memory-poc"},
                "pull_request": {
                    "head": {
                        "sha": "1" * 40,
                        "repo": {"full_name": "attacker/fork"},
                    },
                    "base": {"sha": "2" * 40},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv(
        "GITHUB_REPOSITORY", "Scuttie/enterprise-shared-memory-poc"
    )
    with pytest.raises(reseal.D110ResealError, match="same-repository"):
        reseal._immutable_history_tip({"PATH": os.environ.get("PATH", "")})


def test_optional_011_boundary_accepts_absent_activation_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reseal, "ROOT", tmp_path)
    monkeypatch.setattr(
        reseal.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=""),
    )

    assert reseal.validate_optional_exec_011_boundary() is None


def test_optional_011_boundary_rejects_uncommitted_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_root = tmp_path
    request = fake_root / (
        "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_011.json"
    )
    request.parent.mkdir(parents=True)
    request.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(reseal, "ROOT", fake_root)
    monkeypatch.setattr(
        reseal.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=""),
    )

    with pytest.raises(
        reseal.D110ResealError,
        match="_011 is not one immutable regular-file addition",
    ):
        reseal.validate_optional_exec_011_boundary()


def test_optional_011_boundary_rejects_multifile_trigger_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = tmp_path / reseal.REQUEST_011_PATH
    request.parent.mkdir(parents=True)
    request.write_text("{}\n", encoding="utf-8")
    execution_head = "1" * 40
    source_head = "2" * 40

    def git_result(argv, **_kwargs):
        command = list(argv)
        if "log" in command and "--format=%H" in command:
            return SimpleNamespace(returncode=0, stdout=f"{execution_head}\n")
        if "rev-list" in command and "--parents" in command:
            return SimpleNamespace(
                returncode=0,
                stdout=f"{execution_head} {source_head}\n",
            )
        if "rev-parse" in command and "HEAD" in command:
            return SimpleNamespace(returncode=0, stdout=f"{execution_head}\n")
        if "diff-tree" in command:
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    f"A\t{reseal.REQUEST_011_PATH}\n"
                    "M\tscripts/trimem_benchmark_run.py\n"
                ),
            )
        raise AssertionError(f"unexpected git command: {command!r}")

    monkeypatch.setattr(reseal, "ROOT", tmp_path)
    monkeypatch.setattr(reseal.subprocess, "run", git_result)

    with pytest.raises(
        reseal.D110ResealError,
        match="_011 trigger commit is not sentinel-only",
    ):
        reseal.validate_optional_exec_011_boundary()
