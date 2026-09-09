from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_development_trigger_d112 as d112  # noqa: E402


_D112_IMPORT_SNAPSHOT = {
    name: getattr(d112, name)
    for name in (
        "REQUEST_ID",
        "REQUEST_SCHEMA",
        "SENTINEL_PATH",
        "REMOTE_GATE_SCHEMA",
        "RUNNER_READINESS_SCHEMA",
        "_validate_source",
        "build_request",
        "validate_request",
        "validate_sentinel_commit",
        "validate_branch_trigger",
    )
}

import trimem_development_trigger_d113 as trigger  # noqa: E402


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


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.email", "d113-trigger@example.invalid")
    _git(repository, "config", "user.name", "D1.13 trigger fixture")
    (repository / "base.txt").write_bytes(b"base\n")
    _commit(repository, "fixture: base")
    return repository


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
        "GITHUB_JOB": "branch-trigger-preflight",
        "GITHUB_REF": trigger.EXPECTED_REF,
        "GITHUB_REPOSITORY": trigger.EXPECTED_REPOSITORY,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "113013",
        "GITHUB_SHA": after,
        "GITHUB_WORKFLOW_REF": trigger.EXPECTED_WORKFLOW_REF,
        "GITHUB_WORKFLOW_SHA": after,
    }


def test_d113_identity_is_exact_and_reuses_unassigned_d112_runners() -> None:
    assert trigger.REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_013"
    assert trigger.REQUEST_SCHEMA == "trimem/development-tuning-branch-trigger/1.13"
    assert trigger.SENTINEL_PATH.endswith("EXEC_REQUEST_013.json")
    assert trigger.REQUIRED_EXTERNAL_AUTHORIZATION == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_013_APPROVED_ONCE"
    )
    assert trigger.AMENDMENT_ENDPOINT == "TRIMEM_V1_READY_FOR_EXEC_013_REQUEST"
    assert trigger.PREVIOUS_SOURCE_HEAD == (
        "9db94e2a4abfaad0bb27079738b77836d68fa2e4"
    )
    assert trigger.PREVIOUS_EXECUTION_HEAD == (
        "491d1022fe079d182d7b453c48083c486936dcb2"
    )
    assert trigger.PREVIOUS_RUN_ID == 34_128_541_859
    assert trigger.PREVIOUS_FAILURE_SUBTYPE == (
        "HOSTED_GITHUB_TOKEN_RUNNER_LIST_AUTHORIZATION"
    )
    assert trigger.RUNNER_NAMES == d112.RUNNER_NAMES
    assert trigger.RUNNER_ROOTS == d112.RUNNER_ROOTS


def test_import_and_reload_do_not_mutate_d112_global_state() -> None:
    for name, expected in _D112_IMPORT_SNAPSHOT.items():
        observed = getattr(d112, name)
        assert observed is expected if callable(expected) else observed == expected
    importlib.reload(trigger)
    for name, expected in _D112_IMPORT_SNAPSHOT.items():
        observed = getattr(d112, name)
        assert observed is expected if callable(expected) else observed == expected


def test_runtime_context_is_nested_and_restores_on_failure() -> None:
    before_id = d112.REQUEST_ID
    before_validator = d112.validate_sentinel_commit
    with pytest.raises(RuntimeError, match="fixture failure"):
        with trigger._d113_runtime_context():
            assert d112.REQUEST_ID == trigger.REQUEST_ID
            assert d112.validate_sentinel_commit is trigger._validate_sentinel_commit_impl
            with trigger._d113_runtime_context():
                assert d112.REQUEST_SCHEMA == trigger.REQUEST_SCHEMA
            assert d112.REQUEST_ID == trigger.REQUEST_ID
            raise RuntimeError("fixture failure")
    assert d112.REQUEST_ID == before_id
    assert d112.validate_sentinel_commit is before_validator


