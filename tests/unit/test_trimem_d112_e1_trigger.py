from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_development_trigger_d112 as trigger  # noqa: E402


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.email", "d112-trigger@example.invalid")
    _git(repository, "config", "user.name", "D1.12 trigger fixture")
    (repository / "base.txt").write_bytes(b"immutable base\n")
    return repository, _commit(repository, "fixture: immutable base")


def _pull_request(head: str) -> dict[str, object]:
    return {
        "base_ref": trigger.EXPECTED_BASE_BRANCH,
        "base_sha": trigger.EXPECTED_BASE_HEAD,
        "draft": True,
        "head_ref": trigger.EXPECTED_BRANCH,
        "head_repository": trigger.EXPECTED_REPOSITORY,
        "head_sha": head,
        "html_url": (
            "https://github.com/Scuttie/enterprise-shared-memory-poc/pull/18"
        ),
        "number": trigger.PULL_REQUEST_NUMBER,
        "state": "open",
    }


def _raw_pull_request(head: str) -> dict[str, object]:
    return {
        "base": {
            "ref": trigger.EXPECTED_BASE_BRANCH,
            "sha": trigger.EXPECTED_BASE_HEAD,
        },
        "draft": True,
        "head": {
            "ref": trigger.EXPECTED_BRANCH,
            "repo": {"full_name": trigger.EXPECTED_REPOSITORY},
            "sha": head,
        },
        "html_url": (
            "https://github.com/Scuttie/enterprise-shared-memory-poc/pull/18"
        ),
        "number": trigger.PULL_REQUEST_NUMBER,
        "state": "open",
    }


def _raw_runs(source_head: str) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {"push": [], "pull_request": []}
    for index, (path, event, _pr_number) in enumerate(
        trigger.REMOTE_GATE_SPECS, start=1
    ):
        run_id = 1_120_000 + index
        result[event].append(
            {
                "conclusion": "success",
                "event": event,
                "head_branch": trigger.EXPECTED_BRANCH,
                "head_sha": source_head,
                "html_url": (
                    "https://github.com/Scuttie/enterprise-shared-memory-poc/"
                    f"actions/runs/{run_id}"
                ),
                "id": run_id,
                "path": path,
                "pull_requests": [
                    {
                        "number": 999,
                        "head": {"sha": "f" * 40},
                    }
                ],
                "run_attempt": 1,
                "status": "completed",
            }
        )
    return result


def _execution_run(head: str, run_id: int = 990_012) -> dict[str, object]:
    return {
        "conclusion": None,
        "event": "push",
        "head_branch": trigger.EXPECTED_BRANCH,
        "head_sha": head,
        "id": run_id,
        "path": trigger.EXPECTED_WORKFLOW_PATH,
        "run_attempt": 1,
        "status": "in_progress",
    }


def _remote_gate_evidence(source_head: str) -> dict[str, object]:
    rows = trigger._select_remote_gate_rows(
        _raw_runs(source_head), source_head=source_head
    )
    return {
        "activation_actuals": dict(trigger.ACTIVATION_ZERO_COUNTERS),
        "all_required_workflows_passed": True,
        "observed_at_utc": _now_utc(),
        "pull_request": _pull_request(source_head),
        "pull_request_number": trigger.PULL_REQUEST_NUMBER,
        "repository": trigger.EXPECTED_REPOSITORY,
        "schema": trigger.REMOTE_GATE_SCHEMA,
        "source_head": source_head,
        "source_ref": trigger.EXPECTED_REF,
        "workflows": rows,
    }


def _runner_rows() -> list[dict[str, object]]:
    return [
        {
            "busy": False,
            "id": 2_120_000 + index,
            "labels": [
                "Linux",
                "X64",
                "self-hosted",
                "trimem-benchmark",
                "trimem-ubuntu-24.04",
            ],
            "name": name,
            "status": "online",
        }
        for index, name in enumerate(trigger.RUNNER_NAMES, start=1)
    ]


