from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import threading

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_d123_loader_rehearsal as loader  # noqa: E402
import trimem_d123_reseal as reseal  # noqa: E402
import trimem_development_trigger_d122 as d122  # noqa: E402
import trimem_development_trigger_d123 as d123  # noqa: E402


def test_d123_exact_identity_and_credential_free_d122_receipt() -> None:
    assert d123.BASELINE_SOURCE_HEAD == (
        "cfa79b2406f174bd152eb873e98018725947d349"
    )
    assert d123.REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_022"
    assert d123.REQUEST_SCHEMA == "trimem/development-tuning-branch-trigger/1.23"
    assert d123.SENTINEL_PATH == (
        "artifacts/trimem_v1/exec_requests/"
        "DEVELOPMENT_TUNING_EXEC_REQUEST_022.json"
    )
    assert d123.AMENDMENT_STATUS == "READY_FOR_EXEC_022_REQUEST"
    assert d123.AMENDMENT_ENDPOINT == "TRIMEM_V1_READY_FOR_EXEC_022_REQUEST"
    assert d123.REQUIRED_EXTERNAL_AUTHORIZATION == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_022_APPROVED_ONCE"
    )
    assert d123.LOADER_REHEARSAL_COLLECTOR_PATH == (
        "scripts/trimem_d123_loader_rehearsal.py"
    )

    raw = (ROOT / d123.REMOTE_CI_EVIDENCE_PATH).read_bytes()
    assert len(raw) == d123.REMOTE_CI_EVIDENCE_BYTES == 2_090
    assert hashlib.sha256(raw).hexdigest() == d123.REMOTE_CI_EVIDENCE_SHA256
    evidence = d123.validate_remote_ci_evidence(ROOT)
    assert evidence["exact_head"] == d123.BASELINE_SOURCE_HEAD
    assert evidence["status"] == "PASS"
    assert evidence["credential_access"] is False
    assert evidence["benchmark_execution_runs"] == 0
    assert evidence["model_api_calls"] == 0
    assert evidence["paid_model_calls"] == 0
    assert len(evidence["required_workflows"]) == 6


def test_d123_context_propagates_and_restores_all_inherited_readers() -> None:
    modules = (d123.d121, d123.d120, d123.d119, d123.d118, d123.d115)
    names = (
        "REQUEST_ID",
        "REQUEST_SCHEMA",
        "SENTINEL_PATH",
        "LOADER_REHEARSAL_COLLECTOR_PATH",
    )
    before = {
        module: tuple(getattr(module, name) for name in names) for module in modules
    }

    with d123._d123_runtime_context():
        for module in modules:
            assert tuple(getattr(module, name) for name in names) == (
                d123.REQUEST_ID,
                d123.REQUEST_SCHEMA,
                d123.SENTINEL_PATH,
                d123.LOADER_REHEARSAL_COLLECTOR_PATH,
            )

    for module in modules:
        assert tuple(getattr(module, name) for name in names) == before[module]


def test_d123_nested_source_validation_context_reaches_d112_and_restores() -> None:
    names = (
        "REQUEST_ID",
        "REQUEST_SCHEMA",
        "STARTING_FREEZE_SHA256",
        "RUNNER_READINESS_SCHEMA",
    )
    before = tuple(getattr(d123.d112, name) for name in names)

    with (
        d123._d123_runtime_context(),
        d123.d114._d114_runtime_context(),
        d123.d113._d113_runtime_context(),
    ):
        assert tuple(getattr(d123.d112, name) for name in names) == (
            d123.REQUEST_ID,
            d123.REQUEST_SCHEMA,
            d123.STARTING_FREEZE_SHA256,
            d123.RUNNER_READINESS_SCHEMA,
        )

    assert tuple(getattr(d123.d112, name) for name in names) == before


def test_d123_context_waits_for_a_concurrent_historical_d121_context() -> None:
    attempted = threading.Event()
    entered = threading.Event()
    observations: list[str] = []

    def enter_d123() -> None:
        attempted.set()
        with d123._d123_runtime_context():
            observations.append(d123.d121.REQUEST_ID)
            entered.set()

    with d123.d121._d121_runtime_context():
        worker = threading.Thread(target=enter_d123, daemon=True)
        worker.start()
        assert attempted.wait(timeout=1)
        assert not entered.wait(timeout=0.2)
        assert d123.d121.REQUEST_ID == (
            "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_021"
        )

    assert entered.wait(timeout=2)
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert observations == [d123.REQUEST_ID]
    assert d123.d121.REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_021"


