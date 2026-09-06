from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_development_trigger_d110 as trigger  # noqa: E402


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


def _git_succeeds(repository: Path, *arguments: str) -> bool:
    return (
        subprocess.run(
            ["git", *arguments],
            cwd=repository,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.email", "d110-trigger@example.invalid")
    _git(repository, "config", "user.name", "D1.10 E1 trigger fixture")
    (repository / "base.txt").write_bytes(b"immutable base\n")
    return repository, _commit(repository, "fixture: immutable base")


def _remote_gate_evidence(source_head: str) -> dict[str, object]:
    rows = []
    for index, (path, event, pull_request_number) in enumerate(
        trigger.REMOTE_GATE_SPECS, start=1
    ):
        run_id = 1_100_000 + index
        rows.append(
            {
                "conclusion": "success",
                "event": event,
                "head_branch": trigger.EXPECTED_BRANCH,
                "head_sha": source_head,
                "html_url": (
                    "https://github.com/Scuttie/enterprise-shared-memory-poc/"
                    f"actions/runs/{run_id}"
                ),
                "pull_request_number": pull_request_number,
                "run_attempt": 1,
                "run_id": run_id,
                "status": "completed",
                "workflow_path": path,
            }
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


def _runner_rows() -> list[dict[str, object]]:
    return [
        {
            "busy": False,
            "id": 2_200_000 + index,
            "labels": list(trigger.REQUIRED_RUNNER_LABELS),
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
                {"pid": 3_300_000 + index, "root": root}
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


def _execution_run(trigger_head: str, run_id: int) -> dict[str, object]:
    return {
        "conclusion": None,
        "event": "push",
        "head_branch": trigger.EXPECTED_BRANCH,
        "head_sha": trigger_head,
        "id": run_id,
        "path": trigger.EXPECTED_WORKFLOW_PATH,
        "run_attempt": 1,
        "status": "in_progress",
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


def _environment(after: str) -> dict[str, str]:
    return {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": trigger.EXPECTED_REF,
        "GITHUB_REPOSITORY": trigger.EXPECTED_REPOSITORY,
        "GITHUB_RUN_ID": "990011",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": after,
        "GITHUB_WORKFLOW_REF": trigger.EXPECTED_WORKFLOW_REF,
        "GITHUB_WORKFLOW_SHA": after,
    }


def _host_environment(after: str) -> dict[str, str]:
    return {
        **_environment(after),
        "GITHUB_JOB": "bounded-context-preflight",
        "GITHUB_WORKSPACE": "/opt/trimem-d110-runners/preflight/_work/repository",
        "RUNNER_ARCH": "X64",
        "RUNNER_OS": "Linux",
    }


def test_d110_repository_activation_source_is_canonical_after_reseal() -> None:
    relative_test_path = "tests/unit/test_trimem_d110_e1_trigger.py"
    if not _git_succeeds(ROOT, "cat-file", "-e", f"HEAD:{relative_test_path}"):
        pytest.skip("D1.10 activation source has not been committed and resealed yet")

    sentinel_commit = _git(
        ROOT,
        "log",
        "-1",
        "--diff-filter=A",
        "--format=%H",
        "HEAD",
        "--",
        trigger.SENTINEL_PATH,
    )
    source_head = (
        _git(ROOT, "rev-parse", f"{sentinel_commit}^")
        if sentinel_commit
        else _git(ROOT, "rev-parse", "HEAD")
    )

    validated = trigger.validate_correction_source(
        ROOT,
        source_head,
        require_checked_out_head=False,
    )

    assert validated["status"] == "PASS"
    assert validated["source_head"] == source_head
    assert validated["sentinel_present"] is False
    assert validated["model_calls"] == validated["paid_model_calls"] == 0
    assert validated["task_arm_runs"] == 0
    assert validated["total_usd"] == 0.0
    assert validated["activation_changes"][".github/workflows/trimem-benchmark.yml"] == "M"
    assert validated["activation_changes"]["scripts/trimem_development_trigger_d110.py"] == "A"


def test_d110_cli_imports_sibling_lock_reader_under_isolated_python() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "scripts" / "trimem_development_trigger_d110.py"),
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


def test_d110_remote_gate_evidence_requires_exact_ordered_twelve_rows() -> None:
    source_head = "a" * 40
    evidence = _remote_gate_evidence(source_head)

    assert len(trigger.REMOTE_GATE_SPECS) == 12
    assert trigger._validate_remote_gate_evidence(
        evidence, source_head=source_head
    ) == evidence
    assert [row["workflow_path"] for row in evidence["workflows"]] == list(
        trigger.REQUIRED_REMOTE_GATE_WORKFLOWS
    )
    assert evidence["pull_request"] == _pull_request(source_head)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda rows: rows.__setitem__(
                0, {**rows[0], "run_attempt": 2}
            ),
            "missing, red, rerun, or misbound",
        ),
        (lambda rows: rows.pop(), "workflow count differs"),
        (lambda rows: rows.append(deepcopy(rows[0])), "workflow count differs"),
        (
            lambda rows: rows.__setitem__(1, deepcopy(rows[0])),
            "row shape differs|missing, red, rerun, or misbound",
        ),
        (
            lambda rows: rows.__setitem__(
                6, {**rows[6], "pull_request_number": None}
            ),
            "missing, red, rerun, or misbound",
        ),
    ],
)
def test_d110_remote_gate_evidence_fails_closed_on_attempt_missing_duplicate_or_pr(
    mutation: object,
    message: str,
) -> None:
    source_head = "a" * 40
    evidence = _remote_gate_evidence(source_head)
    rows = evidence["workflows"]
    assert isinstance(rows, list)
    mutation(rows)  # type: ignore[operator]

    with pytest.raises(trigger.DevelopmentTriggerError, match=message):
        trigger._validate_remote_gate_evidence(evidence, source_head=source_head)


def test_d110_pull_request_binding_is_exact_and_unique() -> None:
    source_head = "a" * 40
    exact = [
        {
            "number": trigger.PULL_REQUEST_NUMBER,
            "head": {"sha": source_head},
        }
    ]
    assert trigger._validate_pull_request_binding(exact, source_head) is True

    invalid = (
        [],
        exact + deepcopy(exact),
        [{"number": trigger.PULL_REQUEST_NUMBER + 1, "head": {"sha": source_head}}],
        [{"number": trigger.PULL_REQUEST_NUMBER, "head": {"sha": "b" * 40}}],
        [{"number": trigger.PULL_REQUEST_NUMBER}],
    )
    assert all(
        trigger._validate_pull_request_binding(candidate, source_head) is False
        for candidate in invalid
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_sha", "b" * 40),
        ("draft", False),
        ("head_ref", "wrong-branch"),
        ("head_repository", "wrong/repository"),
        ("head_sha", "b" * 40),
        ("state", "closed"),
    ],
)
def test_d110_remote_gate_evidence_rejects_stale_or_misbound_current_pr(
    field: str, value: object
) -> None:
    source_head = "a" * 40
    evidence = _remote_gate_evidence(source_head)
    pull = evidence["pull_request"]
    assert isinstance(pull, dict)
    pull[field] = value

    with pytest.raises(trigger.DevelopmentTriggerError, match="PR #18"):
        trigger._validate_remote_gate_evidence(evidence, source_head=source_head)


def test_d110_runner_readiness_accepts_only_exact_two_clean_idle_runners() -> None:
    source_head = "a" * 40
    readiness = _runner_readiness(source_head)

    assert trigger._validate_runner_readiness(
        readiness, source_head=source_head
    ) == readiness
    assert [row["name"] for row in readiness["runners"]] == list(
        trigger.RUNNER_NAMES
    )
    assert readiness["host"]["os_id"] == "ubuntu"  # type: ignore[index]
    assert readiness["host"]["os_version_id"] == "24.04"  # type: ignore[index]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("os_id", "debian"),
        ("os_id", "Ubuntu"),
        ("os_version_id", "22.04"),
        ("os_version_id", "24.04.1"),
    ],
)
def test_d110_runner_readiness_rejects_os_identity_drift(
    field: str, value: str
) -> None:
    source_head = "a" * 40
    readiness = _runner_readiness(source_head)
    readiness["host"][field] = value  # type: ignore[index]

    with pytest.raises(trigger.DevelopmentTriggerError, match="host readiness"):
        trigger._validate_runner_readiness(readiness, source_head=source_head)