def _runner_readiness(source_head: str) -> dict[str, object]:
    runners = _runner_rows()
    return {
        "activation_actuals": dict(trigger.ACTIVATION_ZERO_COUNTERS),
        "host": {
            "architecture": "x86_64",
            "cached_execution_images": 13,
            "container_count": 0,
            "disk_available_bytes": trigger.MINIMUM_RUNNER_DISK_BYTES,
            "docker_server_version": "29.1.3",
            "exact_python_path": f"{trigger.EXACT_PYTHON_ROOT}/bin/python",
            "exact_python_version": "Python 3.11.10",
            "forbidden_secret_names_present": [],
            "fresh_runner_roots": list(trigger.RUNNER_ROOTS),
            "listener_bindings": [
                {"pid": 3_120_000 + index, "root": root}
                for index, root in enumerate(trigger.RUNNER_ROOTS, start=1)
            ],
            "local_runner_bindings": [
                {
                    "agent_id": row["id"],
                    "agent_name": row["name"],
                    "root": trigger.RUNNER_ROOTS[index],
                    "work_folder": "_work",
                }
                for index, row in enumerate(runners)
            ],
            "minimum_disk_available_bytes": trigger.MINIMUM_RUNNER_DISK_BYTES,
            "os_id": "ubuntu",
            "os_version_id": "24.04",
            "stale_runner_roots_absent": list(trigger.STALE_RUNNER_ROOTS),
            "tool_cache_root": trigger.RUNNER_TOOL_CACHE,
            "wsl_distribution": trigger.RUNNER_DISTRIBUTION,
        },
        "observed_at_utc": _now_utc(),
        "repository": trigger.EXPECTED_REPOSITORY,
        "required_labels": list(trigger.REQUIRED_RUNNER_LABELS),
        "runners": runners,
        "schema": trigger.RUNNER_READINESS_SCHEMA,
        "sequential_self_hosted_jobs": [
            "bounded-context-preflight",
            "frozen-serial-phase",
        ],
        "source_head": source_head,
    }


def _event(before: str, after: str) -> dict[str, object]:
    return {
        "after": after,
        "before": before,
        "created": False,
        "deleted": False,
        "forced": False,
        "ref": trigger.EXPECTED_REF,
        "repository": {"full_name": trigger.EXPECTED_REPOSITORY},
    }


def _environment(after: str, run_id: int = 990_012) -> dict[str, str]:
    return {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_JOB": "branch-trigger-preflight",
        "GITHUB_REF": trigger.EXPECTED_REF,
        "GITHUB_REPOSITORY": trigger.EXPECTED_REPOSITORY,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": str(run_id),
        "GITHUB_SHA": after,
        "GITHUB_WORKFLOW_REF": trigger.EXPECTED_WORKFLOW_REF,
        "GITHUB_WORKFLOW_SHA": after,
    }


def _previous_request() -> dict[str, object]:
    return {
        "control_plane": {
            "exact_model_metadata_requests": 1,
            "one_time_workflow_run_attempt": 1,
            "one_time_workflow_runs": 1,
            "precedes_benchmark_image_pull": True,
            "protocol_canary_generation_requests": 1,
            "scientific_generation_request_cap": 1_872,
        },
        "exact_model": {
            "base_url": "https://api.openai.com/v1",
            "model_id": trigger.MODEL_ID,
            "reasoning_effort": trigger.REASONING_EFFORT,
            "same_snapshot_for": [
                "decomposition",
                "solve",
                "experience_extraction",
            ],
        },
        "scientific_workload": {
            "grader_containers": 72,
            "m2_candidate_streams": 4,
            "protocol_canary_generation_calls": 1,
            "scientific_generation_call_cap": 1_872,
            "stream_order": list(trigger.EXPECTED_STREAM_ORDER),
            "target_order": list(trigger.EXPECTED_TARGET_ORDER),
            "task_arm_runs": 72,
        },
    }


def _validated_source() -> dict[str, object]:
    binding_names = set(trigger.SCIENCE_BINDING_PATHS)
    binding_names.update(trigger.ACTIVATION_BINDING_PATHS)
    binding_names.update(trigger.EXECUTION_CONTRACT_PATHS)
    bindings = {
        name: "sha256:" + hashlib.sha256(name.encode("ascii")).hexdigest()
        for name in binding_names
    }
    bindings["freeze_sha256"] = "sha256:" + "a" * 64
    bindings["remote_gate_workflow_blob_sha256"] = {
        path: "sha256:" + hashlib.sha256(path.encode("ascii")).hexdigest()
        for path in trigger.REQUIRED_REMOTE_GATE_WORKFLOWS
    }
    return {
        "activation_changes": {},
        "bindings": bindings,
        "hard_cap": dict(trigger.EXPECTED_DEVELOPMENT_HARD_CAP),
        "previous_request": _previous_request(),
        "target_order": list(trigger.EXPECTED_TARGET_ORDER),
    }