def test_d123_loader_adapter_runs_only_inside_the_d123_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_main(argv: list[str] | None = None) -> int:
        observed["argv"] = argv
        observed["request_id"] = d123.d121.REQUEST_ID
        observed["request_schema"] = d123.d121.REQUEST_SCHEMA
        observed["sentinel_path"] = d123.d121.SENTINEL_PATH
        observed["collector"] = d123.d121.LOADER_REHEARSAL_COLLECTOR_PATH
        return 17

    original = d123.d121.REQUEST_ID
    monkeypatch.setattr(loader.d115_collector, "main", fake_main)
    assert loader.main(["--credential-free-rehearsal"]) == 17
    assert observed == {
        "argv": ["--credential-free-rehearsal"],
        "request_id": d123.REQUEST_ID,
        "request_schema": d123.REQUEST_SCHEMA,
        "sentinel_path": d123.SENTINEL_PATH,
        "collector": d123.LOADER_REHEARSAL_COLLECTOR_PATH,
    }
    assert d123.d121.REQUEST_ID == original


def test_d123_preserves_the_exact_d122_baseline() -> None:
    baseline = d123.validate_d122_baseline(ROOT)
    assert baseline["source_head"] == d123.BASELINE_SOURCE_HEAD
    assert baseline["status"] == "PASS"
    assert baseline["request_021_attempt_one_consumed"] is True
    assert baseline["request_021_rerun_allowed"] is False
    assert baseline["request_022_creation_authorized"] is False
    assert baseline["request_022_execution_authorized"] is False
    assert baseline["historical_execution_actuals"] == (
        d122.HISTORICAL_EXECUTION_ACTUALS
    )
    assert baseline["current_execution_actuals"] == (
        d122.ZERO_CURRENT_EXECUTION_ACTUALS
    )


def test_d123_previous_run_fixture_binds_the_recorded_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = (ROOT / d123.PREVIOUS_FAILURE_FIXTURE_PATH).read_bytes()
    monkeypatch.setattr(d123, "commit_bytes", lambda *_args: raw)
    observed = d123._validate_previous_run_fixture(ROOT, "a" * 40)
    assert observed["workflow_run"]["id"] == d123.PREVIOUS_RUN_ID
    assert observed["workflow_run"]["attempt"] == d123.PREVIOUS_RUN_ATTEMPT


def test_d123_fresh_campaign_caps_and_nonreuse_are_exact() -> None:
    assert d123.FRESH_EXECUTION_CONTRACT == {
        "cross_run_resume_allowed": False,
        "grader_containers": 72,
        "historical_partial_cells_reused": 0,
        "input_token_cap": 36_004_096,
        "new_campaign_starts_at_sequence_zero": True,
        "output_token_cap": 4_720_640,
        "paid_model_call_cap": 1_873,
        "partial_candidate_checkpoint_selection_allowed": False,
        "protocol_canary_generation_calls": 1,
        "scientific_generation_call_cap": 1_872,
        "task_arm_runs": 72,
        "total_usd_hard_cap": 50.0,
    }
    assert all(value == 0 for value in d123.ZERO_CURRENT_EXECUTION_ACTUALS.values())
    assert d123.SENTINEL_PATH not in d123.ALLOWED_ACTIVATION_PATHS
    assert set(d123.PRESERVED_SCIENTIFIC_PATHS).isdisjoint(
        d123.ALLOWED_ACTIVATION_PATHS
    )

    source = d123.current_activation_record()
    child = d123.current_activation_record(request_created=True)
    assert source["request_022_creation_authorized"] is True
    assert source["request_022_created"] is False
    assert child["request_022_created"] is True
    for record in (source, child):
        assert record["actual_execution_authorized"] is False
        assert record["external_execution_approval_received"] is False
        assert record["request_022_created_in_source"] is False
        assert record["request_022_execution_authorized"] is False
        assert record["current_execution_actuals"] == (
            d123.ZERO_CURRENT_EXECUTION_ACTUALS
        )
        assert record["endpoint"] == d123.AMENDMENT_ENDPOINT
        assert record["status"] == d123.AMENDMENT_STATUS