@pytest.mark.parametrize(
    "raw",
    [
        b'ID=ubuntu\nVERSION_ID="24.04"\n',
        b'ID="ubuntu"\nVERSION_ID=24.04\n',
    ],
)
def test_d110_os_release_parser_accepts_only_exact_ubuntu_2404_encodings(
    raw: bytes,
) -> None:
    assert trigger._validate_ubuntu_os_release(raw) == {
        "os_id": "ubuntu",
        "os_version_id": "24.04",
    }


@pytest.mark.parametrize(
    "raw",
    [
        b"ID ubuntu\nVERSION_ID=24.04\n",
        b"ID=ubuntu\n",
        b"VERSION_ID=24.04\n",
        b"ID=ubuntu\nID=ubuntu\nVERSION_ID=24.04\n",
        b"ID=ubuntu\nVERSION_ID=24.04\nVERSION_ID=24.04\n",
        b"ID=debian\nVERSION_ID=24.04\n",
        b"ID=ubuntu\nVERSION_ID=22.04\n",
        b"ID=ubuntu\nVERSION_ID=24.04\xff\n",
    ],
)
def test_d110_os_release_parser_rejects_malformed_duplicate_or_other_os(
    raw: bytes,
) -> None:
    with pytest.raises(
        trigger.DevelopmentTriggerError,
        match="OS release|os-release|Ubuntu",
    ):
        trigger._validate_ubuntu_os_release(raw)