def test_d112_frozen_identity_and_zero_authority_constants() -> None:
    assert trigger.BASELINE_SOURCE_HEAD == (
        "fa1af529a2af4f8ba606b01410434412881f3d27"
    )
    assert trigger.BASELINE_FREEZE_SHA256 == (
        "e2964255c9c214f29c04bc8df2a5fe275601d43a40f8cad6b1fc926b8cf73739"
    )
    assert trigger.REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012"
    assert trigger.REQUIRED_EXTERNAL_AUTHORIZATION == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012_APPROVED_ONCE"
    )
    assert trigger.SENTINEL_PATH.endswith("EXEC_REQUEST_012.json")
    assert trigger.RUNNER_NAMES == (
        "trimem-d112-exec",
        "trimem-d112-preflight",
    )
    assert trigger.REQUIRED_RUNNER_LABELS == (
        "self-hosted",
        "linux",
        "x64",
        "trimem-ubuntu-24.04",
        "trimem-benchmark",
    )
    assert trigger.REQUIRED_ACTIVATION_CHANGES[".gitattributes"] == "M"
    assert trigger.REQUIRED_ACTIVATION_CHANGES[trigger.GH_CLI_LOCK_PATH] == "M"
    assert trigger.REQUIRED_ACTIVATION_CHANGES[
        "scripts/trimem_install_pinned_gh.py"
    ] == "M"
    assert trigger.REQUIRED_ACTIVATION_CHANGES[
        "tests/unit/test_trimem_pinned_gh.py"
    ] == "M"
    assert trigger.ACTIVATION_BINDING_PATHS["gitattributes_sha256"] == (
        ".gitattributes"
    )
    assert trigger.ACTIVATION_BINDING_PATHS["gh_cli_lock_sha256"] == (
        trigger.GH_CLI_LOCK_PATH
    )
    assert trigger.ACTIVATION_BINDING_PATHS[
        "gh_observer_verifier_sha256"
    ] == "scripts/trimem_install_pinned_gh.py"
    assert trigger.ACTIVATION_BINDING_PATHS[
        "gh_observer_verifier_test_sha256"
    ] == "tests/unit/test_trimem_pinned_gh.py"


def test_d112_cli_imports_sibling_lock_reader_under_isolated_python() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "scripts" / "trimem_development_trigger_d112.py"),
            "--help",
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    assert "ModuleNotFoundError" not in completed.stderr


def test_d112_windows_observer_is_byte_verified_before_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    windows_binary = (tmp_path / "gh.exe").resolve()
    lock = {"schema": "trimem/gh-cli-lock/1.1"}
    safe_environment = {"PATH": "verified-observer-only"}
    calls: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        trigger.shutil, "which", lambda name: str(windows_binary) if name == "gh" else None
    )
    monkeypatch.setattr(trigger, "load_gh_cli_lock", lambda path: lock)

    def verify_observer(
        selected_lock: object, binary: Path
    ) -> dict[str, object]:
        calls.append((selected_lock, binary))
        return {
            "first_version_line": "gh version 2.97.0 (2026-07-31)",
            "observer_platform": "windows_amd64",
            "status": "PASS",
        }

    monkeypatch.setattr(trigger, "verify_observer_gh", verify_observer)
    monkeypatch.setattr(
        trigger, "_safe_process_environment", lambda: safe_environment
    )

    assert trigger._pinned_gh_context() == (
        str(windows_binary),
        safe_environment,
    )
    assert calls == [(lock, windows_binary)]


def test_d112_runner_api_uses_the_same_byte_verified_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    safe_environment = {"PATH": "verified-observer-only"}
    expected = _runner_rows()
    response_rows = [
        {
            **row,
            "labels": [{"name": label} for label in row["labels"]],
        }
        for row in expected
    ]
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        trigger,
        "_pinned_gh_context",
        lambda: ("C:\\locked\\gh.exe", safe_environment),
    )

    def run_command(
        argv: object,
        *,
        safe_environment: object,
        label: str,
        timeout: int = 60,
    ) -> bytes:
        calls.append((tuple(argv), safe_environment, label, timeout))  # type: ignore[arg-type]
        return trigger.canonical_bytes(
            {"runners": response_rows, "total_count": len(response_rows)}
        )

    monkeypatch.setattr(trigger, "_run_readiness_command", run_command)

    assert trigger.collect_remote_runner_rows() == expected
    assert len(calls) == 1
    argv, observed_environment, label, timeout = calls[0]
    assert argv[0] == "C:\\locked\\gh.exe"  # type: ignore[index]
    assert observed_environment is safe_environment
    assert label == "GitHub repository runners"
    assert timeout == 60


def test_d112_workflow_locks_job_placement_order_and_secret_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = (ROOT / trigger.EXPECTED_WORKFLOW_PATH).read_bytes()
    monkeypatch.setattr(
        trigger,
        "commit_bytes",
        lambda _repository, _source, path: workflow
        if path == trigger.EXPECTED_WORKFLOW_PATH
        else pytest.fail(f"unexpected path: {path}"),
    )
    trigger._validate_d112_workflow(ROOT, "a" * 40)

    exposed = workflow.replace(
        b"  bounded-context-preflight:\n",
        b"  bounded-context-preflight:\n    env:\n      LEAK: ${{ secrets.OPENAI_API_KEY }}\n",
        1,
    )
    monkeypatch.setattr(trigger, "commit_bytes", lambda *_args: exposed)
    with pytest.raises(trigger.DevelopmentTriggerError, match="protected-environment"):
        trigger._validate_d112_workflow(ROOT, "a" * 40)


