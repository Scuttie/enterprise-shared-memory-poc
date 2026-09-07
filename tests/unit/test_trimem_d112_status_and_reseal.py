"""D1.12 source-state authority, immutable D1.11, and `_012` boundary tests."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_d112_reseal as reseal  # noqa: E402


def read(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def commit_file(repository: Path, relative: str, raw: bytes, message: str) -> str:
    target = repository / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    git(repository, "add", "--", relative)
    git(repository, "commit", "-m", message)
    return git(repository, "rev-parse", "HEAD")


def repository_with_source(tmp_path: Path) -> tuple[str, str]:
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "trimem-tests@example.invalid")
    git(tmp_path, "config", "user.name", "TriMem Tests")
    base = commit_file(tmp_path, "README.md", b"base\n", "base")
    source = commit_file(tmp_path, "source.txt", b"source\n", "source")
    return base, source


def test_source_activation_record_has_creation_but_no_execution_authority() -> None:
    assert reseal.current_activation_record() == {
        "actual_execution_authorized": False,
        "benchmark_image_pulls": 0,
        "classification": "PRE_EXEC_012_ZERO_AUTHORITY_ACTIVATION",
        "endpoint": "TRIMEM_V1_READY_FOR_EXEC_012_REQUEST",
        "external_execution_approval_received": False,
        "grader_containers": 0,
        "model_api_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "performance_measured": False,
        "request_creation_authority_received": True,
        "request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012",
        "request_path": (
            "artifacts/trimem_v1/exec_requests/"
            "DEVELOPMENT_TUNING_EXEC_REQUEST_012.json"
        ),
        "request_present_in_activation_source": False,
        "schema": "trimem/development-exec-012-activation/1.0",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def test_historical_d111_is_verified_from_exact_git_blobs() -> None:
    result = reseal.validate_historical_d111()

    assert result == {
        "amendment_sha256": (
            "bd4648ca3bb6542c16d9af9d0bbe96cd64241986212c0b50a52e4fb8a9bf6ca4"
        ),
        "baseline_head": "fa1af529a2af4f8ba606b01410434412881f3d27",
        "freeze_sha256": (
            "e2964255c9c214f29c04bc8df2a5fe275601d43a40f8cad6b1fc926b8cf73739"
        ),
        "implementation_files": 17,
        "inventory_sha256": (
            "383462fce02204fb7ca3507e8102e804f9fa4df135ff5d719a172cf85df8c5c1"
        ),
        "request_011_attempt_one_consumed": True,
        "request_011_model_api_calls": 0,
        "request_011_official_grader_runs": 0,
        "request_011_paid_model_calls": 0,
        "request_011_run_attempt": 1,
        "request_011_run_id": 34_047_573_548,
        "status": "PASS",
    }


def test_optional_012_boundary_accepts_absent_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _base, source = repository_with_source(tmp_path)
    monkeypatch.setattr(reseal, "ROOT", tmp_path)

    assert git(tmp_path, "rev-parse", "HEAD") == source
    assert reseal.validate_optional_exec_012_boundary() is None


def test_optional_012_boundary_rejects_uncommitted_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_with_source(tmp_path)
    target = tmp_path / reseal.REQUEST_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes(b"{}\n")
    monkeypatch.setattr(reseal, "ROOT", tmp_path)

    with pytest.raises(
        reseal.D112ResealError,
        match="uncommitted or non-historical _012 request is forbidden",
    ):
        reseal.validate_optional_exec_012_boundary()


def test_optional_012_boundary_rejects_multifile_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_with_source(tmp_path)
    target = tmp_path / reseal.REQUEST_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes(b"{}\n")
    (tmp_path / "extra.txt").write_bytes(b"extra\n")
    git(tmp_path, "add", "--", reseal.REQUEST_PATH, "extra.txt")
    git(tmp_path, "commit", "-m", "bad sentinel")
    monkeypatch.setattr(reseal, "ROOT", tmp_path)

    with pytest.raises(reseal.D112ResealError, match="sentinel-only"):
        reseal.validate_optional_exec_012_boundary()


def test_optional_012_boundary_delegates_exact_child_to_active_trigger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _base, source = repository_with_source(tmp_path)
    execution = commit_file(
        tmp_path,
        reseal.REQUEST_PATH,
        b'{"request_id":"zero-authority-test"}\n',
        "sentinel",
    )
    calls: list[tuple[Path, str, str | None, bool]] = []

    def validate(
        repository: Path,
        after: str,
        *,
        expected_parent: str | None,
        require_checked_out_head: bool,
    ) -> dict:
        calls.append((repository, after, expected_parent, require_checked_out_head))
        return {"status": "PASS"}

    trigger = SimpleNamespace(
        REQUEST_ID=reseal.REQUEST_ID,
        SENTINEL_PATH=reseal.REQUEST_PATH,
        validate_sentinel_commit=validate,
    )
    monkeypatch.setattr(reseal, "ROOT", tmp_path)
    monkeypatch.setattr(
        reseal.importlib,
        "import_module",
        lambda name: trigger
        if name == "trimem_development_trigger_d112"
        else pytest.fail(f"unexpected import: {name}"),
    )

    assert reseal.validate_optional_exec_012_boundary() == execution
    assert calls == [(tmp_path, execution, source, True)]


def test_changed_path_coverage_rejects_unsealed_source_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, _source = repository_with_source(tmp_path)
    bad = commit_file(tmp_path, "scripts/unsealed.py", b"pass\n", "unsealed")
    monkeypatch.setattr(reseal, "ROOT", tmp_path)
    monkeypatch.setattr(reseal, "BASE_HEAD", base)

    with pytest.raises(reseal.D112ResealError, match="escape the explicit seal"):
        reseal.verify_changed_path_coverage(bad)


def test_trigger_and_reseal_share_exact_d112_contract_constants() -> None:
    import trimem_development_trigger_d112 as trigger

    assert trigger.AMENDMENT_PATH == reseal.AMENDMENT_PATH.relative_to(ROOT).as_posix()
    assert trigger.INVENTORY_PATH == reseal.INVENTORY_PATH.relative_to(ROOT).as_posix()
    assert trigger.AMENDMENT_SCHEMA == reseal.AMENDMENT_SCHEMA
    assert trigger.INVENTORY_SCHEMA == reseal.INVENTORY_SCHEMA
    assert trigger.AMENDMENT_CLASSIFICATION == reseal.CLASSIFICATION
    assert trigger.AMENDMENT_STATUS == reseal.STATUS
    assert trigger.AMENDMENT_ENDPOINT == reseal.ENDPOINT
    assert trigger.SENTINEL_PATH == reseal.REQUEST_PATH
    assert trigger.ALLOWED_ACTIVATION_PATHS == reseal.ALLOWED_CHANGED_PATHS


def test_cross_platform_observer_is_byte_locked_and_bounded() -> None:
    contract = reseal.validate_github_observer_contract()

    assert contract["lock_schema"] == "trimem/gh-cli-lock/1.1"
    assert contract["first_version_line"] == "gh version 2.97.0 (2026-07-31)"
    assert contract["observer_selection_policy"] == (
        "PLATFORM_EXACT_BYTES_AND_VERSION_NO_UNVERIFIED_FALLBACK"
    )
    assert contract["report_line_ending_contract"] == "GIT_ATTRIBUTE_TEXT_EOL_LF"
    assert contract["platforms"] == {
        "linux_amd64": {
            "archive_sha256": (
                "a2c9b8497e1f85b1ad0dfcb78b5a622e098801b8e461e459e88e1ee12f018112"
            ),
            "binary_sha256": (
                "141507c337e8b202ad398550c3b73d72f5af92e86f71665214538a81efd4c409"
            ),
        },
        "windows_amd64": {
            "archive_sha256": (
                "35d7fe05c4dd1411ffda1e73dfc7c6f44b75c936ca51fa6595c657fdc0350cec"
            ),
            "binary_sha256": (
                "e2efa10a5d2ce93cac9bc4b676932b62947c0967c01c8f2c3a9cb4437ad358d3"
            ),
        },
    }
    assert contract["same_verified_transport_for"] == [
        "current_pull_request",
        "current_execution_workflow_run",
        "source_workflow_runs",
        "repository_runners",
    ]
    assert contract["visibility_polling"] == {
        "fail_immediately_for": [
            "malformed_or_contradictory_identity",
            "duplicate_or_rerun_workflow",
            "red_source_gate",
            "missing_or_nonready_runner_set",
        ],
        "interval_seconds": 2,
        "maximum_polls": 16,
        "poll_only": [
            "missing_stale_or_incomplete_current_pr_head",
            "missing_or_incomplete_current_execution_workflow_run",
        ],
        "timeout_disposition": "FAIL_CLOSED_BEFORE_SENTINEL_OR_EXECUTION",
        "timeout_seconds": 30,
    }
    for relative in (
        ".gitattributes",
        "configs/trimem_v1/gh_cli_lock.json",
        "scripts/trimem_install_pinned_gh.py",
        "tests/unit/test_trimem_pinned_gh.py",
    ):
        assert relative in reseal.IMPLEMENTATION_PATHS
        assert reseal.REQUIRED_CHANGED_PATHS[relative] == "M"


def test_activation_report_records_observer_scope_without_execution_claim() -> None:
    report = (ROOT / "reports/TRIMEM_D112_EXEC_012_ACTIVATION.md").read_text(
        encoding="utf-8"
    )

    assert "same verified GitHub CLI" in report
    assert "gh_2.97.0_windows_amd64.zip" in report
    assert "at most 16 observations" in report
    assert "Source-gate and runner-set evidence never poll" in report
    assert "no benchmark image" in report
    assert "not DEV execution approval" in report


def test_d112_artifacts_are_reproducible_and_keep_zero_execution_authority() -> None:
    expected_amendment, expected_inventory = reseal.build_artifacts()
    amendment = read(
        "artifacts/trimem_v1/development_exec_012_activation_amendment.json"
    )
    inventory = read(
        "artifacts/trimem_v1/development_exec_012_activation_inventory.json"
    )

    assert amendment == expected_amendment
    assert inventory == expected_inventory
    assert amendment["github_observer"] == reseal.validate_github_observer_contract()
    assert inventory["github_observer"] == amendment["github_observer"]
    assert amendment["zero_cost_activation_actuals"] == reseal.ZERO_ACTUALS
    assert amendment["authority_boundary"] == {
        "actual_execution_authorized": False,
        "distinct_external_execution_approval_required": True,
        "external_execution_approval_received": False,
        "request_011_attempt_one_consumed": True,
        "request_011_rerun_allowed": False,
        "request_012_created": False,
        "request_012_creation_authorized": True,
        "request_012_execution_authorized": False,
        "sentinel_contains_execution_authority": False,
    }
    assert reseal.validate_optional_exec_012_boundary() is None