def test_d110_runner_readiness_requires_distinct_listener_processes() -> None:
    source_head = "a" * 40
    readiness = _runner_readiness(source_head)
    listeners = readiness["host"]["listener_bindings"]  # type: ignore[index]
    listeners[1]["pid"] = listeners[0]["pid"]  # type: ignore[index]

    with pytest.raises(
        trigger.DevelopmentTriggerError,
        match="listener.*PID|host readiness",
    ):
        trigger._validate_runner_readiness(readiness, source_head=source_head)


def test_d110_runner_readiness_rejects_stale_observation() -> None:
    source_head = "a" * 40
    readiness = _runner_readiness(source_head)
    now = datetime(2026, 9, 7, 0, 0, tzinfo=timezone.utc)
    readiness["observed_at_utc"] = (now - timedelta(hours=2)).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")

    with pytest.raises(trigger.DevelopmentTriggerError, match="fresh|stale"):
        trigger._validate_runner_readiness_freshness(readiness, now=now)


def test_d110_runner_readiness_rejects_excessive_future_skew() -> None:
    source_head = "a" * 40
    readiness = _runner_readiness(source_head)
    now = datetime(2026, 9, 7, 0, 0, tzinfo=timezone.utc)
    readiness["observed_at_utc"] = (now + timedelta(minutes=6)).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")

    with pytest.raises(trigger.DevelopmentTriggerError, match="future|fresh"):
        trigger._validate_runner_readiness_freshness(readiness, now=now)


def test_d110_runner_readiness_rejects_wrong_source_binding() -> None:
    readiness = _runner_readiness("a" * 40)

    with pytest.raises(trigger.DevelopmentTriggerError, match="identity differs"):
        trigger._validate_runner_readiness(readiness, source_head="b" * 40)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["runners"][0].__setitem__("busy", True),
            "registration row differs",
        ),
        (
            lambda value: value["runners"][1].__setitem__("status", "offline"),
            "registration row differs",
        ),
        (
            lambda value: value["runners"][0]["labels"].__setitem__(
                -1, "ubuntu-latest"
            ),
            "registration row differs",
        ),
        (
            lambda value: value["runners"].pop(),
            "registration set differs",
        ),
        (
            lambda value: value["host"].__setitem__("container_count", 1),
            "host readiness differs",
        ),
        (
            lambda value: value["host"]["forbidden_secret_names_present"].append(
                "OPENAI_API_KEY"
            ),
            "host readiness differs",
        ),
    ],
)
def test_d110_runner_readiness_fails_closed_on_identity_label_or_host_drift(
    mutation: object, message: str
) -> None:
    source_head = "a" * 40
    readiness = _runner_readiness(source_head)
    mutation(readiness)  # type: ignore[operator]

    with pytest.raises(trigger.DevelopmentTriggerError, match=message):
        trigger._validate_runner_readiness(readiness, source_head=source_head)