@pytest.mark.parametrize(
    "raw",
    [
        b"\xef\xbb\xbf{}",
        b"\xff{}",
        b'{"duplicate":1,"duplicate":2}',
        b'{"value":NaN}',
    ],
)
def test_d112_contract_json_is_strict(raw: bytes) -> None:
    with pytest.raises(trigger.DevelopmentTriggerError, match="invalid|duplicate"):
        trigger.strict_json(raw)


def test_d112_gate_selection_ignores_mutable_nested_pull_requests() -> None:
    source_head = "a" * 40
    runs = _raw_runs(source_head)
    selected = trigger._select_remote_gate_rows(runs, source_head=source_head)

    without_nested = deepcopy(runs)
    for rows in without_nested.values():
        for row in rows:
            row.pop("pull_requests", None)
    with_arbitrary_nested = deepcopy(runs)
    for rows in with_arbitrary_nested.values():
        for row in rows:
            row["pull_requests"] = {"mutable": [None, "anything", 7]}

    assert trigger._select_remote_gate_rows(
        without_nested, source_head=source_head
    ) == selected
    assert trigger._select_remote_gate_rows(
        with_arbitrary_nested, source_head=source_head
    ) == selected
    assert len(selected) == 12


def test_d112_gate_selection_rejects_missing_and_duplicate_top_level_identity() -> None:
    source_head = "a" * 40
    missing = _raw_runs(source_head)
    missing["pull_request"].pop()
    with pytest.raises(trigger.DevelopmentTriggerError, match="exactly one"):
        trigger._select_remote_gate_rows(missing, source_head=source_head)

    duplicate = _raw_runs(source_head)
    duplicate["push"].append(deepcopy(duplicate["push"][0]))
    with pytest.raises(trigger.DevelopmentTriggerError, match="exactly one"):
        trigger._select_remote_gate_rows(duplicate, source_head=source_head)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda rows: rows[0].__setitem__("run_attempt", 2), "rerun"),
        (lambda rows: rows[0].__setitem__("status", "in_progress"), "red"),
        (lambda rows: rows[0].__setitem__("conclusion", "failure"), "red"),
        (lambda rows: rows[1].__setitem__("run_id", rows[0]["run_id"]), "duplicated"),
    ],
)
def test_d112_gate_evidence_rejects_rerun_red_or_duplicate(
    mutation: object, message: str
) -> None:
    source_head = "a" * 40
    evidence = _remote_gate_evidence(source_head)
    rows = evidence["workflows"]
    assert isinstance(rows, list)
    mutation(rows)  # type: ignore[operator]
    if message == "duplicated":
        rows[1]["html_url"] = rows[0]["html_url"]

    with pytest.raises(trigger.DevelopmentTriggerError, match=message):
        trigger._validate_remote_gate_evidence(evidence, source_head=source_head)


def test_d112_current_pr_is_validated_separately_from_historical_runs() -> None:
    source_head = "a" * 40
    evidence = _remote_gate_evidence(source_head)
    pull = evidence["pull_request"]
    assert isinstance(pull, dict)
    pull["head_sha"] = "b" * 40

    with pytest.raises(trigger.DevelopmentTriggerError, match="PR #18"):
        trigger._validate_remote_gate_evidence(evidence, source_head=source_head)


def test_d112_current_pr_visibility_polls_only_missing_or_stale_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_head = "b" * 40
    responses = [
        {},
        _raw_pull_request("a" * 40),
        _raw_pull_request(expected_head),
    ]
    sleeps: list[float] = []

    def run_command(*_args: object, **_kwargs: object) -> bytes:
        return trigger.canonical_bytes(responses.pop(0))

    monkeypatch.setattr(trigger, "_run_readiness_command", run_command)
    assert trigger._collect_current_pull_request(
        "verified-gh",
        {"PATH": "verified"},
        expected_head=expected_head,
        _sleep=sleeps.append,
    ) == _pull_request(expected_head)
    assert responses == []
    assert sleeps == [
        trigger.REMOTE_VISIBILITY_POLL_INTERVAL_SECONDS,
        trigger.REMOTE_VISIBILITY_POLL_INTERVAL_SECONDS,
    ]
    assert sum(sleeps) <= trigger.REMOTE_VISIBILITY_TIMEOUT_SECONDS


@pytest.mark.parametrize("malformed", ["wrong-draft", "malformed-head"])
def test_d112_current_pr_deterministic_errors_do_not_poll(
    monkeypatch: pytest.MonkeyPatch, malformed: str
) -> None:
    expected_head = "b" * 40
    response = _raw_pull_request(expected_head)
    if malformed == "wrong-draft":
        response["draft"] = False
    else:
        response["head"] = "not-an-object"
    sleeps: list[float] = []
    monkeypatch.setattr(
        trigger,
        "_run_readiness_command",
        lambda *_args, **_kwargs: trigger.canonical_bytes(response),
    )

    with pytest.raises(
        trigger.DevelopmentTriggerError,
        match="OPEN/DRAFT|malformed",
    ):
        trigger._collect_current_pull_request(
            "verified-gh",
            {"PATH": "verified"},
            expected_head=expected_head,
            _sleep=sleeps.append,
        )
    assert sleeps == []