def test_d123_reseal_artifacts_keep_creation_and_execution_authority_separate() -> None:
    amendment, inventory = reseal.build_artifacts(
        source_changed_paths=sorted(d123.REQUIRED_ACTIVATION_CHANGES)
    )
    assert amendment["schema"] == d123.AMENDMENT_SCHEMA
    assert inventory["schema"] == d123.INVENTORY_SCHEMA
    assert amendment["status"] == inventory["status"] == d123.AMENDMENT_STATUS
    assert amendment["endpoint"] == inventory["endpoint"] == (
        d123.AMENDMENT_ENDPOINT
    )
    assert amendment["pass_at_1"] is None
    assert amendment["performance_measured"] is False
    assert amendment["current_execution_actuals"] == (
        d123.ZERO_CURRENT_EXECUTION_ACTUALS
    )
    assert amendment["consumed_execution_actuals"] == (
        d122.HISTORICAL_EXECUTION_ACTUALS
    )

    authority = amendment["authority_boundary"]
    assert authority["request_021_attempt_one_consumed"] is True
    assert authority["request_021_rerun_allowed"] is False
    assert authority["request_022_creation_authorized"] is True
    assert authority["request_022_created_in_source"] is False
    assert authority["request_022_execution_authorized"] is False
    assert authority["external_execution_approval_received"] is False
    assert authority["development_execution_authorized"] is False
    assert authority["sentinel_contains_execution_authority"] is False
    assert authority["required_external_authorization"] == (
        d123.REQUIRED_EXTERNAL_AUTHORIZATION
    )
    assert amendment["implementation_sha256"] == inventory["implementation_sha256"]
    assert set(amendment["implementation_sha256"]) == (
        d123.IMPLEMENTATION_SEAL_PATHS
    )