def test_d110_request_binds_canonical_runner_readiness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_head = "a" * 40
    gates = _remote_gate_evidence(source_head)
    readiness = _runner_readiness(source_head)
    bindings = {
        name: "sha256:" + chr(ord("a") + index) * 64
        for index, name in enumerate(
            (
                "loader_environment_contract_sha256",
                "loader_preflight_sha256",
                "grader_lifecycle_sha256",
                "cell_commit_journal_sha256",
                "resume_disposition_sha256",
            )
        )
    }
    monkeypatch.setattr(
        trigger,
        "_validate_source",
        lambda _repository, selected: {
            "activation_changes": {},
            "bindings": bindings,
            "hard_cap": dict(trigger.EXPECTED_DEVELOPMENT_HARD_CAP),
            "target_order": list(trigger.EXPECTED_TARGET_ORDER),
        }
        if selected == source_head
        else pytest.fail("wrong source head"),
    )

    request = trigger.build_request(
        tmp_path,
        source_head=source_head,
        remote_gate_evidence=gates,
        runner_readiness=readiness,
    )

    assert request["runner_readiness"] == readiness
    assert request["activation_actuals"] == trigger.ACTIVATION_ZERO_COUNTERS
    assert request["pre_execution_actuals"]["paid_model_calls"] == 0


def test_d110_sentinel_commit_accepts_one_regular_add_only_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, parent = _repository(tmp_path)
    sentinel = repository / trigger.SENTINEL_PATH
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b'{"fixture":true}\n')
    after = _commit(repository, "control: add D1.10 E1 sentinel only")
    monkeypatch.setattr(
        trigger,
        "validate_request",
        lambda _repository, raw, *, source_head: {
            "raw": raw,
            "source_head": source_head,
        },
    )

    validated = trigger.validate_sentinel_commit(
        repository, after, expected_parent=parent
    )

    assert validated["source_head"] == parent
    assert validated["raw"] == b'{"fixture":true}\n'


def test_d110_sentinel_commit_rejects_a_second_changed_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, parent = _repository(tmp_path)
    sentinel = repository / trigger.SENTINEL_PATH
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b'{"fixture":true}\n')
    (repository / "unexpected.txt").write_bytes(b"not sentinel-only\n")
    after = _commit(repository, "control: invalid multi-file trigger")
    monkeypatch.setattr(trigger, "validate_request", pytest.fail)

    with pytest.raises(trigger.DevelopmentTriggerError, match="exclusive _011"):
        trigger.validate_sentinel_commit(
            repository, after, expected_parent=parent
        )


def test_d110_sentinel_commit_rejects_non_100644_blob_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, parent = _repository(tmp_path)
    sentinel = repository / trigger.SENTINEL_PATH
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b'{"fixture":true}\n')
    _git(repository, "add", "--chmod=+x", "--", trigger.SENTINEL_PATH)
    _git(repository, "commit", "-m", "control: invalid executable sentinel")
    after = _git(repository, "rev-parse", "HEAD")
    assert _git(repository, "ls-tree", after, "--", trigger.SENTINEL_PATH).startswith(
        "100755 blob "
    )
    monkeypatch.setattr(trigger, "validate_request", pytest.fail)

    with pytest.raises(
        trigger.DevelopmentTriggerError,
        match="100644|regular non-executable",
    ):
        trigger.validate_sentinel_commit(
            repository, after, expected_parent=parent
        )


def test_d110_sentinel_commit_rejects_merge_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, _base = _repository(tmp_path)
    primary_branch = _git(repository, "branch", "--show-current")
    _git(repository, "switch", "-c", "sentinel-side")
    sentinel = repository / trigger.SENTINEL_PATH
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b'{"fixture":true}\n')
    _commit(repository, "side: add sentinel")
    _git(repository, "switch", primary_branch)
    (repository / "primary.txt").write_bytes(b"diverge primary\n")
    _commit(repository, "primary: diverge")
    _git(repository, "merge", "--no-ff", "sentinel-side", "-m", "invalid merge trigger")
    after = _git(repository, "rev-parse", "HEAD")
    monkeypatch.setattr(trigger, "validate_request", pytest.fail)

    with pytest.raises(trigger.DevelopmentTriggerError, match="single-parent"):
        trigger.validate_sentinel_commit(repository, after)