def test_d112_current_pr_visibility_timeout_is_bounded_to_30_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations: list[bool] = []
    sleeps: list[float] = []

    def missing_response(*_args: object, **_kwargs: object) -> bytes:
        observations.append(True)
        return b"{}"

    monkeypatch.setattr(trigger, "_run_readiness_command", missing_response)
    with pytest.raises(trigger.DevelopmentTriggerError, match="30 seconds"):
        trigger._collect_current_pull_request(
            "verified-gh",
            {"PATH": "verified"},
            expected_head="b" * 40,
            _sleep=sleeps.append,
        )
    assert len(observations) == trigger.REMOTE_VISIBILITY_MAX_POLLS
    assert len(sleeps) == trigger.REMOTE_VISIBILITY_MAX_POLLS - 1
    assert sum(sleeps) == trigger.REMOTE_VISIBILITY_TIMEOUT_SECONDS


def test_d112_branch_trigger_binds_source_execution_pr_and_runner_separately(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before, after = "a" * 40, "b" * 40
    gates = _remote_gate_evidence(before)
    readiness = _runner_readiness(before)
    event_path = tmp_path / "event.json"
    event_path.write_bytes(trigger.canonical_bytes(_event(before, after)))
    calls: list[tuple[object, ...]] = []

    def validate_sentinel(
        repository: Path,
        selected: str,
        *,
        expected_parent: str,
        require_checked_out_head: bool,
    ) -> dict[str, object]:
        calls.append(
            (
                "sentinel",
                repository,
                selected,
                expected_parent,
                require_checked_out_head,
            )
        )
        return {
            "remote_gate_evidence": gates,
            "runner_readiness": readiness,
            "source_head": expected_parent,
            "trigger_commit": selected,
        }

    monkeypatch.setattr(
        trigger,
        "validate_sentinel_commit",
        validate_sentinel,
    )

    def validate_execution_run(
        selected: str, environment: dict[str, str]
    ) -> dict[str, object]:
        calls.append(("execution", selected, environment["GITHUB_RUN_ID"]))
        return {
            "event": "push",
            "head_sha": selected,
            "run_attempt": 1,
            "run_id": int(environment["GITHUB_RUN_ID"]),
            "workflow_path": trigger.EXPECTED_WORKFLOW_PATH,
        }

    monkeypatch.setattr(
        trigger,
        "_validate_unique_execution_run",
        validate_execution_run,
    )
    monkeypatch.setattr(trigger, "_pinned_gh_context", lambda: ("pinned-gh", {}))

    def current_pull_request(
        gh: str, environment: dict[str, str], *, expected_head: str
    ) -> dict[str, object]:
        calls.append(("current-pr", gh, environment, expected_head))
        return _pull_request(expected_head)

    monkeypatch.setattr(
        trigger,
        "_collect_current_pull_request",
        current_pull_request,
    )

    def remote_gates(
        gh: str, environment: dict[str, str], *, source_head: str
    ) -> object:
        calls.append(("source-gates", gh, environment, source_head))
        return gates["workflows"]

    monkeypatch.setattr(
        trigger,
        "_collect_remote_gate_rows",
        remote_gates,
    )
    def remote_runners(
        gh: str, environment: dict[str, str]
    ) -> list[dict[str, object]]:
        calls.append(("runners", gh, environment))
        return deepcopy(readiness["runners"])  # type: ignore[return-value]

    monkeypatch.setattr(trigger, "_collect_remote_runner_rows", remote_runners)

    result = trigger.validate_branch_trigger(
        ROOT, event_path, environ=_environment(after)
    )
    assert result["source_head"] == before
    assert result["trigger_commit"] == after
    assert result["execution_run"]["head_sha"] == after
    assert result["activation_actuals"] == trigger.ACTIVATION_ZERO_COUNTERS
    assert calls == [
        ("execution", after, "990012"),
        ("sentinel", ROOT, after, before, True),
        ("current-pr", "pinned-gh", {}, after),
        ("source-gates", "pinned-gh", {}, before),
        ("runners", "pinned-gh", {}),
    ]


def test_d112_branch_trigger_rejects_secret_or_second_attempt_before_git(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before, after = "a" * 40, "b" * 40
    event_path = tmp_path / "event.json"
    event_path.write_bytes(trigger.canonical_bytes(_event(before, after)))
    monkeypatch.setattr(trigger, "validate_sentinel_commit", pytest.fail)
    monkeypatch.setattr(trigger, "_validate_unique_execution_run", pytest.fail)

    second_attempt = {**_environment(after), "GITHUB_RUN_ATTEMPT": "2"}
    with pytest.raises(trigger.DevelopmentTriggerError, match="attempt"):
        trigger.validate_branch_trigger(ROOT, event_path, environ=second_attempt)

    wrong_job = {**_environment(after), "GITHUB_JOB": "bounded-context-preflight"}
    with pytest.raises(trigger.DevelopmentTriggerError, match="branch-trigger-preflight"):
        trigger.validate_branch_trigger(ROOT, event_path, environ=wrong_job)

    with_secret = {**_environment(after), "OPENAI_API_KEY": "must-not-be-visible"}
    with pytest.raises(trigger.DevelopmentTriggerError, match="protected benchmark"):
        trigger.validate_branch_trigger(ROOT, event_path, environ=with_secret)


def test_d112_branch_trigger_rejects_stale_embedded_runner_before_live_gates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before, after = "a" * 40, "b" * 40
    readiness = _runner_readiness(before)
    readiness["observed_at_utc"] = "2000-01-01T00:00:00.000Z"
    event_path = tmp_path / "event.json"
    event_path.write_bytes(trigger.canonical_bytes(_event(before, after)))
    monkeypatch.setattr(
        trigger,
        "_validate_unique_execution_run",
        lambda *_args, **_kwargs: {"run_id": 990_012},
    )
    monkeypatch.setattr(
        trigger,
        "validate_sentinel_commit",
        lambda *_args, **_kwargs: {
            "remote_gate_evidence": _remote_gate_evidence(before),
            "runner_readiness": readiness,
        },
    )
    monkeypatch.setattr(trigger, "_pinned_gh_context", pytest.fail)

    with pytest.raises(trigger.DevelopmentTriggerError, match="stale"):
        trigger.validate_branch_trigger(ROOT, event_path, environ=_environment(after))


def test_d112_execution_run_is_unique_and_attempt_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head, run_id = "b" * 40, 990_012
    run = _execution_run(head, run_id)
    monkeypatch.setattr(trigger, "_pinned_gh_context", lambda: ("pinned-gh", {}))
    monkeypatch.setattr(
        trigger, "_query_github_runs", lambda *_args, **_kwargs: [run]
    )
    assert trigger._validate_unique_execution_run(
        head, {"GITHUB_RUN_ID": str(run_id)}
    )["run_attempt"] == 1

    monkeypatch.setattr(
        trigger,
        "_query_github_runs",
        lambda *_args, **_kwargs: [run, deepcopy(run)],
    )
    with pytest.raises(trigger.DevelopmentTriggerError, match="exactly one"):
        trigger._validate_unique_execution_run(
            head, {"GITHUB_RUN_ID": str(run_id)}
        )


def test_d112_execution_visibility_polls_missing_and_incomplete_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head, run_id = "b" * 40, 990_012
    complete = _execution_run(head, run_id)
    incomplete = deepcopy(complete)
    del incomplete["status"]
    del incomplete["conclusion"]
    responses = [[], [incomplete], [complete]]
    sleeps: list[float] = []
    calls: list[tuple[object, ...]] = []
    safe_environment = {"PATH": "verified"}
    monkeypatch.setattr(
        trigger,
        "_pinned_gh_context",
        lambda: ("C:\\locked\\gh.exe", safe_environment),
    )

    def query(
        gh: str,
        source_head: str,
        event: str,
        environment: object,
    ) -> list[dict[str, object]]:
        calls.append((gh, source_head, event, environment))
        return responses.pop(0)

    monkeypatch.setattr(trigger, "_query_github_runs", query)
    result = trigger._validate_unique_execution_run(
        head,
        {"GITHUB_RUN_ID": str(run_id)},
        _sleep=sleeps.append,
    )
    assert result["run_id"] == run_id
    assert responses == []
    assert calls == [
        ("C:\\locked\\gh.exe", head, "push", safe_environment),
        ("C:\\locked\\gh.exe", head, "push", safe_environment),
        ("C:\\locked\\gh.exe", head, "push", safe_environment),
    ]
    assert sleeps == [
        trigger.REMOTE_VISIBILITY_POLL_INTERVAL_SECONDS,
        trigger.REMOTE_VISIBILITY_POLL_INTERVAL_SECONDS,
    ]
    assert sum(sleeps) <= trigger.REMOTE_VISIBILITY_TIMEOUT_SECONDS


@pytest.mark.parametrize("failure", ["duplicate", "red", "rerun"])
def test_d112_execution_deterministic_errors_do_not_poll(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    head, run_id = "b" * 40, 990_012
    run = _execution_run(head, run_id)
    if failure == "duplicate":
        rows = [run, deepcopy(run)]
        expected_message = "exactly one"
    elif failure == "red":
        run["status"] = "completed"
        run["conclusion"] = "failure"
        rows = [run]
        expected_message = "identity differs"
    else:
        run["run_attempt"] = 2
        rows = [run]
        expected_message = "identity differs"
    sleeps: list[float] = []
    monkeypatch.setattr(trigger, "_pinned_gh_context", lambda: ("verified-gh", {}))
    monkeypatch.setattr(
        trigger, "_query_github_runs", lambda *_args, **_kwargs: rows
    )

    with pytest.raises(trigger.DevelopmentTriggerError, match=expected_message):
        trigger._validate_unique_execution_run(
            head,
            {"GITHUB_RUN_ID": str(run_id)},
            _sleep=sleeps.append,
        )
    assert sleeps == []


def test_d112_runner_readiness_requires_exact_fresh_identity() -> None:
    source_head = "a" * 40
    readiness = _runner_readiness(source_head)
    assert trigger._validate_runner_readiness(
        readiness, source_head=source_head
    ) == readiness

    wrong_label = deepcopy(readiness)
    wrong_label["runners"][0]["labels"][-1] = "ubuntu-24.04"  # type: ignore[index]
    with pytest.raises(trigger.DevelopmentTriggerError, match="registration row"):
        trigger._validate_runner_readiness(wrong_label, source_head=source_head)

    stale_name = deepcopy(readiness)
    stale_name["runners"][0]["name"] = "trimem-d110-exec"  # type: ignore[index]
    with pytest.raises(trigger.DevelopmentTriggerError, match="registration set"):
        trigger._validate_runner_readiness(stale_name, source_head=source_head)


def test_d112_request_preserves_science_and_records_zero_call_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_head = "a" * 40
    validated = _validated_source()
    monkeypatch.setattr(trigger, "_validate_source", lambda *_args: validated)
    request = trigger.build_request(
        tmp_path,
        source_head=source_head,
        remote_gate_evidence=_remote_gate_evidence(source_head),
        runner_readiness=_runner_readiness(source_head),
    )

    previous = validated["previous_request"]
    assert request["exact_model"] == previous["exact_model"]  # type: ignore[index]
    assert request["scientific_workload"] == previous["scientific_workload"]  # type: ignore[index]
    assert request["hard_caps"] == trigger.EXPECTED_DEVELOPMENT_HARD_CAP
    assert request["actual_execution_authorized"] is False
    assert request["external_execution_approval_received"] is False
    assert request["request_creation_authority_received"] is True
    assert request["requires_external_approval"] is True
    assert request["required_external_authorization"] == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012_APPROVED_ONCE"
    )
    assert request["recovery_provenance"]["model_api_calls"] == 0
    assert request["recovery_provenance"]["grader_containers"] == 0
    assert request["recovery_provenance"]["total_usd"] == 0.0
    assert request["pre_execution_actuals"]["paid_model_calls"] == 0


def test_d112_request_validation_requires_canonical_utf8_plus_one_lf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_head = "a" * 40
    validated = _validated_source()
    monkeypatch.setattr(trigger, "_validate_source", lambda *_args: validated)
    request = trigger.build_request(
        tmp_path,
        source_head=source_head,
        remote_gate_evidence=_remote_gate_evidence(source_head),
        runner_readiness=_runner_readiness(source_head),
    )
    raw = trigger.canonical_bytes(request, trailing_lf=True)
    assert trigger.validate_request(tmp_path, raw, source_head=source_head) == request

    with pytest.raises(trigger.DevelopmentTriggerError, match="canonical"):
        trigger.validate_request(tmp_path, raw[:-1], source_head=source_head)


def test_d112_sentinel_accepts_exact_single_parent_regular_addition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, source = _repository(tmp_path)
    sentinel = repository / trigger.SENTINEL_PATH
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b'{"zero_authority":true}\n')
    execution = _commit(repository, "control: add D1.12 sentinel only")
    monkeypatch.setattr(
        trigger,
        "validate_request",
        lambda _repo, raw, *, source_head: {
            "raw": raw,
            "source_head": source_head,
        },
    )

    validated = trigger.validate_sentinel_commit(
        repository, execution, expected_parent=source
    )
    assert validated == {
        "raw": b'{"zero_authority":true}\n',
        "source_head": source,
    }


@pytest.mark.parametrize("invalid_kind", ["extra", "executable", "history"])
def test_d112_sentinel_rejects_nonexclusive_mode_or_prior_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invalid_kind: str
) -> None:
    repository, source = _repository(tmp_path)
    sentinel = repository / trigger.SENTINEL_PATH
    sentinel.parent.mkdir(parents=True)
    if invalid_kind == "history":
        sentinel.write_bytes(b'{"old":true}\n')
        _commit(repository, "fixture: create prior sentinel")
        sentinel.unlink()
        source = _commit(repository, "fixture: remove prior sentinel")
    sentinel.write_bytes(b'{"zero_authority":true}\n')
    if invalid_kind == "extra":
        (repository / "unexpected.txt").write_bytes(b"unexpected\n")
    if invalid_kind == "executable":
        _git(repository, "add", "--chmod=+x", "--", trigger.SENTINEL_PATH)
        _git(repository, "commit", "-m", "control: invalid executable sentinel")
        execution = _git(repository, "rev-parse", "HEAD")
    else:
        execution = _commit(repository, "control: invalid sentinel")
    monkeypatch.setattr(trigger, "validate_request", pytest.fail)

    with pytest.raises(
        trigger.DevelopmentTriggerError,
        match="exclusive|100644|already exists",
    ):
        trigger.validate_sentinel_commit(
            repository, execution, expected_parent=source
        )


