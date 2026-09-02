from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_multi_swe_probe_request as request  # noqa: E402


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _write(repository: Path, relative: str, raw: bytes) -> None:
    target = repository / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)


def _correction_repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.name", "TriMem Test")
    _git(repository, "config", "user.email", "trimem@example.invalid")
    _git(repository, "config", "commit.gpgsign", "false")
    _git(repository, "config", "core.autocrlf", "false")
    _git(repository, "checkout", "-b", "codex/trimem-coder-v1")

    for relative in request.MATERIAL_PATHS:
        if relative == request.FREEZE_PATH:
            continue
        _write(repository, relative, (ROOT / relative).read_bytes())
    frozen_files = {}
    for relative in request.MATERIAL_PATHS:
        if relative == request.FREEZE_PATH:
            continue
        raw = (repository / relative).read_bytes()
        frozen_files[relative] = {
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    freeze = {
        "files": frozen_files,
        "hash_algorithm": "sha256",
        "path_policy": "unit-test-explicit-allowlist",
        "schema": "trimem/freeze/1.0",
    }
    _write(
        repository,
        request.FREEZE_PATH,
        json.dumps(freeze, indent=2, sort_keys=True).encode("utf-8") + b"\n",
    )
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "frozen correction head")
    return repository, _git(repository, "rev-parse", "HEAD")


def _event(before: str, after: str) -> dict[str, object]:
    """Mirror the Actions push payload without webhook-only file arrays."""

    commit = {
        "id": after,
    }
    return {
        "after": after,
        "before": before,
        "commits": [dict(commit)],
        "created": False,
        "deleted": False,
        "forced": False,
        "head_commit": dict(commit),
        "ref": request.EXPECTED_REF,
    }


def _environment(after: str, *, attempt: str = "1") -> dict[str, str]:
    return {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": request.EXPECTED_REF,
        "GITHUB_REPOSITORY": request.EXPECTED_REPOSITORY,
        "GITHUB_RUN_ATTEMPT": attempt,
        "GITHUB_SHA": after,
    }


def _commit_request(repository: Path) -> tuple[str, str, dict[str, object]]:
    before = _git(repository, "rev-parse", "HEAD")
    report = request.write_request(repository)
    assert report["correction_head"] == before
    _git(repository, "add", request.REQUEST_PATH)
    _git(repository, "commit", "-m", "TriMem one-time Vue image probe request 001")
    after = _git(repository, "rev-parse", "HEAD")
    return before, after, _event(before, after)


def test_request_binds_exact_frozen_vue_target_and_zero_scientific_caps(
    tmp_path: Path,
) -> None:
    repository, correction_head = _correction_repository(tmp_path)
    document = request.build_request_document(
        repository,
        correction_head=correction_head,
    )

    assert document["actual_execution_authorized"] is True
    assert document["correction_head"] == correction_head
    assert document["bindings"]["multi_swe_entrypoint_sha256"] == request._sha256(
        (repository / request.MULTI_SWE_ENTRYPOINT_PATH).read_bytes()
    )
    assert document["bindings"][
        "multi_swe_evaluation_contract_lock_sha256"
    ] == request._sha256(
        (repository / request.MULTI_SWE_EVALUATION_CONTRACT_LOCK_PATH).read_bytes()
    )
    assert document["bindings"]["probe_evidence_sha256"] == request._sha256(
        (repository / request.PROBE_EVIDENCE_PATH).read_bytes()
    )
    assert document["frozen_target"] == {
        "base_commit": "3be4e3cbe34b394096210897c1be8deeb6d748d8",
        "benchmark_id": "multi_swe_bench_mini",
        "expected_digest": (
            "sha256:2883a52a2eb4054e820dc3a88f9fb0b93fbef7ce10801a57e718f1c6d9f8e9c1"
        ),
        "harness_image_tag": "mswebench/vuejs_m_core:pr-8911",
        "image": (
            "mswebench/vuejs_m_core@sha256:"
            "2883a52a2eb4054e820dc3a88f9fb0b93fbef7ce10801a57e718f1c6d9f8e9c1"
        ),
        "instance_id": "vuejs__core-8911",
        "repository": "vuejs/core",
        "target_ids": list(request.TARGET_IDS),
    }
    assert document["hard_caps"] == request.HARD_CAPS
    assert document["hard_caps"]["image_contract_probe_containers"] == 1
    assert all(
        document["hard_caps"][field] == 0
        for field in (
            "api_calls",
            "grader_containers",
            "grader_executions",
            "input_tokens",
            "model_calls",
            "official_tests",
            "output_tokens",
            "paid_model_calls",
            "patch_applications",
            "task_arm_runs",
            "total_usd",
        )
    )
    serialized = json.dumps(document, sort_keys=True)
    assert "patch_contents" not in serialized
    assert "GOLD patch" not in serialized