def test_d110_runner_host_preflight_binds_exact_event_source_and_live_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before, after = "a" * 40, "b" * 40
    readiness = _runner_readiness(before)
    now = datetime.now(timezone.utc)
    readiness["observed_at_utc"] = now.isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(_event(before, after)), encoding="utf-8")
    environment = _host_environment(after)
    calls: list[tuple[Path, str, object, object]] = []
    live_host = {
        "architecture": "x86_64",
        "source_head": before,
        "status": "PASS",
    }
    monkeypatch.setattr(
        trigger,
        "validate_sentinel_commit",
        lambda repository,
        selected,
        *,
        expected_parent,
        require_checked_out_head=True: {
            "runner_readiness": readiness,
            "source_head": expected_parent,
            "trigger_commit": selected,
        }
        if (
            repository == ROOT
            and selected == after
            and expected_parent == before
            and require_checked_out_head is True
        )
        else pytest.fail("runner host preflight used wrong sentinel identity"),
    )

    def collect_local(
        repository: Path,
        source_head: str,
        expected_readiness: object,
        *,
        environ: object = None,
    ) -> dict[str, object]:
        calls.append((repository, source_head, expected_readiness, environ))
        return live_host

    monkeypatch.setattr(trigger, "collect_local_runner_host_readiness", collect_local)

    validated = trigger.validate_runner_host_preflight(
        ROOT,
        event_path,
        environ=environment,
        now=now,
    )

    assert calls == [(ROOT, before, readiness, environment)]
    assert validated["status"] == "PASS"
    assert validated["source_head"] == before
    assert validated["trigger_commit"] == after
    assert validated["execution_run_id"] == int(environment["GITHUB_RUN_ID"])
    assert validated["execution_run_attempt"] == 1
    assert len(validated["live_host_sha256"]) == 64


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"GITHUB_JOB": "branch-trigger-preflight"}, "bounded-context"),
        ({"RUNNER_OS": "Windows"}, "platform"),
        ({"RUNNER_ARCH": "ARM64"}, "platform"),
        ({"GITHUB_RUN_ATTEMPT": "2"}, "attempt"),
        ({"GITHUB_SHA": "c" * 40}, "execution SHA"),
    ],
)
def test_d110_runner_host_preflight_rejects_wrong_job_platform_or_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    change: dict[str, str],
    message: str,
) -> None:
    before, after = "a" * 40, "b" * 40
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(_event(before, after)), encoding="utf-8")
    environment = {**_host_environment(after), **change}
    monkeypatch.setattr(trigger, "validate_sentinel_commit", pytest.fail)
    monkeypatch.setattr(trigger, "collect_local_runner_host_readiness", pytest.fail)

    with pytest.raises(trigger.DevelopmentTriggerError, match=message):
        trigger.validate_runner_host_preflight(
            ROOT,
            event_path,
            environ=environment,
            now=datetime.now(timezone.utc),
        )