def test_d112_source_diff_is_strict_descendant_and_explicit_allowlist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, baseline = _repository(tmp_path)
    monkeypatch.setattr(trigger, "STARTING_SOURCE_HEAD", baseline)
    monkeypatch.setattr(trigger, "ALLOWED_ACTIVATION_PATHS", frozenset({"allowed.txt"}))
    monkeypatch.setattr(
        trigger, "REQUIRED_ACTIVATION_CHANGES", {"allowed.txt": "A"}
    )
    (repository / "allowed.txt").write_bytes(b"D1.12 control only\n")
    source = _commit(repository, "control: allowed D1.12 source")
    assert trigger._validate_d112_activation_diff(repository, source) == {
        "allowed.txt": "A"
    }

    (repository / "forbidden.txt").write_bytes(b"scientific drift\n")
    forbidden = _commit(repository, "control: forbidden D1.12 source")
    with pytest.raises(trigger.DevelopmentTriggerError, match="forbidden path"):
        trigger._validate_d112_activation_diff(repository, forbidden)


def test_d112_source_requires_empty_sentinel_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, _base = _repository(tmp_path)
    previous = {
        "request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_011",
        "request_path": "previous.json",
        "request_sha256": "sha256:" + trigger.PREVIOUS_REQUEST_PAYLOAD_SHA256,
        "schema": "trimem/development-tuning-branch-trigger/1.10",
        "source_head": trigger.PREVIOUS_SOURCE_HEAD,
    }
    previous_raw = trigger.canonical_bytes(previous, trailing_lf=True)
    previous_path = repository / "previous.json"
    previous_path.write_bytes(previous_raw)
    previous_execution = _commit(repository, "fixture: immutable _011")
    (repository / "source.txt").write_bytes(b"activation source\n")
    source = _commit(repository, "fixture: D1.12 source")
    monkeypatch.setattr(trigger, "PREVIOUS_EXECUTION_HEAD", previous_execution)
    monkeypatch.setattr(trigger, "PREVIOUS_SENTINEL_PATH", "previous.json")
    monkeypatch.setattr(
        trigger, "PREVIOUS_SENTINEL_SHA256", hashlib.sha256(previous_raw).hexdigest()
    )
    assert trigger._validate_historical_011(repository, source) == previous

    sentinel = repository / trigger.SENTINEL_PATH
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b"{}\n")
    with_history = _commit(repository, "fixture: premature _012")
    with pytest.raises(trigger.DevelopmentTriggerError, match="source history"):
        trigger._validate_historical_011(repository, with_history)