def test_generic_runtime_wrapper_observes_d113_then_restores(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed: list[tuple[str, str]] = []

    def fake_runtime(*args: object, **kwargs: object) -> dict[str, str]:
        del args, kwargs
        observed.append((d112.REQUEST_ID, d112.SENTINEL_PATH))
        return {"status": "PASS"}

    monkeypatch.setattr(d112, "validate_runner_host_preflight", fake_runtime)
    original_id = d112.REQUEST_ID
    assert trigger.validate_runner_host_preflight(tmp_path, tmp_path / "event") == {
        "status": "PASS"
    }
    assert observed == [(trigger.REQUEST_ID, trigger.SENTINEL_PATH)]
    assert d112.REQUEST_ID == original_id
    assert d112.validate_runner_host_preflight is fake_runtime


def test_branch_gate_uses_fresh_embedded_readiness_without_runner_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before = "a" * 40
    after = "b" * 40
    event_path = tmp_path / "event.json"
    event_path.write_bytes(trigger.canonical_bytes(_event(before, after)))
    live_rows = [{"workflow_path": "gate", "run_id": 1}]
    request = {
        "remote_gate_evidence": {"workflows": deepcopy(live_rows)},
        "runner_readiness": {"observed_at_utc": "2026-09-07T13:35:33.072Z"},
    }
    calls: list[str] = []

    monkeypatch.setattr(trigger, "resolve_repository_root", lambda path: path)
    monkeypatch.setattr(
        trigger,
        "_validate_secret_free_branch_environment",
        lambda environment: calls.append("secret-free"),
    )
    monkeypatch.setattr(
        trigger,
        "_validate_unique_execution_run",
        lambda head, environment: {"head_sha": head, "run_id": int(environment["GITHUB_RUN_ID"])},
    )
    monkeypatch.setattr(
        trigger,
        "_validate_sentinel_commit_impl",
        lambda *args, **kwargs: deepcopy(request),
    )
    monkeypatch.setattr(
        trigger,
        "_validate_runner_readiness_freshness",
        lambda evidence: calls.append("fresh-readiness"),
    )
    monkeypatch.setattr(trigger, "_pinned_gh_context", lambda: ("gh", {"PATH": "pinned"}))
    monkeypatch.setattr(
        trigger,
        "_collect_current_pull_request",
        lambda *args, **kwargs: calls.append("live-pr"),
    )
    monkeypatch.setattr(
        trigger,
        "_collect_remote_gate_rows",
        lambda *args, **kwargs: calls.append("live-source-runs") or live_rows,
    )

    def forbidden_runner_api(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("hosted branch must not query repository runners")

    monkeypatch.setattr(d112, "_collect_remote_runner_rows", forbidden_runner_api)
    result = trigger.validate_branch_trigger(
        tmp_path, event_path, environ=_environment(after)
    )
    assert result["status"] == "PASS"
    assert result["runner_readiness_authority"] == "FRESH_EMBEDDED_PREREGISTRATION"
    assert calls == ["secret-free", "fresh-readiness", "live-pr", "live-source-runs"]


def test_branch_gate_fails_closed_on_stale_embedded_readiness_before_live_queries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before = "a" * 40
    after = "b" * 40
    event_path = tmp_path / "event.json"
    event_path.write_bytes(trigger.canonical_bytes(_event(before, after)))
    monkeypatch.setattr(trigger, "resolve_repository_root", lambda path: path)
    monkeypatch.setattr(trigger, "_validate_secret_free_branch_environment", lambda env: None)
    monkeypatch.setattr(trigger, "_validate_unique_execution_run", lambda *args: {})
    monkeypatch.setattr(
        trigger,
        "_validate_sentinel_commit_impl",
        lambda *args, **kwargs: {"runner_readiness": {}, "remote_gate_evidence": {}},
    )
    monkeypatch.setattr(
        trigger,
        "_validate_runner_readiness_freshness",
        lambda evidence: (_ for _ in ()).throw(trigger.DevelopmentTriggerError("stale")),
    )
    monkeypatch.setattr(
        trigger,
        "_pinned_gh_context",
        lambda: (_ for _ in ()).throw(AssertionError("must not reach live query")),
    )
    with pytest.raises(trigger.DevelopmentTriggerError, match="stale"):
        trigger.validate_branch_trigger(tmp_path, event_path, environ=_environment(after))


def test_writer_retains_admin_runner_collection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = tmp_path.resolve()
    source_head = "c" * 40
    readiness_calls: list[tuple[Path, str, object]] = []
    pending_calls: list[tuple[object, ...]] = []

    def fake_git(repo: Path, *args: str) -> str:
        del repo
        if args[:3] == ("symbolic-ref", "--quiet", "HEAD"):
            return trigger.EXPECTED_REF + "\n"
        if args[:2] == ("status", "--porcelain=v1"):
            return ""
        if args[:2] == ("rev-parse", "HEAD"):
            return source_head + "\n"
        if args and args[0] == "log":
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(trigger, "resolve_repository_root", lambda path: path.resolve())
    monkeypatch.setattr(trigger, "git", fake_git)
    monkeypatch.setattr(trigger, "_validate_secret_free_branch_environment", lambda env: None)
    monkeypatch.setattr(trigger, "_validate_source_impl", lambda *args: {})
    monkeypatch.setattr(trigger, "_pinned_gh_context", lambda: ("admin-gh", {"PATH": "safe"}))
    monkeypatch.setattr(
        trigger,
        "_require_no_pending_benchmark_consumers",
        lambda *args: pending_calls.append(args),
    )
    monkeypatch.setattr(trigger, "collect_remote_gate_evidence", lambda *args, **kwargs: {"g": 1})

    def readiness(repo: Path, head: str, *, _observer_context: object) -> dict[str, int]:
        readiness_calls.append((repo, head, _observer_context))
        return {"r": 1}

    monkeypatch.setattr(trigger, "collect_runner_readiness", readiness)
    monkeypatch.setattr(
        trigger,
        "_build_request_impl",
        lambda *args, **kwargs: {"request_id": trigger.REQUEST_ID},
    )
    monkeypatch.setattr(trigger, "_recheck_request_write_boundary", lambda *args: None)
    result = trigger.write_request(repository)
    assert result["status"] == "WROTE_ZERO_AUTHORITY_SENTINEL"
    assert readiness_calls == [
        (repository, source_head, ("admin-gh", {"PATH": "safe"}))
    ]
    assert len(pending_calls) == 2
    target = repository.joinpath(*trigger.SENTINEL_PATH.split("/"))
    assert json.loads(target.read_text("utf-8"))["request_id"] == trigger.REQUEST_ID


def test_sentinel_commit_is_one_canonical_single_child_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = _repository(tmp_path)
    parent = _git(repository, "rev-parse", "HEAD")
    target = repository.joinpath(*trigger.SENTINEL_PATH.split("/"))
    target.parent.mkdir(parents=True)
    target.write_bytes(b'{"request_id":"fixture"}\n')
    after = _commit(repository, "fixture: add _013 only")
    monkeypatch.setattr(
        trigger,
        "_validate_request_impl",
        lambda repo, raw, *, source_head: {
            "raw": raw,
            "source_head": source_head,
        },
    )
    result = trigger.validate_sentinel_commit(
        repository, after, expected_parent=parent
    )
    assert result == {"raw": b'{"request_id":"fixture"}\n', "source_head": parent}

    (repository / "extra.txt").write_bytes(b"extra\n")
    target.unlink()
    target.write_bytes(b'{"request_id":"second"}\n')
    bad = _commit(repository, "fixture: non-exclusive mutation")
    with pytest.raises(trigger.DevelopmentTriggerError, match="exclusive _013"):
        trigger.validate_sentinel_commit(repository, bad)


def test_immutable_012_loader_pins_graph_blob_source_and_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = _repository(tmp_path)
    source = _git(repository, "rev-parse", "HEAD")
    sentinel = repository.joinpath(*trigger.PREVIOUS_SENTINEL_PATH.split("/"))
    sentinel.parent.mkdir(parents=True)
    value = {
        "request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012",
        "request_path": trigger.PREVIOUS_SENTINEL_PATH,
        "request_sha256": "sha256:" + "d" * 64,
        "schema": "trimem/development-tuning-branch-trigger/1.12",
        "source_head": source,
    }
    raw = trigger.canonical_bytes(value, trailing_lf=True)
    sentinel.write_bytes(raw)
    execution = _commit(repository, "fixture: exclusive _012")
    (repository / "descendant.txt").write_bytes(b"recovery\n")
    descendant = _commit(repository, "fixture: recovery source")
    mode, blob = _git(
        repository, "ls-tree", execution, "--", trigger.PREVIOUS_SENTINEL_PATH
    ).split("\t", 1)[0].split()[::2]
    assert mode == "100644"
    monkeypatch.setattr(trigger, "PREVIOUS_SOURCE_HEAD", source)
    monkeypatch.setattr(trigger, "PREVIOUS_EXECUTION_HEAD", execution)
    monkeypatch.setattr(trigger, "PREVIOUS_SENTINEL_BYTES", len(raw))
    monkeypatch.setattr(trigger, "PREVIOUS_SENTINEL_BLOB_OID", blob)
    monkeypatch.setattr(trigger, "PREVIOUS_SENTINEL_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(trigger, "PREVIOUS_REQUEST_PAYLOAD_SHA256", "d" * 64)
    assert trigger._load_previous_request(repository, descendant) == value

    sentinel.write_bytes(raw.replace(b"d" * 64, b"e" * 64))
    corrupted = _commit(repository, "fixture: corrupt history")
    with pytest.raises(trigger.DevelopmentTriggerError, match="changed after execution"):
        trigger._load_previous_request(repository, corrupted)


def test_failure_fixture_contract_is_exact_and_zero_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = ROOT / trigger.PREVIOUS_FAILURE_FIXTURE_PATH
    raw = path.read_bytes()
    monkeypatch.setattr(trigger, "commit_bytes", lambda *args: raw)
    result = trigger._validate_previous_run_fixture(ROOT, "f" * 40)
    assert result["workflow_run"]["id"] == 34_128_541_859
    assert result["actuals"]["model_api_calls"] == 0
    modified = deepcopy(result)
    modified["actuals"]["model_api_calls"] = 1
    bad = (json.dumps(modified, ensure_ascii=False, indent=2) + "\n").encode()
    monkeypatch.setattr(trigger, "commit_bytes", lambda *args: bad)
    with pytest.raises(trigger.DevelopmentTriggerError, match="failure fixture"):
        trigger._validate_previous_run_fixture(ROOT, "f" * 40)


def test_build_request_is_zero_authority_and_preserves_science(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    science = {"target_order": ["target"], "task_arm_runs": 72}
    bindings = {
        name: "sha256:" + hashlib.sha256(name.encode()).hexdigest()
        for name in trigger.EXECUTION_CONTRACT_PATHS
    }
    validated = {
        "bindings": bindings,
        "hard_cap": deepcopy(trigger.EXPECTED_DEVELOPMENT_HARD_CAP),
        "previous_request": {
            "control_plane": {"one_time_workflow_runs": 1},
            "exact_model": {
                "model_id": trigger.MODEL_ID,
                "reasoning_effort": trigger.REASONING_EFFORT,
            },
            "scientific_workload": science,
        },
    }
    monkeypatch.setattr(trigger, "resolve_repository_root", lambda path: path)
    monkeypatch.setattr(trigger, "_validate_source_impl", lambda *args: deepcopy(validated))
    monkeypatch.setattr(
        trigger,
        "_validate_remote_gate_evidence",
        lambda evidence, *, source_head: deepcopy(evidence),
    )
    monkeypatch.setattr(
        trigger,
        "_validate_runner_readiness",
        lambda evidence, *, source_head: deepcopy(evidence),
    )
    result = trigger.build_request(
        tmp_path,
        source_head="e" * 40,
        remote_gate_evidence={"gate": "PASS"},
        runner_readiness={"runner": "READY"},
    )
    assert result["actual_execution_authorized"] is False
    assert result["external_execution_approval_received"] is False
    assert result["scientific_workload"] == science
    assert result["pre_execution_actuals"]["paid_model_calls"] == 0
    unsigned = {key: value for key, value in result.items() if key != "request_sha256"}
    assert result["request_sha256"] == (
        "sha256:" + hashlib.sha256(trigger.canonical_bytes(unsigned)).hexdigest()
    )