def test_d110_runner_host_preflight_fails_closed_on_live_probe_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before, after = "a" * 40, "b" * 40
    readiness = _runner_readiness(before)
    now = datetime.now(timezone.utc)
    readiness["observed_at_utc"] = now.isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(_event(before, after)), encoding="utf-8")
    monkeypatch.setattr(
        trigger,
        "validate_sentinel_commit",
        lambda *_args, **_kwargs: {"runner_readiness": readiness},
    )

    def reject_live_probe(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise trigger.DevelopmentTriggerError("live local host probe failed")

    monkeypatch.setattr(
        trigger, "collect_local_runner_host_readiness", reject_live_probe
    )

    with pytest.raises(
        trigger.DevelopmentTriggerError,
        match="live local host probe failed",
    ):
        trigger.validate_runner_host_preflight(
            ROOT,
            event_path,
            environ=_host_environment(after),
            now=now,
        )


def test_d110_branch_trigger_accepts_only_exact_push_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before, after = "a" * 40, "b" * 40
    run_id = 990_011
    gates = _remote_gate_evidence(before)
    readiness = _runner_readiness(before)
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(_event(before, after)), encoding="utf-8")
    monkeypatch.setattr(
        trigger,
        "validate_sentinel_commit",
        lambda _repository,
        selected,
        *,
        expected_parent,
        require_checked_out_head=True: {
            "remote_gate_evidence": gates,
            "runner_readiness": readiness,
            "source_head": expected_parent,
            "trigger_commit": selected,
        },
    )
    monkeypatch.setattr(
        trigger,
        "_pinned_gh_context",
        lambda: ("pinned-gh", {"GH_TOKEN": "fixture"}),
    )
    monkeypatch.setattr(
        trigger,
        "_query_github_runs",
        lambda gh, head, event, safe_environment: [_execution_run(after, run_id)]
        if (
            gh == "pinned-gh"
            and head == after
            and event == "push"
            and safe_environment == {"GH_TOKEN": "fixture"}
        )
        else pytest.fail("wrong execution-run query"),
    )
    monkeypatch.setattr(
        trigger,
        "_collect_current_pull_request",
        lambda gh, safe_environment, *, expected_head: _pull_request(after)
        if (
            gh == "pinned-gh"
            and safe_environment == {"GH_TOKEN": "fixture"}
            and expected_head == after
        )
        else pytest.fail("wrong current PR query"),
    )
    monkeypatch.setattr(
        trigger,
        "_collect_remote_gate_rows",
        lambda gh, safe_environment, *, source_head: gates["workflows"]
        if (
            gh == "pinned-gh"
            and safe_environment == {"GH_TOKEN": "fixture"}
            and source_head == before
        )
        else pytest.fail("wrong live remote gate query"),
    )
    monkeypatch.setattr(
        trigger,
        "collect_remote_runner_rows",
        lambda: deepcopy(readiness["runners"]),
    )
    environment = _environment(after)
    environment["GITHUB_RUN_ID"] = str(run_id)

    validated = trigger.validate_branch_trigger(
        ROOT, event_path, environ=environment
    )

    assert validated == {
        "activation_actuals": trigger.ACTIVATION_ZERO_COUNTERS,
        "execution_run": {
            "event": "push",
            "head_sha": after,
            "run_attempt": 1,
            "run_id": run_id,
            "workflow_path": trigger.EXPECTED_WORKFLOW_PATH,
        },
        "request_id": trigger.REQUEST_ID,
        "source_head": before,
        "status": "PASS",
        "trigger_commit": after,
    }


@pytest.mark.parametrize(
    ("event_change", "environment_change", "message"),
    [
        ({"created": True}, {}, "branch or repository"),
        ({"deleted": True}, {}, "deleted"),
        ({"forced": True}, {}, "forced"),
        ({"ref": "refs/heads/wrong"}, {}, "branch or repository"),
        (
            {"repository": {"full_name": "wrong/repository"}},
            {},
            "branch or repository",
        ),
        ({}, {"GITHUB_RUN_ATTEMPT": "2"}, "attempt"),
        ({}, {"GITHUB_SHA": "c" * 40}, "after SHA"),
        ({}, {"GITHUB_WORKFLOW_SHA": "c" * 40}, "workflow SHA"),
    ],
)
def test_d110_branch_trigger_fails_closed_on_push_identity_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    event_change: dict[str, object],
    environment_change: dict[str, str],
    message: str,
) -> None:
    before, after = "a" * 40, "b" * 40
    event = {**_event(before, after), **event_change}
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    environment = {**_environment(after), **environment_change}
    monkeypatch.setattr(trigger, "_validate_unique_execution_run", pytest.fail)
    monkeypatch.setattr(trigger, "validate_sentinel_commit", pytest.fail)

    with pytest.raises(trigger.DevelopmentTriggerError, match=message):
        trigger.validate_branch_trigger(ROOT, event_path, environ=environment)


def test_d110_branch_trigger_rejects_protected_secret_exposure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before, after = "a" * 40, "b" * 40
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(_event(before, after)), encoding="utf-8")
    environment = {**_environment(after), "OPENAI_API_KEY": "must-not-be-here"}
    monkeypatch.setattr(trigger, "_validate_unique_execution_run", pytest.fail)
    monkeypatch.setattr(trigger, "validate_sentinel_commit", pytest.fail)

    with pytest.raises(trigger.DevelopmentTriggerError, match="protected benchmark secrets"):
        trigger.validate_branch_trigger(ROOT, event_path, environ=environment)