def test_d123_optional_boundary_accepts_source_and_one_exact_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = "a" * 40
    child = "b" * 40

    monkeypatch.setattr(d123, "resolve_repository_root", lambda value: value)

    def source_git(_repository: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return source
        if args[:3] == ("log", "--format=%H", "--diff-filter=A"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(d123, "git", source_git)
    assert d123.validate_optional_exec_022_boundary(tmp_path) is None

    calls: list[tuple[str, str | None, bool]] = []

    def child_git(_repository: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return child
        if args[:3] == ("log", "--format=%H", "--diff-filter=A"):
            return child
        if args == ("rev-list", "--parents", "-n", "1", child):
            return f"{child} {source}"
        raise AssertionError(args)

    def validate_child(
        _repository: Path,
        after: str,
        *,
        expected_parent: str | None = None,
        require_checked_out_head: bool = True,
    ) -> dict[str, object]:
        calls.append((after, expected_parent, require_checked_out_head))
        return {"request_id": d123.REQUEST_ID}

    monkeypatch.setattr(d123, "git", child_git)
    monkeypatch.setattr(d123, "validate_sentinel_commit", validate_child)
    assert d123.validate_optional_exec_022_boundary(tmp_path) == child
    assert calls == [(child, source, True)]


def test_d123_optional_boundary_rejects_worktree_or_post_sentinel_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = "a" * 40
    old_child = "b" * 40
    later = "c" * 40
    monkeypatch.setattr(d123, "resolve_repository_root", lambda value: value)

    target = tmp_path.joinpath(*Path(d123.SENTINEL_PATH).parts)
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        d123,
        "git",
        lambda _repository, *args: source if args == ("rev-parse", "HEAD") else "",
    )
    with pytest.raises(d123.DevelopmentTriggerError, match="uncommitted `_022`"):
        d123.validate_optional_exec_022_boundary(tmp_path)

    target.unlink()

    def drift_git(_repository: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return later
        if args[:3] == ("log", "--format=%H", "--diff-filter=A"):
            return old_child
        raise AssertionError(args)

    monkeypatch.setattr(d123, "git", drift_git)
    with pytest.raises(d123.DevelopmentTriggerError, match="commits exist after"):
        d123.validate_optional_exec_022_boundary(tmp_path)


def test_d123_no_exec_guard_rejects_a_dangling_worktree_sentinel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = "a" * 40
    target = tmp_path.joinpath(*Path(d123.SENTINEL_PATH).parts)
    target.parent.mkdir(parents=True)
    try:
        target.symlink_to(tmp_path / "missing-request.json")
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable on this Windows host: {exc}")

    monkeypatch.setattr(d123, "resolve_repository_root", lambda value: value)

    def fake_git(_repository: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return source
        if args == (
            "log",
            "--format=%H",
            source,
            "--",
            d123.SENTINEL_PATH,
        ):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(d123, "git", fake_git)
    with pytest.raises(
        d123.DevelopmentTriggerError, match="working-tree `_022` exists"
    ):
        d123.validate_no_exec_022(tmp_path)


def test_d123_current_activation_marks_source_or_sentinel_without_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "a" * 40
    child = "b" * 40
    calls: list[tuple[str | None, bool]] = []
    monkeypatch.setattr(d123, "resolve_repository_root", lambda value: value)

    def validate_source(
        _repository: Path,
        source_head: str | None = None,
        *,
        require_checked_out_head: bool = True,
    ) -> dict[str, object]:
        calls.append((source_head, require_checked_out_head))
        return {"source_head": source_head}

    monkeypatch.setattr(d123, "validate_correction_source", validate_source)
    monkeypatch.setattr(d123, "validate_optional_exec_022_boundary", lambda _repo: None)
    monkeypatch.setattr(d123, "git", lambda _repo, *_args: source)
    source_result = d123.validate_current_activation(ROOT)
    assert calls.pop() == (source, True)
    assert source_result["request_022_created"] is False

    monkeypatch.setattr(
        d123, "validate_optional_exec_022_boundary", lambda _repo: child
    )
    monkeypatch.setattr(
        d123,
        "git",
        lambda _repo, *args: f"{child} {source}"
        if args == ("rev-list", "--parents", "-n", "1", child)
        else child,
    )
    child_result = d123.validate_current_activation(ROOT)
    assert calls.pop() == (source, False)
    assert child_result["request_022_created"] is True
    for result in (source_result, child_result):
        assert result["request_021_attempt_one_consumed"] is True
        assert result["request_021_rerun_allowed"] is False
        assert result["request_022_execution_authorized"] is False
        assert result["external_execution_approval_received"] is False


def test_d123_build_request_enters_context_and_keeps_the_no_sentinel_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "a" * 40
    observed: dict[str, object] = {}

    def no_exec(
        repository: Path,
        source_head: str | None = None,
        *,
        require_worktree_absent: bool = True,
    ) -> None:
        observed["no_exec"] = (
            repository,
            source_head,
            require_worktree_absent,
        )

    def build(
        repository: Path,
        *,
        source_head: str,
        remote_gate_evidence: object,
        runner_readiness: object,
        loader_rehearsal: object,
        checkout_rehearsal: object,
    ) -> dict[str, object]:
        observed["active_request_id"] = d123.d121.REQUEST_ID
        observed["payloads"] = (
            remote_gate_evidence,
            runner_readiness,
            loader_rehearsal,
            checkout_rehearsal,
        )
        return {"request_id": d123.REQUEST_ID, "source_head": source_head}

    payloads = ({"gate": 1}, {"runner": 2}, {"loader": 3}, {"checkout": 4})
    monkeypatch.setattr(d123, "validate_no_exec_022", no_exec)
    monkeypatch.setattr(d123, "_build_request_impl", build)
    result = d123.build_request(
        ROOT,
        source_head=source,
        remote_gate_evidence=payloads[0],
        runner_readiness=payloads[1],
        loader_rehearsal=payloads[2],
        checkout_rehearsal=payloads[3],
    )
    assert result == {"request_id": d123.REQUEST_ID, "source_head": source}
    assert observed["no_exec"] == (ROOT, source, True)
    assert observed["active_request_id"] == d123.REQUEST_ID
    assert observed["payloads"] == payloads


def test_d123_runner_and_matrix_edits_are_exact_reader_swaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "a" * 40
    old = b"from trimem_development_trigger_d121 import"
    new = b"from trimem_development_trigger_d123 import"
    baseline = {
        path: b"prefix\n" + old + b" thing\nsuffix\n"
        for path in (
            "scripts/trimem_benchmark_run.py",
            "scripts/trimem_benchmark_matrix.py",
        )
    }

    def exact_bytes(_repo: Path, commit: str, path: str) -> bytes:
        raw = baseline[path]
        return raw if commit == d123.BASELINE_SOURCE_HEAD else raw.replace(old, new)

    monkeypatch.setattr(d123, "commit_bytes", exact_bytes)
    d123._validate_active_reader_sources(ROOT, source)

    def drifted_bytes(_repo: Path, commit: str, path: str) -> bytes:
        raw = exact_bytes(_repo, commit, path)
        if commit == source and path == "scripts/trimem_benchmark_run.py":
            return raw + b"# unrelated drift\n"
        return raw

    monkeypatch.setattr(d123, "commit_bytes", drifted_bytes)
    with pytest.raises(d123.DevelopmentTriggerError, match="beyond import routing"):
        d123._validate_active_reader_sources(ROOT, source)


def test_d123_workflow_routes_exclusively_to_the_exact_022_reader() -> None:
    text = (ROOT / d123.EXPECTED_WORKFLOW_PATH).read_text(encoding="utf-8")
    assert text.count(d123.TRIGGER_PATH) == 8
    assert "scripts/trimem_development_trigger_d121.py" not in text
    assert "scripts/trimem_development_trigger_d122.py" not in text
    assert text.count(d123.SENTINEL_PATH) == 1
    assert text.count(d123.EXPECTED_CONCURRENCY_GROUP) == 1
    assert text.count("clean: true") == 3
    assert "actions/download-artifact" not in text
    assert "DEVELOPMENT_TUNING_EXEC_REQUEST_021.json" not in text


def test_d123_workflow_rejects_clean_moved_outside_a_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "a" * 40
    current = (ROOT / d123.EXPECTED_WORKFLOW_PATH).read_bytes()
    checkout = (
        b"        uses: actions/checkout@"
        b"11bd71901bbe5b1630ceea73d27597364c9af683\n"
        b"        with:\n"
        b"          clean: true\n"
        b"          fetch-depth: 0\n"
        b"          persist-credentials: false\n"
        b"          ref: ${{ github.sha }}\n"
    )
    without_clean = checkout.replace(b"          clean: true\n", b"")
    moved = current.replace(checkout, without_clean, 1).replace(
        b"        with:\n          python-version: 3.11.10\n",
        b"        with:\n          clean: true\n"
        b"          python-version: 3.11.10\n",
        1,
    )
    assert moved.count(b"clean: true") == 3

    monkeypatch.setattr(d123, "_D121_VALIDATE_WORKFLOW", lambda *_args: None)
    monkeypatch.setattr(
        d123,
        "commit_bytes",
        lambda _repo, commit, _path: moved if commit == source else b"unused",
    )
    with pytest.raises(
        d123.DevelopmentTriggerError,
        match="fresh EXEC-022 checkout isolation differs",
    ):
        d123._validate_workflow(ROOT, source)


def test_d123_report_and_receipt_have_zero_current_paid_activity() -> None:
    report = (ROOT / d123.REPORT_PATH).read_text(encoding="utf-8")
    for marker in (
        d123.BASELINE_SOURCE_HEAD,
        d123.AMENDMENT_ENDPOINT,
        "24 of 72",
        "paid/model calls = 0",
        "gpt-5.4-mini-2026-03-17",
        d123.REQUIRED_EXTERNAL_AUTHORIZATION,
        "not a benchmark score",
    ):
        assert marker in report

    receipt = json.loads(
        (ROOT / d123.REMOTE_CI_EVIDENCE_PATH).read_text(encoding="utf-8")
    )
    serialized = json.dumps(receipt, sort_keys=True)
    assert receipt["credential_access"] is False
    assert receipt["model_api_calls"] == receipt["paid_model_calls"] == 0
    for forbidden in ("OPENAI_API_KEY", "TRIMEM_EXEC_APPROVAL_B64", "sk-proj-"):
        assert forbidden not in serialized