def test_one_marker_only_push_validates_and_binds_sole_parent(tmp_path: Path) -> None:
    repository, _ = _correction_repository(tmp_path)
    before, after, event = _commit_request(repository)
    event_path = tmp_path / "event.json"
    event_path.write_bytes(request.canonical_bytes(event, trailing_lf=True))

    result = request.validate_branch_trigger(
        repository,
        event_path,
        environ=_environment(after),
    )
    assert result == {
        "api_calls": 0,
        "correction_head": before,
        "decision": request.GATE_EXECUTE,
        "grader_executions": 0,
        "image_contract_probe_containers": 1,
        "model_calls": 0,
        "official_tests": 0,
        "patch_applications": 0,
        "request_id": request.REQUEST_ID,
        "request_sha256": result["request_sha256"],
        "schema": request.GATE_SCHEMA,
        "status": "REQUEST_VALIDATED",
        "trigger_commit": after,
    }
    assert request.SHA256.fullmatch(result["request_sha256"])


def test_ordinary_push_without_marker_touch_is_explicitly_skipped(
    tmp_path: Path,
) -> None:
    repository, _ = _correction_repository(tmp_path)
    before = _git(repository, "rev-parse", "HEAD")
    _write(repository, "ordinary.txt", b"ordinary research update\n")
    _git(repository, "add", "ordinary.txt")
    _git(repository, "commit", "-m", "ordinary push")
    after = _git(repository, "rev-parse", "HEAD")
    event_path = tmp_path / "event.json"
    event_path.write_bytes(request.canonical_bytes(_event(before, after), trailing_lf=True))

    result = request.classify_branch_trigger(
        repository,
        event_path,
        environ=_environment(after),
    )

    assert result == {
        "decision": request.GATE_SKIP,
        "push_before": before,
        "push_head": after,
        "reason": "PROBE_REQUEST_PATH_UNCHANGED",
        "schema": request.GATE_SCHEMA,
        "status": "NOT_REQUESTED",
    }


def test_probe_push_refuses_rerun_attempt_before_docker(tmp_path: Path) -> None:
    repository, _ = _correction_repository(tmp_path)
    _, after, event = _commit_request(repository)
    event_path = tmp_path / "event.json"
    event_path.write_bytes(request.canonical_bytes(event, trailing_lf=True))

    with pytest.raises(request.ProbeRequestError, match="rerun attempt"):
        request.validate_branch_trigger(
            repository,
            event_path,
            environ=_environment(after, attempt="2"),
        )


def test_probe_push_refuses_marker_plus_any_other_change(tmp_path: Path) -> None:
    repository, _ = _correction_repository(tmp_path)
    before = _git(repository, "rev-parse", "HEAD")
    request.write_request(repository)
    _write(repository, "unexpected.txt", b"not allowed\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "invalid mixed probe request")
    after = _git(repository, "rev-parse", "HEAD")
    event = _event(before, after)
    event_path = tmp_path / "event.json"
    event_path.write_bytes(request.canonical_bytes(event, trailing_lf=True))

    with pytest.raises(request.ProbeRequestError, match="add only the request"):
        request.validate_branch_trigger(
            repository,
            event_path,
            environ=_environment(after),
        )


@pytest.mark.parametrize("operation", ["modify", "delete"])
def test_probe_push_refuses_existing_marker_modification_or_deletion(
    tmp_path: Path,
    operation: str,
) -> None:
    repository, _ = _correction_repository(tmp_path)
    _, marker_head, _ = _commit_request(repository)
    marker = repository / request.REQUEST_PATH
    if operation == "modify":
        marker.write_bytes(marker.read_bytes() + b" ")
    else:
        marker.unlink()
    _git(repository, "add", "-A", request.REQUEST_PATH)
    _git(repository, "commit", "-m", f"invalid marker {operation}")
    after = _git(repository, "rev-parse", "HEAD")
    event_path = tmp_path / "event.json"
    event_path.write_bytes(
        request.canonical_bytes(_event(marker_head, after), trailing_lf=True)
    )

    with pytest.raises(request.ProbeRequestError, match="add only the request"):
        request.classify_branch_trigger(
            repository,
            event_path,
            environ=_environment(after),
        )


def test_probe_push_refuses_multicommit_range_containing_marker(tmp_path: Path) -> None:
    repository, _ = _correction_repository(tmp_path)
    before = _git(repository, "rev-parse", "HEAD")
    request.write_request(repository)
    _git(repository, "add", request.REQUEST_PATH)
    _git(repository, "commit", "-m", "marker commit")
    _write(repository, "later.txt", b"second commit\n")
    _git(repository, "add", "later.txt")
    _git(repository, "commit", "-m", "later commit in same push")
    after = _git(repository, "rev-parse", "HEAD")
    event_path = tmp_path / "event.json"
    event_path.write_bytes(request.canonical_bytes(_event(before, after), trailing_lf=True))

    with pytest.raises(request.ProbeRequestError, match="one non-merge child"):
        request.classify_branch_trigger(
            repository,
            event_path,
            environ=_environment(after),
        )


def test_gate_failure_evidence_records_fail_closed_decision(tmp_path: Path) -> None:
    report = request._gate_failure_report(
        request.ProbeRequestError("probe rerun attempt is forbidden")
    )
    report_path = tmp_path / "gate.json"
    github_output = tmp_path / "github-output.txt"

    request.write_gate_evidence(
        report,
        report_path=report_path,
        github_output_path=github_output,
    )

    assert json.loads(report_path.read_bytes()) == report
    assert github_output.read_bytes() == b"decision=FAIL_CLOSED\n"


def test_cli_persists_fail_closed_gate_evidence_on_marker_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _ = _correction_repository(tmp_path)
    before, after, event = _commit_request(repository)
    assert before != after
    event_path = tmp_path / "event.json"
    event_path.write_bytes(request.canonical_bytes(event, trailing_lf=True))
    report_path = tmp_path / "gate.json"
    github_output = tmp_path / "github-output.txt"
    for name, value in _environment(after, attempt="2").items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "trimem_multi_swe_probe_request.py",
            "--repository",
            str(repository),
            "--event-path",
            str(event_path),
            "--gate-report",
            str(report_path),
            "--github-output",
            str(github_output),
        ],
    )

    assert request.main() == 1
    report = json.loads(report_path.read_bytes())
    assert report == {
        "decision": request.GATE_FAIL,
        "reason": "probe rerun attempt is forbidden",
        "schema": request.GATE_SCHEMA,
        "status": request.GATE_FAIL,
    }
    assert github_output.read_bytes() == b"decision=FAIL_CLOSED\n"