def test_d110_branch_trigger_rejects_remote_gate_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before, after = "a" * 40, "b" * 40
    embedded = _remote_gate_evidence(before)
    readiness = _runner_readiness(before)
    live = deepcopy(embedded)
    live["workflows"][0]["run_id"] += 1  # type: ignore[index,operator]
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(_event(before, after)), encoding="utf-8")
    monkeypatch.setattr(
        trigger,
        "validate_sentinel_commit",
        lambda *_args, **_kwargs: {
            "remote_gate_evidence": embedded,
            "runner_readiness": readiness,
        },
    )
    monkeypatch.setattr(
        trigger,
        "_validate_unique_execution_run",
        lambda *_args: {"run_id": 990_011},
    )
    monkeypatch.setattr(
        trigger, "_pinned_gh_context", lambda: ("pinned-gh", {})
    )
    monkeypatch.setattr(
        trigger,
        "_collect_current_pull_request",
        lambda *_args, **_kwargs: _pull_request(after),
    )
    monkeypatch.setattr(
        trigger,
        "_collect_remote_gate_rows",
        lambda *_args, **_kwargs: live["workflows"],
    )

    with pytest.raises(trigger.DevelopmentTriggerError, match="embedded remote gates"):
        trigger.validate_branch_trigger(
            ROOT, event_path, environ=_environment(after)
        )


def test_d110_branch_trigger_rejects_live_runner_registration_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before, after = "a" * 40, "b" * 40
    gates = _remote_gate_evidence(before)
    readiness = _runner_readiness(before)
    live_runners = deepcopy(readiness["runners"])
    live_runners[0]["labels"][-1] = "wrong-label"  # type: ignore[index]
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(_event(before, after)), encoding="utf-8")
    monkeypatch.setattr(
        trigger,
        "validate_sentinel_commit",
        lambda *_args, **_kwargs: {
            "remote_gate_evidence": gates,
            "runner_readiness": readiness,
        },
    )
    monkeypatch.setattr(
        trigger,
        "_validate_unique_execution_run",
        lambda *_args: {"run_id": 990_011},
    )
    monkeypatch.setattr(
        trigger, "_pinned_gh_context", lambda: ("pinned-gh", {})
    )
    monkeypatch.setattr(
        trigger,
        "_collect_current_pull_request",
        lambda *_args, **_kwargs: _pull_request(after),
    )
    monkeypatch.setattr(
        trigger,
        "_collect_remote_gate_rows",
        lambda *_args, **_kwargs: gates["workflows"],
    )
    monkeypatch.setattr(
        trigger, "collect_remote_runner_rows", lambda: live_runners
    )

    with pytest.raises(
        trigger.DevelopmentTriggerError,
        match="embedded runner registrations",
    ):
        trigger.validate_branch_trigger(
            ROOT, event_path, environ=_environment(after)
        )
def test_d110_unique_execution_run_rejects_duplicate_benchmark_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trigger_head = "b" * 40
    run_id = 990_011
    run = _execution_run(trigger_head, run_id)
    monkeypatch.setattr(
        trigger, "_pinned_gh_context", lambda: ("pinned-gh", {})
    )
    monkeypatch.setattr(
        trigger,
        "_query_github_runs",
        lambda *_args, **_kwargs: [run, deepcopy(run)],
    )

    with pytest.raises(
        trigger.DevelopmentTriggerError,
        match="exactly one benchmark workflow push run",
    ):
        trigger._validate_unique_execution_run(
            trigger_head, {"GITHUB_RUN_ID": str(run_id)}
        )


@pytest.mark.parametrize("run_id", [None, "", "0", "-1", " 990011", "９９００１１"])
def test_d110_unique_execution_run_rejects_noncanonical_run_id(
    monkeypatch: pytest.MonkeyPatch, run_id: str | None
) -> None:
    monkeypatch.setattr(trigger, "_pinned_gh_context", pytest.fail)
    environment = {} if run_id is None else {"GITHUB_RUN_ID": run_id}

    with pytest.raises(trigger.DevelopmentTriggerError, match="run ID is invalid"):
        trigger._validate_unique_execution_run("b" * 40, environment)
