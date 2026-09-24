from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_run_with_resume as resume_driver
import trimem_benchmark_run as benchmark


def _marker(disposition: str, *, status: str) -> bytes:
    return (
        json.dumps(
            {"process_disposition": disposition, "status": status},
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def test_only_the_final_nonempty_stdout_line_can_authorize_resume() -> None:
    stdout = _marker(
        "RESUME_SAFE_DURABLE_SUFFIX", status="FAIL"
    ) + b"process terminated before final disposition\n"
    assert resume_driver._disposition(stdout, 9) == "UNKNOWN_FAILURE"


def test_zero_exit_without_exact_success_marker_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(resume_driver, "ROOT", tmp_path)
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume_driver.subprocess, "run", fake_run)
    assert resume_driver.run_with_one_resume(
        "development", tmp_path / "approval.json"
    ) == 1
    assert len(calls) == 1
    manifest = json.loads(
        (
            tmp_path
            / "artifacts/trimem_v1/benchmark_exec/development/driver-evidence/attempts.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["first_disposition"] == "UNKNOWN_FAILURE"
    assert manifest["resume_started"] is False
    assert manifest["status"] == "FAIL"


def test_second_zero_exit_without_exact_success_marker_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(resume_driver, "ROOT", tmp_path)
    monkeypatch.setattr(
        resume_driver,
        "_durable_resume_disposition",
        lambda _root, **_kwargs: "RESUME_SAFE_CELL_COMMIT_JOURNAL",
    )
    outputs = [
        subprocess.CompletedProcess(
            ["runner"],
            9,
            stdout=_marker("RESUME_SAFE_CELL_COMMIT_JOURNAL", status="FAIL"),
            stderr=b"",
        ),
        subprocess.CompletedProcess(
            ["runner"], 0, stdout=b'{"status":"PASS"}\n', stderr=b""
        ),
    ]

    def fake_run(_argv, **_kwargs):
        return outputs.pop(0)

    monkeypatch.setattr(resume_driver.subprocess, "run", fake_run)
    assert resume_driver.run_with_one_resume(
        "development", tmp_path / "approval.json"
    ) == 1
    manifest = json.loads(
        (
            tmp_path
            / "artifacts/trimem_v1/benchmark_exec/development/driver-evidence/attempts.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["resume_started"] is True
    assert manifest["second_process_exit_code"] == 0
    assert manifest["attempts"][1]["process_disposition"] == "UNKNOWN_FAILURE"
    assert manifest["status"] == "FAIL"


def test_status_must_match_the_exit_code() -> None:
    assert resume_driver._disposition(
        _marker("SUCCESS", status="FAIL"), 0
    ) == "UNKNOWN_FAILURE"
    assert resume_driver._disposition(
        _marker("GLOBAL_GRADER_INFRA_FAILURE", status="PASS"), 9
    ) == "UNKNOWN_FAILURE"


def test_reported_safe_disposition_requires_matching_durable_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(resume_driver, "ROOT", tmp_path)
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(
            argv,
            9,
            stdout=_marker("RESUME_SAFE_CELL_COMMIT_JOURNAL", status="FAIL"),
            stderr=b"",
        )

    monkeypatch.setattr(resume_driver.subprocess, "run", fake_run)
    monkeypatch.setattr(
        resume_driver,
        "_durable_resume_disposition",
        lambda _root, **_kwargs: "UNKNOWN_FAILURE",
    )
    assert resume_driver.run_with_one_resume(
        "development", tmp_path / "approval.json"
    ) == 9
    assert len(calls) == 1
    manifest = json.loads(
        (
            tmp_path
            / "artifacts/trimem_v1/benchmark_exec/development/driver-evidence/attempts.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["first_disposition"] == "GLOBAL_EVIDENCE_FAILURE"
    assert manifest["resume_started"] is False


def test_hard_child_death_closes_started_grader_without_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def short_fixture_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    monkeypatch.setattr(benchmark, "atomic_write", short_fixture_write)
    monkeypatch.setattr(resume_driver, "ROOT", tmp_path)
    execution_root = (
        tmp_path / "artifacts/trimem_v1/benchmark_exec/development"
    )
    journal = benchmark.TerminalInvocationJournal(
        execution_root / "M0/000-target-001/terminal-journal"
    )
    request_sha256 = "a" * 64
    path = journal.begin_grader_request(
        "target-001:" + request_sha256, request_sha256
    )
    journal.transition_grader(
        path,
        expected=("GRADER_NOT_PREPARED",),
        status="GRADER_PREFLIGHT_PASSED",
        values={"loader_preflight_evidence_sha256": "b" * 64},
    )
    journal.transition_grader(
        path,
        expected=("GRADER_PREFLIGHT_PASSED",),
        status="GRADER_REQUEST_RECORDED",
    )
    journal.transition_grader(
        path,
        expected=("GRADER_REQUEST_RECORDED",),
        status="GRADER_PROCESS_STARTED",
    )
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, -9, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume_driver.subprocess, "run", fake_run)
    assert resume_driver.run_with_one_resume(
        "development", tmp_path / "approval.json"
    ) == 1
    assert len(calls) == 1
    row = benchmark.TerminalInvocationJournal._validated_grader_row(path)
    assert row["status"] == "GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START"
    assert (row["official_grader_runs"], row["grader_containers"]) == (1, 1)
    assert row["grader_capacity_disposition"] == "CONSERVATIVELY_CONSUMED"
    manifest = json.loads(
        (
            execution_root / "driver-evidence/attempts.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["first_disposition"] == "GLOBAL_GRADER_INFRA_FAILURE"
    assert manifest["resume_eligible"] is False
    assert manifest["resume_started"] is False
    assert manifest["attempts"][0]["disposition_source"] == (
        "VERIFIED_GRADER_LIFECYCLE_RECONCILIATION"
    )


def test_hard_child_death_closes_retry_marker_without_a_third_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def short_fixture_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    monkeypatch.setattr(benchmark, "atomic_write", short_fixture_write)
    monkeypatch.setattr(resume_driver, "ROOT", tmp_path)
    execution_root = (
        tmp_path / "artifacts/trimem_v1/benchmark_exec/development"
    )
    journal = benchmark.TerminalInvocationJournal(
        execution_root / "M0/000-target-001/terminal-journal"
    )
    request_sha256 = "a" * 64
    path = journal.begin_grader_request(
        "target-001:" + request_sha256, request_sha256
    )
    journal.transition_grader(
        path,
        expected=("GRADER_NOT_PREPARED",),
        status="GRADER_PREFLIGHT_PASSED",
        values={"loader_preflight_evidence_sha256": "b" * 64},
    )
    journal.transition_grader(
        path,
        expected=("GRADER_PREFLIGHT_PASSED",),
        status="GRADER_REQUEST_RECORDED",
    )
    journal.transition_grader(
        path,
        expected=("GRADER_REQUEST_RECORDED",),
        status="GRADER_PROCESS_STARTED",
    )
    attempt1 = {
        "task_id": "target-001",
        "resolved": False,
        "exit_code": 127,
        "stdout": "",
        "stderr": "loader failed",
        "report": {"task_id": "target-001", "resolved": False},
        "grader_id": "official-fixture",
        "container_digest": "fixture@sha256:" + "c" * 64,
        "official": True,
        "wall_time_ms": 1,
        "container_started": False,
        "status": "harness_launch_failed",
    }
    journal.transition_grader(
        path,
        expected=("GRADER_PROCESS_STARTED",),
        status="PRECONTAINER_RETRY_AUTHORIZED",
        values={
            "precontainer_retry_attempt": 1,
            "attempt1_failure": attempt1,
            "attempt1_failure_sha256": benchmark.sha256_bytes(
                benchmark.canonical_bytes(attempt1)
            ),
            "official_grader_runs": 0,
            "grader_containers": 0,
            "grader_capacity_disposition": "NOT_CONSUMED",
        },
    )
    journal.transition_grader(
        path,
        expected=("PRECONTAINER_RETRY_AUTHORIZED",),
        status="GRADER_RETRY_PROCESS_STARTED",
    )
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, -9, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume_driver.subprocess, "run", fake_run)
    assert resume_driver.run_with_one_resume(
        "development", tmp_path / "approval.json"
    ) == 1
    assert len(calls) == 1
    row = benchmark.TerminalInvocationJournal._validated_grader_row(path)
    assert row["status"] == "GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START"
    assert row["attempt1_failure"] == attempt1
    assert (row["official_grader_runs"], row["grader_containers"]) == (1, 1)
    manifest = json.loads(
        (execution_root / "driver-evidence/attempts.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["first_disposition"] == "GLOBAL_GRADER_INFRA_FAILURE"
    assert manifest["resume_started"] is False
    assert manifest["attempts"][0]["reconciled_ambiguous_grader_processes"] == 1


def test_hard_second_child_death_closes_started_grader_without_third_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sole recovery child must receive the same conservative closure."""

    def short_fixture_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    monkeypatch.setattr(benchmark, "atomic_write", short_fixture_write)
    monkeypatch.setattr(resume_driver, "ROOT", tmp_path)
    monkeypatch.setattr(
        resume_driver,
        "_durable_resume_disposition",
        lambda _root, **_kwargs: "RESUME_SAFE_CELL_COMMIT_JOURNAL",
    )
    execution_root = (
        tmp_path / "artifacts/trimem_v1/benchmark_exec/development"
    )
    calls: list[list[str]] = []
    journal_paths: list[Path] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                argv,
                9,
                stdout=_marker(
                    "RESUME_SAFE_CELL_COMMIT_JOURNAL", status="FAIL"
                ),
                stderr=b"",
            )
        journal = benchmark.TerminalInvocationJournal(
            execution_root / "M0/000-target-001/terminal-journal"
        )
        request_sha256 = "a" * 64
        path = journal.begin_grader_request(
            "target-001:" + request_sha256, request_sha256
        )
        journal.transition_grader(
            path,
            expected=("GRADER_NOT_PREPARED",),
            status="GRADER_PREFLIGHT_PASSED",
            values={"loader_preflight_evidence_sha256": "b" * 64},
        )
        journal.transition_grader(
            path,
            expected=("GRADER_PREFLIGHT_PASSED",),
            status="GRADER_REQUEST_RECORDED",
        )
        journal.transition_grader(
            path,
            expected=("GRADER_REQUEST_RECORDED",),
            status="GRADER_PROCESS_STARTED",
        )
        journal_paths.append(path)
        return subprocess.CompletedProcess(
            argv, -9, stdout=b"", stderr=b"killed"
        )

    monkeypatch.setattr(resume_driver.subprocess, "run", fake_run)
    assert resume_driver.run_with_one_resume(
        "development", tmp_path / "approval.json"
    ) == 1
    assert len(calls) == 2
    assert "--resume" in calls[1]
    assert len(journal_paths) == 1
    row = benchmark.TerminalInvocationJournal._validated_grader_row(
        journal_paths[0]
    )
    assert row["status"] == "GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START"
    assert (row["official_grader_runs"], row["grader_containers"]) == (1, 1)
    assert row["grader_capacity_disposition"] == "CONSERVATIVELY_CONSUMED"
    manifest = json.loads(
        (execution_root / "driver-evidence/attempts.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["resume_started"] is True
    assert manifest["second_process_exit_code"] == -9
    assert manifest["attempts"][1]["reported_process_disposition"] == (
        "UNKNOWN_FAILURE"
    )
    assert manifest["attempts"][1]["process_disposition"] == (
        "GLOBAL_GRADER_INFRA_FAILURE"
    )
    assert manifest["attempts"][1]["disposition_source"] == (
        "VERIFIED_GRADER_LIFECYCLE_RECONCILIATION"
    )
    assert manifest["attempts"][1]["reconciled_ambiguous_grader_processes"] == 1
    assert manifest["status"] == "FAIL"