def test_d112_windows_writer_shares_one_verified_observer_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, source_head = _repository(tmp_path)
    _git(repository, "branch", "-M", trigger.EXPECTED_BRANCH)
    observer_environment = {"PATH": "verified-observer-only"}
    observer_context = ("C:\\locked\\gh.exe", observer_environment)
    calls: list[tuple[object, ...]] = []
    gates = _remote_gate_evidence(source_head)
    readiness = _runner_readiness(source_head)

    monkeypatch.setattr(
        trigger, "_validate_secret_free_branch_environment", lambda _env: None
    )
    monkeypatch.setattr(trigger, "_validate_source", lambda *_args: {})
    monkeypatch.setattr(trigger, "_pinned_gh_context", lambda: observer_context)

    def collect_gates(
        selected_head: str,
        *,
        _observer_context: object,
    ) -> dict[str, object]:
        calls.append(("gates", selected_head, _observer_context))
        assert _observer_context is observer_context
        return gates

    def collect_readiness(
        selected_repository: Path,
        selected_head: str,
        *,
        _observer_context: object,
    ) -> dict[str, object]:
        calls.append(
            ("runners", selected_repository, selected_head, _observer_context)
        )
        assert _observer_context is observer_context
        return readiness

    document = {"request_id": trigger.REQUEST_ID, "source_head": source_head}
    monkeypatch.setattr(trigger, "collect_remote_gate_evidence", collect_gates)
    monkeypatch.setattr(trigger, "collect_runner_readiness", collect_readiness)
    monkeypatch.setattr(trigger, "build_request", lambda *_args, **_kwargs: document)

    written = trigger.write_request(repository)
    target = repository / trigger.SENTINEL_PATH
    assert target.read_bytes() == trigger.canonical_bytes(document, trailing_lf=True)
    assert written["source_head"] == source_head
    assert calls == [
        ("gates", source_head, observer_context),
        ("runners", repository.resolve(), source_head, observer_context),
    ]