def test_request_bytes_are_canonical_and_tamper_fails_closed(tmp_path: Path) -> None:
    repository, correction_head = _correction_repository(tmp_path)
    document = request.build_request_document(repository, correction_head=correction_head)
    raw = request.canonical_bytes(document, trailing_lf=True)
    assert request.validate_request_document(
        repository,
        raw,
        expected_correction_head=correction_head,
    ) == document

    tampered = json.loads(raw)
    tampered["hard_caps"]["api_calls"] = 1
    with pytest.raises(request.ProbeRequestError, match="content differs"):
        request.validate_request_document(
            repository,
            request.canonical_bytes(tampered, trailing_lf=True),
            expected_correction_head=correction_head,
        )

    noncanonical = json.dumps(document, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    with pytest.raises(request.ProbeRequestError, match="canonical LF"):
        request.validate_request_document(
            repository,
            noncanonical,
            expected_correction_head=correction_head,
        )


def test_workflow_uses_registered_push_contract_and_never_dispatch() -> None:
    workflow = (ROOT / request.WORKFLOW_PATH).read_text(encoding="utf-8")
    assert "workflow_dispatch" not in workflow
    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "github.event_name == 'push'" in workflow
    assert "github.event.head_commit.added" not in workflow
    assert "contains(github.event" not in workflow
    assert "scripts/trimem_multi_swe_probe_request.py" in workflow
    assert "--event-path \"$GITHUB_EVENT_PATH\"" in workflow
    assert "--gate-report \"$RUNNER_TEMP/multi_swe_vue_image_probe_gate.json\"" in workflow
    assert "--github-output \"$GITHUB_OUTPUT\"" in workflow
    assert "steps.probe_gate.outputs.decision == 'EXECUTE'" in workflow
    assert "needs.pinned-contract-preexec.result == 'success'" in workflow
    assert workflow.index("Classify checked-out Git push") < workflow.index(
        "Pull, observe, inspect metadata"
    )
    assert "Preserve sanitized probe-gate evidence" in workflow
    assert "id: probe_artifact" in workflow
    assert "Fail closed if an exact request did not reach the image probe" in workflow
    assert 'test "$IMAGE_PROBE_OUTCOME" = "success"' in workflow
    assert 'test "$IMAGE_PROBE_OUTCOME" != "skipped"' not in workflow
    assert "always() && steps.image_probe.outcome != 'skipped'" in workflow
    assert "secrets." not in workflow
    assert "trimem_grader_smoke.py" not in workflow
    assert "persist-credentials: false" in workflow


def test_repository_probe_marker_is_absent_or_one_immutable_valid_addition() -> None:
    history = [
        line
        for line in _git(
            ROOT,
            "log",
            "--format=%H",
            "HEAD",
            "--",
            request.REQUEST_PATH,
        ).splitlines()
        if line
    ]
    marker = ROOT / request.REQUEST_PATH
    if not history:
        assert not marker.exists()
        return

    assert len(history) == 1
    marker_commit = history[0]
    parents = _git(ROOT, "rev-list", "--parents", "-n", "1", marker_commit).split()
    assert len(parents) == 2
    correction_head = parents[1]
    assert _git(
        ROOT,
        "diff-tree",
        "--no-commit-id",
        "--name-status",
        "-r",
        "--no-renames",
        marker_commit,
    ).splitlines() == [f"A\t{request.REQUEST_PATH}"]
    committed = request._commit_bytes(ROOT, marker_commit, request.REQUEST_PATH)
    assert request._commit_bytes(ROOT, "HEAD", request.REQUEST_PATH) == committed
    request.validate_request_document(
        ROOT,
        committed,
        expected_correction_head=correction_head,
    )
