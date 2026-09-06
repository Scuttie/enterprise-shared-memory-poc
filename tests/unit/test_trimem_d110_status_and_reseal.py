"""D1.10 status split, immutable history, and zero-cost research seal."""
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


def read(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_current_status_uses_exact_split_fields_and_ready_endpoint() -> None:
    readiness = read("artifacts/trimem_v1/readiness_requirements.json")
    status = readiness["current_status"]

    assert "OFFICIAL_GRADER_VIABILITY" not in status
    assert {
        key: status[key] for key in reseal.STATUS_FIELDS
    } == reseal.STATUS_FIELDS
    assert status["CLASSIFICATION"] == reseal.CLASSIFICATION
    assert status["ENDPOINT"] == reseal.ENDPOINT
    assert status["DEV_APPROVAL_ALLOWED"] == "YES"
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


def test_explicit_011_authority_does_not_reuse_final_exec_010_request() -> None:
    authority = read("artifacts/trimem_v1/readiness_requirements.json")[
        "development_authorization_boundary"
    ]
    assert authority["historical_failed_request_id"] == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_010"
    )
    assert authority["historical_failed_request_path"] == reseal.REQUEST_PATH
    assert authority["fresh_execution_request"] == (
        "REQUEST_011_AUTHORIZED_PENDING_EXACT_REMOTE_GATES"
    )
    assert authority["fresh_execution_request_creation_authorized"] is True
    assert authority["recovery_authorization"] == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_011_APPROVED_ONCE"
    )
    assert authority["required_external_authorization"] == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_011_APPROVED_ONCE"
    )
    assert authority["recovery_authorization_received"] is True
    assert authority["future_recovery_authority_received"] is True
    assert authority["recovery_request_id"] == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_011"
    )
    assert authority["recovery_request_path"] == reseal.REQUEST_011_PATH
    assert authority["request_011_allowed_after_exact_remote_gates"] is True
    assert authority["request_011_created"] is False
    assert authority["active_development_approval"] is False
    assert authority["development_execution_authorized"] is False
    assert authority["fresh_dev_execution_approval_required"] is True


def test_exec_001_through_010_are_byte_locked_and_011_is_optional_activation() -> None:
    requests, evidence = reseal.verify_historical_boundaries()
    request_011 = (
        "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_011.json"
    )
    assert requests == reseal.HISTORICAL_REQUEST_SHA256
    assert len(requests) == 10
    assert evidence
    assert request_011 == reseal.REQUEST_011_PATH
    assert request_011 not in requests
    assert request_011 not in reseal.D110_GENERATED_PATHS
    assert request_011 not in reseal.IMPLEMENTATION_PATHS


def test_d19_amendment_and_inventory_remain_immutable_history() -> None:
    for relative in (
        "artifacts/trimem_v1/development_bounded_context_amendment.json",
        "artifacts/trimem_v1/development_bounded_context_inventory.json",
    ):
        assert relative in reseal.PRESERVED_SCIENTIFIC_PATHS
        assert reseal.source_bytes(relative) == reseal.git_blob(
            reseal.EXECUTION_HEAD, relative
        )


def test_d19_trigger_is_immutable_history_and_d110_trigger_is_active() -> None:
    historical = "scripts/trimem_development_trigger_d19.py"
    active = "scripts/trimem_development_trigger_d110.py"

    assert historical in reseal.PRESERVED_SCIENTIFIC_PATHS
    assert historical not in reseal.IMPLEMENTATION_PATHS
    assert reseal.source_bytes(historical) == reseal.git_blob(
        reseal.EXECUTION_HEAD, historical
    )
    assert active in reseal.IMPLEMENTATION_PATHS
    assert active not in reseal.PRESERVED_SCIENTIFIC_PATHS


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


def test_d110_artifacts_are_exactly_reproducible_and_zero_cost() -> None:
    expected_amendment, expected_inventory = reseal.build_artifacts()
    amendment = read(
        "artifacts/trimem_v1/development_grader_launch_stream_commit_amendment.json"
    )
    inventory = read(
        "artifacts/trimem_v1/development_grader_launch_stream_commit_inventory.json"
    )

    assert amendment == expected_amendment
    assert inventory == expected_inventory
    assert amendment["credential_free_correction_actuals"] == {
        "benchmark_image_pulls": 0,
        "model_api_calls": 0,
        "model_generation_calls": 0,
        "official_grader_executions": 0,
        "paid_model_calls": 0,
        "total_usd": 0,
    }
    assert amendment["authority_boundary"]["request_011_created"] is False
    assert amendment["authority_boundary"]["fresh_execution_request"] == (
        "REQUEST_011_AUTHORIZED_PENDING_EXACT_REMOTE_GATES"
    )
    assert amendment["authority_boundary"][
        "fresh_execution_request_creation_authorized"
    ] is True
    assert amendment["authority_boundary"]["recovery_authorization"] == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_011_APPROVED_ONCE"
    )
    assert amendment["authority_boundary"][
        "required_external_authorization"
    ] == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_011_APPROVED_ONCE"
    assert amendment["authority_boundary"][
        "recovery_authorization_received"
    ] is True
    assert amendment["authority_boundary"][
        "future_recovery_authority_received"
    ] is True
    assert amendment["authority_boundary"][
        "request_011_allowed_after_exact_remote_gates"
    ] is True
    assert amendment["authority_boundary"][
        "fresh_dev_execution_approval_required"
    ] is True
    assert amendment["credential_free_bundle_scope"] == (
        "REHASHED_BYTE_STABLE_EXISTING_SOURCE_TO_TARGET_EVIDENCE; "
        "NOT_D1_10_LOADER_OR_CELL_COMMIT_REHEARSAL"
    )


def test_contract_hashes_are_raw_file_identities() -> None:
    amendment = read(
        "artifacts/trimem_v1/development_grader_launch_stream_commit_amendment.json"
    )
    for name, relative in reseal.CONTRACT_PATHS.items():
        assert amendment["contracts"][name] == hashlib.sha256(
            (ROOT / relative).read_bytes()
        ).hexdigest()


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


def test_committed_d110_paths_are_closed_under_the_explicit_seal() -> None:
    changed = reseal.verify_changed_path_coverage()
    allowed = (
        set(reseal.IMPLEMENTATION_PATHS)
        | reseal.D110_GENERATED_PATHS
        | reseal.PRODUCT_COMPATIBILITY_PATHS
    )
    assert changed
    assert set(changed) <= allowed


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
