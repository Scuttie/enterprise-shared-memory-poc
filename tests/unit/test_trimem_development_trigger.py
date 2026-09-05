from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Callable

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_development_trigger_preflight as trigger  # noqa: E402
import trimem_exec_approval as approval_validator  # noqa: E402
import trimem_approved_phase as approved_phase  # noqa: E402
import trimem_benchmark_matrix as benchmark_matrix  # noqa: E402
import trimem_benchmark_run as benchmark_run  # noqa: E402
import trimem_freeze as freeze  # noqa: E402
import trimem_grader_smoke_failure_closure as smoke_failure_closure  # noqa: E402
import trimem_grader_smoke_failure_evidence as smoke_failure_evidence  # noqa: E402
import trimem_m2_candidates as m2_candidates  # noqa: E402
import trimem_multi_swe_probe_evidence as probe_evidence  # noqa: E402
import trimem_public_artifact as public_artifact  # noqa: E402


REAL_COLLECT_REMOTE_GATE_EVIDENCE = trigger.collect_remote_gate_evidence


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout.strip()


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _write_json(path: Path, value: object) -> bytes:
    raw = trigger.canonical_bytes(value, trailing_lf=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _initialize(repository: Path, *, bind_recovery_history: bool = True) -> str:
    repository.mkdir()
    _git(repository, "init", "-b", "codex/trimem-coder-v1")
    _git(repository, "config", "user.name", "TriMem Test")
    _git(repository, "config", "user.email", "trimem@example.invalid")
    if bind_recovery_history:
        objects = Path(_git(ROOT, "rev-parse", "--git-path", "objects"))
        if not objects.is_absolute():
            objects = ROOT / objects
        alternates = repository / ".git" / "objects" / "info" / "alternates"
        alternates.write_text(
            objects.resolve().as_posix() + "\n",
            encoding="utf-8",
            newline="\n",
        )
        _git(
            repository,
            "update-ref",
            "refs/heads/codex/trimem-coder-v1",
            trigger.PREVIOUS_EXECUTION_HEAD,
        )
    amendment = json.loads(
        (ROOT / trigger.MODEL_PRICING_AMENDMENT_PATH).read_text(encoding="utf-8")
    )
    candidates = json.loads(
        (ROOT / trigger.M2_CANDIDATE_MANIFEST_PATH).read_text(encoding="utf-8")
    )
    toolchain_amendment = json.loads(
        (ROOT / trigger.TOOLCHAIN_AMENDMENT_PATH).read_text(encoding="utf-8")
    )
    solve_budget_lock = json.loads(
        (ROOT / trigger.SOLVE_OUTPUT_BUDGET_LOCK_PATH).read_text(encoding="utf-8")
    )
    additional_paths = set(amendment["preserved_contracts"]["path_sha256"])
    additional_paths.update(
        toolchain_amendment["preserved_contracts"]["path_sha256"]
    )
    additional_paths.update(solve_budget_lock["implementation_sha256"])
    additional_paths.add(candidates["base_policy_path"])
    additional_paths.update(
        row["full_policy_path"] for row in candidates["candidates"]
    )
    paths = (
        set(trigger.BOUND_PATHS.values())
        | set(trigger.FREEZE_CLOSURE_PATHS)
        | set(trigger.EXPECTED_RECOVERY_INPUT_SHA256)
        | additional_paths
    ) - {trigger.FREEZE_PATH}
    for relative in sorted(paths):
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    closure = {}
    for relative in sorted(paths):
        raw = (repository / relative).read_bytes()
        closure[relative] = {
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    _write_json(
        repository / trigger.FREEZE_PATH,
        {
            "files": closure,
            "hash_algorithm": "sha256",
            "path_policy": (
                "explicit_allowlist_plus_hash_bound_event_blob_references_plus_"
                "conditional_probe_evidence_triad_no_tree_walk"
            ),
            "schema": "trimem/freeze/1.0",
        },
    )
    return _commit(repository, "frozen source")


def _rehash(value: dict[str, object]) -> None:
    payload = {key: child for key, child in value.items() if key != "request_sha256"}
    value["request_sha256"] = trigger.sha256_prefixed(trigger.canonical_bytes(payload))


def _remote_gate_evidence(
    source_head: str,
    *,
    conclusion: str = "success",
    run_attempt: int = 1,
) -> dict[str, object]:
    return {
        "all_required_workflows_passed": True,
        "observed_at_utc": "2026-09-03T14:00:00.000Z",
        "repository": trigger.EXPECTED_REPOSITORY,
        "schema": trigger.REMOTE_GATE_SCHEMA,
        "scientific_execution": {
            "api_calls": 0,
            "grader_runs": 0,
            "model_calls": 0,
            "paid_model_calls": 0,
            "target_image_pulls": 0,
            "task_arm_runs": 0,
            "total_usd": 0.0,
        },
        "source_head": source_head,
        "source_ref": trigger.EXPECTED_REF,
        "workflows": [
            {
                "conclusion": conclusion,
                "event": "push",
                "head_branch": trigger.EXPECTED_BRANCH,
                "head_sha": source_head,
                "html_url": (
                    "https://github.com/Scuttie/enterprise-shared-memory-poc/"
                    f"actions/runs/{10_000 + index}"
                ),
                "run_attempt": run_attempt,
                "run_id": 10_000 + index,
                "status": "completed",
                "workflow_path": path,
            }
            for index, path in enumerate(
                trigger.REQUIRED_REMOTE_GATE_WORKFLOWS, start=1
            )
        ],
    }


@pytest.fixture(autouse=True)
def _stub_live_remote_gate_collector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep unit tests credential-free while exercising the live comparison path."""

    monkeypatch.setattr(
        trigger,
        "collect_remote_gate_evidence",
        lambda source_head: deepcopy(_remote_gate_evidence(source_head)),
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["workflows"][0].__setitem__("conclusion", "failure"),
            "missing, red, rerun, or bound to another HEAD",
        ),
        (
            lambda value: value["workflows"][0].__setitem__("run_attempt", 2),
            "missing, red, rerun, or bound to another HEAD",
        ),
        (
            lambda value: value["workflows"][0].__setitem__("run_attempt", True),
            "missing, red, rerun, or bound to another HEAD",
        ),
        (
            lambda value: value["workflows"][0].__setitem__("head_sha", "f" * 40),
            "missing, red, rerun, or bound to another HEAD",
        ),
        (
            lambda value: value["workflows"].__setitem__(
                -1, deepcopy(value["workflows"][0])
            ),
            "missing, red, rerun, or bound to another HEAD",
        ),
    ],
    ids=["red", "attempt-two", "bool-attempt", "wrong-head", "duplicate-missing"],
)
def test_remote_gate_evidence_fails_closed(
    mutation: Callable[[dict[str, object]], None], message: str
) -> None:
    source_head = "a" * 40
    evidence = _remote_gate_evidence(source_head)
    mutation(evidence)
    with pytest.raises(trigger.DevelopmentTriggerError, match=message):
        trigger._validate_remote_gate_evidence(evidence, source_head=source_head)


def test_collector_binds_exact_pinned_gh_and_exact_workflow_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_head = "b" * 40
    fixture = _remote_gate_evidence(source_head)
    api_runs = [
        {
            "conclusion": row["conclusion"],
            "event": row["event"],
            "head_branch": row["head_branch"],
            "head_sha": row["head_sha"],
            "html_url": row["html_url"],
            "id": row["run_id"],
            "path": row["workflow_path"],
            "run_attempt": row["run_attempt"],
            "status": row["status"],
        }
        for row in fixture["workflows"]
    ]
    observed: list[tuple[object, Path]] = []
    monkeypatch.setattr(trigger.shutil, "which", lambda name: "/pinned/bin/gh")
    monkeypatch.setattr(trigger, "load_gh_cli_lock", lambda path: {"lock": str(path)})
    monkeypatch.setattr(
        trigger,
        "verify_installed_gh",
        lambda lock, path: observed.append((lock, path))
        or {"first_version_line": "gh version 2.97.0 (2026-07-31)"},
    )
    monkeypatch.setattr(
        trigger.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"workflow_runs": api_runs}).encode("utf-8"),
            stderr=b"",
        ),
    )

    result = REAL_COLLECT_REMOTE_GATE_EVIDENCE(source_head)

    assert result["workflows"] == fixture["workflows"]
    assert observed and observed[0][1] == Path("/pinned/bin/gh")


def test_collector_serializes_remote_query_timeout_as_contract_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(trigger.shutil, "which", lambda name: "/pinned/bin/gh")
    monkeypatch.setattr(trigger, "load_gh_cli_lock", lambda path: {})
    monkeypatch.setattr(
        trigger,
        "verify_installed_gh",
        lambda lock, path: {
            "first_version_line": "gh version 2.97.0 (2026-07-31)"
        },
    )
    monkeypatch.setattr(
        trigger.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd="gh api", timeout=60)
        ),
    )
    with pytest.raises(
        trigger.DevelopmentTriggerError, match="GitHub remote gate query failed"
    ):
        REAL_COLLECT_REMOTE_GATE_EVIDENCE("c" * 40)


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
        "GITHUB_REPOSITORY": trigger.EXPECTED_REPOSITORY,
        "GITHUB_REF": trigger.EXPECTED_REF,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": after,
        "GITHUB_WORKFLOW_REF": trigger.EXPECTED_WORKFLOW_REF,
        "GITHUB_WORKFLOW_SHA": after,
    }


def _isolated_cli_environment(environ: dict[str, str]) -> dict[str, str]:
    allowed_host_names = (
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "WINDIR",
    )
    isolated = {
        name: os.environ[name] for name in allowed_host_names if name in os.environ
    }
    isolated.update(environ)
    return isolated


def _trigger_repository(
    tmp_path: Path,
    *,
    mutate: Callable[[dict[str, object]], None] | None = None,
    extra_file: bool = False,
) -> tuple[Path, Path, str, str, dict[str, str]]:
    repository = tmp_path / "repository"
    before = _initialize(repository)
    request = trigger.build_request_document(
        repository,
        source_head=before,
        remote_gate_evidence=_remote_gate_evidence(before),
    )
    if mutate is not None:
        mutate(request)
        _rehash(request)
    _write_json(repository / trigger.SENTINEL_PATH, request)
    if extra_file:
        (repository / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    after = _commit(repository, "one-time DEV trigger")
    event_path = tmp_path / "event.json"
    _write_json(event_path, _event(before, after))
    return repository, event_path, before, after, _environment(after)


def test_only_exact_dev_sentinel_commit_passes(tmp_path: Path) -> None:
    repository, event_path, before, after, environ = _trigger_repository(tmp_path)
    result = trigger.validate_branch_trigger(repository, event_path, environ=environ)
    request_raw = (repository / trigger.SENTINEL_PATH).read_bytes()
    request = trigger.strict_json_object(request_raw)
    remote_gate_evidence = request["remote_gate_evidence"]
    assert result == {
        "actual_execution_authorized": False,
        "approved_freeze_sha256": trigger.strict_json_object(request_raw)["bindings"][
            "freeze_sha256"
        ],
        "approved_request_raw_sha256": trigger.sha256_prefixed(request_raw),
        "approved_grader_container_cap": 72,
        "approved_task_arm_run_count": 72,
        "grader_containers": 0,
        "model_calls": 0,
        "paid_model_calls": 0,
        "phase": "DEVELOPMENT_TUNING",
        "remote_gate_evidence_sha256": trigger.sha256_prefixed(
            trigger.canonical_bytes(remote_gate_evidence)
        ),
        "remote_gate_workflow_runs": {
            row["workflow_path"]: row["run_id"]
            for row in remote_gate_evidence["workflows"]
        },
        "request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_005",
        "request_payload_sha256": trigger.strict_json_object(request_raw)["request_sha256"],
        "requires_external_approval": True,
        "source_head": before,
        "status": "PASS",
        "task_arm_runs": 0,
        "total_usd": 0.0,
        "trigger_commit": after,
    }
    assert request["recovery_provenance"] == trigger.RECOVERY_PROVENANCE
    assert request["required_external_authorization"] == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_SOLVE_CONTRACT_RECOVERY_EXEC_APPROVED_ONCE"
    )
    assert request["recovery_provenance"]["received_recovery_authorization"] == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_SOLVE_CONTRACT_RECOVERY_EXEC_APPROVED_ONCE"
    )
    assert request["recovery_provenance"][
        "protected_execution_authorization_required"
    ] == request["required_external_authorization"]


def test_branch_trigger_rejects_fabricated_embedded_remote_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, event_path, before, _after, environ = _trigger_repository(tmp_path)
    live = deepcopy(_remote_gate_evidence(before))
    live["workflows"][0]["run_id"] = 90_001
    live["workflows"][0]["html_url"] = (
        "https://github.com/Scuttie/enterprise-shared-memory-poc/actions/runs/90001"
    )
    monkeypatch.setattr(
        trigger, "collect_remote_gate_evidence", lambda source_head: live
    )
    with pytest.raises(
        trigger.DevelopmentTriggerError,
        match="embedded remote gates differ from the live exact-head GitHub runs",
    ):
        trigger.validate_branch_trigger(repository, event_path, environ=environ)


def test_d12_preserved_contract_entry_cannot_be_deleted_and_resealed(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    _initialize(repository)
    amendment_path = repository / trigger.TOOLCHAIN_AMENDMENT_PATH
    amendment = json.loads(amendment_path.read_text(encoding="utf-8"))
    amendment["preserved_contracts"]["path_sha256"].pop(
        "configs/trimem_v1/model_lock.json"
    )
    amendment_raw = _write_json(amendment_path, amendment)
    freeze_path = repository / trigger.FREEZE_PATH
    freeze_document = json.loads(freeze_path.read_text(encoding="utf-8"))
    freeze_document["files"][trigger.TOOLCHAIN_AMENDMENT_PATH] = {
        "bytes": len(amendment_raw),
        "sha256": hashlib.sha256(amendment_raw).hexdigest(),
    }
    _write_json(freeze_path, freeze_document)
    source_head = _commit(repository, "remove preserved D1.2 binding and reseal")
    with pytest.raises(
        trigger.DevelopmentTriggerError, match="preserved-contract map differs"
    ):
        trigger.build_request_document(
            repository,
            source_head=source_head,
            remote_gate_evidence=_remote_gate_evidence(source_head),
        )


def test_workflow_triggers_only_on_exact_sentinel_path_and_dispatch() -> None:
    workflow = (ROOT / trigger.WORKFLOW_PATH).read_text(encoding="utf-8")
    trigger_block = workflow.split("on:\n", 1)[1].split("\nconcurrency:", 1)[0]
    assert trigger_block == (
        "  workflow_dispatch:\n"
        "  push:\n"
        "    branches:\n"
        "      - codex/trimem-coder-v1\n"
        "    paths:\n"
        "      - artifacts/trimem_v1/exec_requests/"
        "DEVELOPMENT_TUNING_EXEC_REQUEST_008.json\n"
    )
    assert "branch-trigger-preflight:" in workflow
    assert "needs: branch-trigger-preflight" in workflow
    assert workflow.count("github.run_attempt == 1") >= 2
    assert "group: trimem-v1-development-tuning-exec-008" in workflow
    assert "group: trimem-v1-development-tuning-exec-004" not in workflow
    assert "group: trimem-v1-development-tuning-exec-002" not in workflow
    assert "group: trimem-v1-development-tuning-exec-001" not in workflow
    assert "cancel-in-progress: false" in workflow
    preflight = workflow.split("  branch-trigger-preflight:", 1)[1].split(
        "  frozen-serial-phase:", 1
    )[0]
    assert "python -I -S scripts/trimem_freeze.py --check --require-git-tracked" in preflight
    assert "python -I -S scripts/trimem_development_trigger_d15.py" in preflight
    assert all(
        forbidden not in preflight
        for forbidden in (
            "secrets.",
            "environment:",
            "services:",
            "container:",
            "trimem_benchmark_run.py",
            "trimem_official_grader",
            "trimem_pull_locked_images.py",
        )
    )
    protected = workflow.split("  frozen-serial-phase:", 1)[1]
    public_upload = protected.split(
        "      - name: Upload public benchmark result", 1
    )[1].split("      - name: Inventory complete restricted benchmark evidence", 1)[0]
    assert "environment: trimem-benchmark-exec" in protected
    assert "ref: ${{ github.sha }}" in protected
    assert "artifacts/trimem_v1/benchmark_exec/*/public-results.json" in public_upload
    assert "development_selection/" not in public_upload
    assert "benchmark_exec/control/restricted-external-approval.json" in protected
    assert "steps.approval_materialization.outcome == 'success'" in protected
    assert "steps.encrypt_evidence.outcome == 'success'" in protected
    assert "INVENTORY_UPLOAD_OUTCOME" in protected
    assert (
        '[ "$RESTRICTED_UPLOAD_OUTCOME" != "success" ] || '
        '[ "$INVENTORY_UPLOAD_OUTCOME" != "success" ]'
    ) in protected
    assert "preserving plaintext and ciphertext" in protected


def test_static_ci_rehearses_preflight_before_dependency_install() -> None:
    workflow = (ROOT / ".github/workflows/ci-trimem.yml").read_text(encoding="utf-8")
    freeze_rehearsal = (
        "python -I -S scripts/trimem_freeze.py --check --require-git-tracked"
    )
    rehearsal = "python -I -S scripts/trimem_development_trigger_d15.py --help"
    install = "python -m pip install --require-hashes"
    assert workflow.count(freeze_rehearsal) == 1
    assert workflow.count(rehearsal) == 1
    assert workflow.index(freeze_rehearsal) < workflow.index(install)
    assert workflow.index(rehearsal) < workflow.index(install)


def test_freeze_path_literals_match_their_owner_modules() -> None:
    assert trigger.PREVIOUS_SENTINEL_PATH in freeze.ARTIFACT_PATHS
    assert freeze.PROBE_REQUEST_PATH == probe_evidence.PROBE_REQUEST_PATH
    assert freeze.PROBE_RESULT_PATH == probe_evidence.PROBE_RESULT_PATH
    assert freeze.PROBE_RECEIPT_PATH == probe_evidence.PROBE_RECEIPT_PATH
    assert (
        freeze.P014_FAILURE_RECEIPT_PATH
        == smoke_failure_evidence.FAILURE_RECEIPT_PATH
    )
    assert (
        freeze.P014_EVIDENCE_INVENTORY_PATH
        == smoke_failure_evidence.EVIDENCE_INVENTORY_PATH
    )
    assert (
        freeze.OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH
        == smoke_failure_closure.FAILURE_RECEIPT_PATH
    )
    assert (
        freeze.OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH
        == smoke_failure_closure.EVIDENCE_INVENTORY_PATH
    )


def test_recovery_receipt_binds_exact_historical_provider_terminal() -> None:
    raw = (ROOT / trigger.RECOVERY_FAILURE_RECEIPT_PATH).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == trigger.EXPECTED_RECOVERY_INPUT_SHA256[
        trigger.RECOVERY_FAILURE_RECEIPT_PATH
    ]
    receipt = trigger.strict_json_object(raw)
    assert receipt["workflow_run"]["id"] == trigger.RECOVERY_PROVENANCE[
        "failed_run_id"
    ]
    assert receipt["sentinel"]["raw_sha256"] == trigger.RECOVERY_PROVENANCE[
        "previous_request_raw_sha256"
    ]
    assert receipt["control_plane"]["protected_environment_worked"] is True
    assert receipt["approval"]["materialization_status"] == "PASS"
    assert receipt["jobs"]["protected_execution"]["failed_step"]["name"] == (
        "Execute frozen serial streams with one atomic phase ledger"
    )
    assert receipt["root_cause"]["terminal_classification"] == (
        "RESPONSE_INCOMPLETE_MAX_OUTPUT_TOKENS"
    )
    assert receipt["execution_accounting"]["completed_task_arm_runs"] == 0
    assert receipt["execution_accounting"]["model_calls"] == 6
    assert receipt["process_resume"]["additional_provider_calls"] == 0
    assert receipt["terminal_boundary"]["github_actions_attempt_2_created"] is False


def test_recovery_request_preserves_every_scientific_contract(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    source_head = _initialize(repository)
    recovered = trigger.build_request_document(
        repository,
        source_head=source_head,
        remote_gate_evidence=_remote_gate_evidence(source_head),
    )
    historical_raw = (ROOT / trigger.PREVIOUS_SENTINEL_PATH).read_bytes()
    assert hashlib.sha256(historical_raw).hexdigest() == (
        trigger.EXPECTED_RECOVERY_INPUT_SHA256[trigger.PREVIOUS_SENTINEL_PATH]
    )
    historical = trigger.strict_json_object(historical_raw)
    assert recovered["exact_model"]["model_id"] == historical["exact_model"]["model_id"]
    assert recovered["exact_model"]["reasoning_effort"] == "medium"
    assert recovered["expected_expenditure"] == historical["expected_expenditure"]
    assert recovered["scientific_workload"] == historical["scientific_workload"]
    assert recovered["hard_caps"]["output_tokens"] == 4_718_592
    assert historical["hard_caps"]["output_tokens"] == 4_718_592
    assert recovered["grader_smoke_rerun_authorized"] is False
    assert recovered["heldout_execution_authorized"] is False
    assert recovered["amendment_classification"] == (
        "PRE_RESULT_SOLVE_EXECUTION_CONTRACT_AMENDMENT"
    )
    assert recovered["pre_execution_actuals"]["api_calls"] == 7
    assert recovered["pre_execution_actuals"]["provider_reported_usage"] == (
        "MIXED_ONE_HISTORICAL_UNAVAILABLE_SIX_AVAILABLE"
    )


def test_benchmark_environment_snapshot_drift_is_rejected_even_if_resealed(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    _initialize(repository)
    environment_path = repository / trigger.BENCHMARK_ENVIRONMENT_PROTECTION_PATH
    environment = json.loads(environment_path.read_text(encoding="utf-8"))
    environment["environment"]["can_admins_bypass"] = True
    environment_raw = _write_json(environment_path, environment)
    freeze_path = repository / trigger.FREEZE_PATH
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    freeze["files"][trigger.BENCHMARK_ENVIRONMENT_PROTECTION_PATH] = {
        "bytes": len(environment_raw),
        "sha256": hashlib.sha256(environment_raw).hexdigest(),
    }
    _write_json(freeze_path, freeze)
    source_head = _commit(repository, "tampered environment reseal")
    with pytest.raises(
        trigger.DevelopmentTriggerError,
        match="protected environment snapshot differs",
    ):
        trigger.build_request_document(
            repository,
            source_head=source_head,
            remote_gate_evidence=_remote_gate_evidence(source_head),
        )


@pytest.mark.parametrize(
    "relative_path",
    [
        trigger.EARLIER_SENTINEL_PATH,
        trigger.EARLIER_FAILURE_RECEIPT_PATH,
        trigger.MIDDLE_SENTINEL_PATH,
        trigger.MIDDLE_FAILURE_RECEIPT_PATH,
        trigger.D12_SENTINEL_PATH,
        trigger.D12_FAILURE_RECEIPT_PATH,
        trigger.PREVIOUS_SENTINEL_PATH,
        trigger.RECOVERY_FAILURE_RECEIPT_PATH,
    ],
    ids=[
        "request-001",
        "failure-receipt-001",
        "request-002",
        "failure-receipt-002",
        "request-003",
        "failure-receipt-003",
        "request-004",
        "failure-receipt-004",
    ],
)
def test_historical_recovery_input_drift_is_rejected_even_if_resealed(
    tmp_path: Path, relative_path: str
) -> None:
    repository = tmp_path / "repository"
    _initialize(repository)
    changed_path = repository / relative_path
    changed_raw = changed_path.read_bytes() + b" "
    changed_path.write_bytes(changed_raw)
    freeze_path = repository / trigger.FREEZE_PATH
    freeze_document = json.loads(freeze_path.read_text(encoding="utf-8"))
    freeze_document["files"][relative_path] = {
        "bytes": len(changed_raw),
        "sha256": hashlib.sha256(changed_raw).hexdigest(),
    }
    _write_json(freeze_path, freeze_document)
    source_head = _commit(repository, "tampered historical recovery material")
    with pytest.raises(
        trigger.DevelopmentTriggerError,
        match="immutable DEV recovery input changed",
    ):
        trigger.build_request_document(
            repository,
            source_head=source_head,
            remote_gate_evidence=_remote_gate_evidence(source_head),
        )


def test_copied_recovery_material_without_immutable_git_history_is_rejected(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    source_head = _initialize(repository, bind_recovery_history=False)
    with pytest.raises(trigger.DevelopmentTriggerError, match="git verification failed"):
        trigger.build_request_document(
            repository,
            source_head=source_head,
            remote_gate_evidence=_remote_gate_evidence(source_head),
        )


def test_ordinary_branch_push_is_rejected(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    before = _initialize(repository)
    (repository / "ordinary.txt").write_text("ordinary\n", encoding="utf-8")
    after = _commit(repository, "ordinary push")
    event_path = tmp_path / "event.json"
    _write_json(event_path, _event(before, after))
    with pytest.raises(trigger.DevelopmentTriggerError, match="add only the exact DEV sentinel"):
        trigger.validate_branch_trigger(
            repository, event_path, environ=_environment(after)
        )


def test_sentinel_plus_another_file_is_rejected(tmp_path: Path) -> None:
    repository, event_path, _before, after, environ = _trigger_repository(
        tmp_path, extra_file=True
    )
    with pytest.raises(trigger.DevelopmentTriggerError, match="add only"):
        trigger.validate_branch_trigger(repository, event_path, environ=environ)


def test_modified_existing_sentinel_is_rejected(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    base = _initialize(repository)
    request = trigger.build_request_document(
        repository,
        source_head=base,
        remote_gate_evidence=_remote_gate_evidence(base),
    )
    _write_json(repository / trigger.SENTINEL_PATH, request)
    before = _commit(repository, "first sentinel")
    (repository / trigger.SENTINEL_PATH).write_bytes(
        (repository / trigger.SENTINEL_PATH).read_bytes() + b" "
    )
    after = _commit(repository, "modify sentinel")
    event_path = tmp_path / "event.json"
    _write_json(event_path, _event(before, after))
    with pytest.raises(trigger.DevelopmentTriggerError, match="add only"):
        trigger.validate_branch_trigger(
            repository, event_path, environ=_environment(after)
        )


def test_merge_commit_is_rejected(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    base = _initialize(repository)
    _git(repository, "switch", "-c", "side")
    (repository / "side.txt").write_text("side\n", encoding="utf-8")
    _commit(repository, "side")
    _git(repository, "switch", "codex/trimem-coder-v1")
    request = trigger.build_request_document(
        repository,
        source_head=base,
        remote_gate_evidence=_remote_gate_evidence(base),
    )
    _write_json(repository / trigger.SENTINEL_PATH, request)
    before = _commit(repository, "sentinel")
    _git(repository, "merge", "--no-ff", "side", "-m", "merge")
    after = _git(repository, "rev-parse", "HEAD")
    event_path = tmp_path / "event.json"
    _write_json(event_path, _event(before, after))
    with pytest.raises(trigger.DevelopmentTriggerError, match="exactly one parent"):
        trigger.validate_branch_trigger(
            repository, event_path, environ=_environment(after)
        )


def test_wrong_push_parent_is_rejected(tmp_path: Path) -> None:
    repository, event_path, _before, after, environ = _trigger_repository(tmp_path)
    wrong = "a" * 40
    _write_json(event_path, _event(wrong, after))
    with pytest.raises(trigger.DevelopmentTriggerError, match="push before SHA"):
        trigger.validate_branch_trigger(repository, event_path, environ=environ)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("created", True, "branch-creation"),
        ("deleted", True, "branch-deletion"),
        ("forced", True, "forced pushes"),
        ("ref", "refs/heads/main", "push ref"),
        ("repository", {"full_name": "someone/else"}, "repository identity"),
    ],
)
def test_wrong_event_identity_is_rejected(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    repository, event_path, before, after, environ = _trigger_repository(tmp_path)
    event = _event(before, after)
    event[field] = value
    _write_json(event_path, event)
    with pytest.raises(trigger.DevelopmentTriggerError, match=message):
        trigger.validate_branch_trigger(repository, event_path, environ=environ)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("GITHUB_REPOSITORY", "someone/else", "GITHUB_REPOSITORY"),
        ("GITHUB_REF", "refs/heads/main", "GITHUB_REF"),
        ("GITHUB_SHA", "a" * 40, "GITHUB_SHA"),
        ("GITHUB_WORKFLOW_REF", "someone/else/workflow.yml@refs/heads/main", "GITHUB_WORKFLOW_REF"),
        ("GITHUB_WORKFLOW_SHA", "b" * 40, "GITHUB_WORKFLOW_SHA"),
    ],
)
def test_wrong_actions_environment_identity_is_rejected(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    repository, event_path, _before, _after, environ = _trigger_repository(tmp_path)
    changed = {**environ, field: value}
    with pytest.raises(trigger.DevelopmentTriggerError, match=message):
        trigger.validate_branch_trigger(repository, event_path, environ=changed)


def test_multi_commit_push_is_rejected(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    before = _initialize(repository)
    (repository / "intermediate.txt").write_text("intermediate\n", encoding="utf-8")
    source_head = _commit(repository, "intermediate source")
    request = trigger.build_request_document(
        repository,
        source_head=source_head,
        remote_gate_evidence=_remote_gate_evidence(source_head),
    )
    _write_json(repository / trigger.SENTINEL_PATH, request)
    after = _commit(repository, "sentinel")
    event_path = tmp_path / "event.json"
    _write_json(event_path, _event(before, after))
    with pytest.raises(trigger.DevelopmentTriggerError, match="push before SHA"):
        trigger.validate_branch_trigger(
            repository, event_path, environ=_environment(after)
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value.__setitem__("phase", "HELDOUT_BENCHMARK"),
            "phase is not DEVELOPMENT_TUNING",
        ),
        (
            lambda value: value["exact_model"].__setitem__("model_id", "gpt-5.4-2026-03-05"),
            "content differs",
        ),
        (
            lambda value: value["bindings"].__setitem__("freeze_sha256", "sha256:" + "0" * 64),
            "content differs",
        ),
        (
            lambda value: value["bindings"].__setitem__(
                "development_manifest_sha256", "sha256:" + "1" * 64
            ),
            "content differs",
        ),
        (
            lambda value: value["scientific_workload"].__setitem__("task_arm_runs", 71),
            "content differs",
        ),
        (lambda value: value["hard_caps"].__setitem__("total_usd", 49.0), "content differs"),
        (lambda value: value["hard_caps"].__setitem__("total_usd", 51.0), "content differs"),
    ],
    ids=[
        "wrong-phase",
        "wrong-model",
        "wrong-freeze",
        "wrong-manifest",
        "wrong-task-count",
        "usd-under-contract",
        "usd-over-contract",
    ],
)
def test_request_drift_is_rejected(
    tmp_path: Path,
    mutate: Callable[[dict[str, object]], None],
    message: str,
) -> None:
    repository, event_path, _before, after, environ = _trigger_repository(
        tmp_path, mutate=mutate
    )
    with pytest.raises(trigger.DevelopmentTriggerError, match=message):
        trigger.validate_branch_trigger(repository, event_path, environ=environ)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["pre_execution_actuals"].__setitem__("grader_containers", False),
        lambda value: value["hard_caps"].__setitem__("total_usd", 50),
    ],
    ids=["bool-equals-zero-in-python", "integer-equals-float-in-python"],
)
def test_python_equal_but_byte_distinct_scalars_are_rejected(
    tmp_path: Path, mutate: Callable[[dict[str, object]], None]
) -> None:
    repository = tmp_path / "repository"
    before = _initialize(repository)
    request = trigger.build_request_document(
        repository,
        source_head=before,
        remote_gate_evidence=_remote_gate_evidence(before),
    )
    mutate(request)
    # Deliberately retain the old payload hash: Python dict equality considers
    # False == 0 and 50 == 50.0, while the committed JSON bytes are different.
    _write_json(repository / trigger.SENTINEL_PATH, request)
    after = _commit(repository, "type-confused DEV trigger")
    event_path = tmp_path / "event.json"
    _write_json(event_path, _event(before, after))
    with pytest.raises(trigger.DevelopmentTriggerError, match="scalar types differ"):
        trigger.validate_branch_trigger(
            repository, event_path, environ=_environment(after)
        )


def test_preflight_reads_no_secret(tmp_path: Path) -> None:
    repository, event_path, _before, after, environ = _trigger_repository(tmp_path)
    workflow = (repository / trigger.WORKFLOW_PATH).read_text(encoding="utf-8")
    preflight = workflow.split("  branch-trigger-preflight:", 1)[1].split(
        "  frozen-serial-phase:", 1
    )[0]
    assert "secrets." not in preflight
    assert "environment:" not in preflight
    assert "OPENAI_API_KEY" not in preflight
    exposed = {**environ, "OPENAI_API_KEY": "must-not-be-readable"}
    with pytest.raises(trigger.DevelopmentTriggerError, match="secret is exposed"):
        trigger.validate_branch_trigger(repository, event_path, environ=exposed)


def test_exact_preflight_cli_fails_closed_without_pinned_gh(tmp_path: Path) -> None:
    repository, event_path, _before, _after, environ = _trigger_repository(tmp_path)
    git = shutil.which("git")
    assert git is not None
    isolated = _isolated_cli_environment(environ)
    isolated["PATH"] = str(Path(git).parent)
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(repository / trigger.PREFLIGHT_PATH),
            "--repository",
            str(repository),
            "--event-path",
            str(event_path),
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        env=isolated,
        check=False,
    )
    assert completed.returncode == 1, completed.stderr
    assert completed.stdout, completed.stderr
    report = json.loads(completed.stdout)
    assert report["status"] == "FAIL_CLOSED"
    assert report["error"] in {
        "gh CLI is required to verify remote gates",
        "remote gate observer does not match the pinned gh byte lock",
    }


def test_isolated_base_python_cli_rejects_attempt_two(tmp_path: Path) -> None:
    repository, event_path, _before, _after, environ = _trigger_repository(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(repository / trigger.PREFLIGHT_PATH),
            "--repository",
            str(repository),
            "--event-path",
            str(event_path),
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        env=_isolated_cli_environment({**environ, "GITHUB_RUN_ATTEMPT": "2"}),
        check=False,
    )
    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["status"] == "FAIL_CLOSED"
    assert "rerun attempt" in report["error"]


def test_workflow_attempt_two_is_rejected_before_environment(tmp_path: Path) -> None:
    repository, event_path, _before, _after, environ = _trigger_repository(tmp_path)
    attempt_two = {**environ, "GITHUB_RUN_ATTEMPT": "2"}
    with pytest.raises(trigger.DevelopmentTriggerError, match="rerun attempt"):
        trigger.validate_branch_trigger(repository, event_path, environ=attempt_two)


def test_heldout_approval_cannot_enter_development(tmp_path: Path) -> None:
    repository, _event_path, before, after, _environ = _trigger_repository(tmp_path)
    request_raw = (repository / trigger.SENTINEL_PATH).read_bytes()
    request = trigger.strict_json_object(request_raw)
    policy = json.loads((repository / trigger.POLICY_REQUEST_PATH).read_text(encoding="utf-8"))
    hard = json.loads((repository / trigger.COST_PLAN_PATH).read_text(encoding="utf-8"))[
        "phase_hard_caps"
    ][trigger.EXPECTED_PHASE]
    document = approval_validator.build_external_approval_document(
        request_id=trigger.REQUEST_ID,
        request_sha256=hashlib.sha256(request_raw).hexdigest(),
        git_commit=after,
        source_git_commit=before,
        freeze_sha256=hashlib.sha256(
            (repository / trigger.FREEZE_PATH).read_bytes()
        ).hexdigest(),
        phase="HELDOUT_BENCHMARK",
        task_arm_runs=72,
        paid_model_call_cap=1873,
        input_token_cap=36_004_096,
        output_token_cap=4_720_640,
        currency_hard_cap=50.0,
        grader_containers=72,
        workflow_run_id=123,
        workflow_run_attempt=1,
        legal_terms_acceptance=True,
        approval_actor="test-actor",
        approval_timestamp="2026-09-03T00:00:00Z",
    )
    with pytest.raises(approval_validator.ApprovalValidationError, match="phase mismatch"):
        approval_validator.validate_external_approval_document(
            document,
            request=request,
            policy_request=policy,
            phase=trigger.EXPECTED_PHASE,
            hard_cap=hard,
            request_sha256=hashlib.sha256(request_raw).hexdigest(),
            freeze_sha256=hashlib.sha256(
                (repository / trigger.FREEZE_PATH).read_bytes()
            ).hexdigest(),
            git_head=after,
            source_head=before,
            workflow_run_id="123",
            workflow_run_attempt="1",
            now=datetime(2026, 9, 3, 1, tzinfo=timezone.utc),
        )


def test_push_route_rejects_heldout_before_generic_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "approval.json"
    _write_json(path, {"approval": {"approved_phase": "HELDOUT_BENCHMARK"}})
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setattr(
        approved_phase,
        "validate_exec_approval",
        lambda *_args, **_kwargs: pytest.fail("generic HELDOUT validation was reached"),
    )
    with pytest.raises(
        approved_phase.BenchmarkExecutionError,
        match="accepts only DEVELOPMENT_TUNING",
    ):
        approved_phase.approved_name(path)


def test_approved_phase_cli_serializes_benchmark_execution_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    approval_path = tmp_path / "approval.json"
    _write_json(approval_path, {"approval": {"approved_phase": "UNKNOWN"}})
    monkeypatch.setattr(
        sys,
        "argv",
        ["trimem_approved_phase.py", "--approval-file", str(approval_path)],
    )

    assert approved_phase.main() == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert captured.err == ""
    assert report == {
        "error": "external approval phase is unknown",
        "status": "FAIL",
    }


def test_generic_request_cannot_authorize_development() -> None:
    request = json.loads(
        (ROOT / trigger.POLICY_REQUEST_PATH).read_text(encoding="utf-8")
    )
    hard = json.loads(
        (ROOT / trigger.COST_PLAN_PATH).read_text(encoding="utf-8")
    )["phase_hard_caps"][trigger.EXPECTED_PHASE]
    request_sha256 = "a" * 64
    freeze_sha256 = "b" * 64
    git_head = "c" * 40
    document = approval_validator.build_external_approval_document(
        request_id=request["request_id"],
        request_sha256=request_sha256,
        git_commit=git_head,
        freeze_sha256=freeze_sha256,
        phase=trigger.EXPECTED_PHASE,
        task_arm_runs=hard["task_arm_runs"],
        paid_model_call_cap=hard["paid_model_calls"],
        input_token_cap=hard["input_tokens"],
        output_token_cap=hard["output_tokens"],
        currency_hard_cap=hard["total_usd"],
        grader_containers=hard["benchmark_grader_containers"],
        workflow_run_id=123,
        workflow_run_attempt=1,
        legal_terms_acceptance=True,
        approval_actor="test-actor",
        approval_timestamp="2026-09-03T00:00:00Z",
    )

    with pytest.raises(
        approval_validator.ApprovalValidationError,
        match="exact phase-bearing request",
    ):
        approval_validator.validate_external_approval_document(
            document,
            request=request,
            policy_request=request,
            phase=trigger.EXPECTED_PHASE,
            hard_cap=hard,
            request_sha256=request_sha256,
            freeze_sha256=freeze_sha256,
            git_head=git_head,
            workflow_run_id="123",
            workflow_run_attempt="1",
            now=datetime(2026, 9, 3, 1, tzinfo=timezone.utc),
        )


def test_development_external_approval_binds_two_heads_and_attempt_one(
    tmp_path: Path,
) -> None:
    repository, _event_path, source_head, execution_head, _environ = _trigger_repository(
        tmp_path
    )
    request_raw = (repository / trigger.SENTINEL_PATH).read_bytes()
    request = trigger.strict_json_object(request_raw)
    policy = json.loads((repository / trigger.POLICY_REQUEST_PATH).read_text(encoding="utf-8"))
    hard = json.loads((repository / trigger.COST_PLAN_PATH).read_text(encoding="utf-8"))[
        "phase_hard_caps"
    ][trigger.EXPECTED_PHASE]
    freeze_sha256 = hashlib.sha256(
        (repository / trigger.FREEZE_PATH).read_bytes()
    ).hexdigest()
    request_sha256 = hashlib.sha256(request_raw).hexdigest()
    document = approval_validator.build_external_approval_document(
        request_id=trigger.REQUEST_ID,
        request_sha256=request_sha256,
        git_commit=execution_head,
        source_git_commit=source_head,
        freeze_sha256=freeze_sha256,
        phase=trigger.EXPECTED_PHASE,
        task_arm_runs=72,
        paid_model_call_cap=1873,
        input_token_cap=36_004_096,
        output_token_cap=4_720_640,
        currency_hard_cap=50.0,
        grader_containers=72,
        workflow_run_id=987654321,
        workflow_run_attempt=1,
        legal_terms_acceptance=True,
        approval_actor="test-actor",
        approval_timestamp="2026-09-03T00:00:00Z",
    )
    arguments = {
        "request": request,
        "policy_request": policy,
        "phase": trigger.EXPECTED_PHASE,
        "hard_cap": hard,
        "request_sha256": request_sha256,
        "freeze_sha256": freeze_sha256,
        "git_head": execution_head,
        "source_head": source_head,
        "workflow_run_id": "987654321",
        "workflow_run_attempt": "1",
        "now": datetime(2026, 9, 3, 1, tzinfo=timezone.utc),
    }
    validated = approval_validator.validate_external_approval_document(
        document, **arguments
    )
    assert validated["approved_git_commit"] == execution_head
    assert validated["approved_source_git_commit"] == source_head

    cases = [
        ("approved_git_commit", "a" * 40, "execution HEAD"),
        ("approved_source_git_commit", "b" * 40, "sentinel parent"),
        ("approved_freeze_sha256", "c" * 64, "freeze digest"),
        ("approved_phase", "HELDOUT_BENCHMARK", "phase mismatch"),
        ("approved_paid_model_call_cap", 1871, "approved_paid_model_call_cap"),
        ("approved_workflow_run_id", 123, "run ID"),
        ("approved_workflow_run_attempt", 2, "attempt"),
        ("approved_legal_terms_acceptance", False, "terms"),
    ]
    for field, bad_value, message in cases:
        changed = deepcopy(document)
        changed["approval"][field] = bad_value
        with pytest.raises(approval_validator.ApprovalValidationError, match=message):
            approval_validator.validate_external_approval_document(
                changed, **arguments
            )

    wrong_request = deepcopy(document)
    wrong_request["approved_request_sha256"] = "d" * 64
    with pytest.raises(
        approval_validator.ApprovalValidationError,
        match="committed request bytes",
    ):
        approval_validator.validate_external_approval_document(
            wrong_request, **arguments
        )


def test_development_approval_evidence_round_trips_runner_aggregate_and_public(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, _event_path, source_head, execution_head, _environ = _trigger_repository(
        tmp_path
    )
    request_path = repository / trigger.SENTINEL_PATH
    request_raw = request_path.read_bytes()
    request = trigger.strict_json_object(request_raw)
    policy = json.loads((repository / trigger.POLICY_REQUEST_PATH).read_text(encoding="utf-8"))
    hard = json.loads((repository / trigger.COST_PLAN_PATH).read_text(encoding="utf-8"))[
        "phase_hard_caps"
    ][trigger.EXPECTED_PHASE]
    freeze_sha256 = hashlib.sha256(
        (repository / trigger.FREEZE_PATH).read_bytes()
    ).hexdigest()
    request_sha256 = hashlib.sha256(request_raw).hexdigest()
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    document = approval_validator.build_external_approval_document(
        request_id=trigger.REQUEST_ID,
        request_sha256=request_sha256,
        git_commit=execution_head,
        source_git_commit=source_head,
        freeze_sha256=freeze_sha256,
        phase=trigger.EXPECTED_PHASE,
        task_arm_runs=72,
        paid_model_call_cap=1873,
        input_token_cap=36_004_096,
        output_token_cap=4_720_640,
        currency_hard_cap=50.0,
        grader_containers=72,
        workflow_run_id=246813579,
        workflow_run_attempt=1,
        legal_terms_acceptance=True,
        approval_actor="test-actor",
        approval_timestamp=timestamp,
    )
    approval_path = tmp_path / "external-approval.json"
    approval_raw = _write_json(approval_path, document)
    approval_validator.validate_external_approval_document(
        document,
        request=request,
        policy_request=policy,
        phase=trigger.EXPECTED_PHASE,
        hard_cap=hard,
        request_sha256=request_sha256,
        freeze_sha256=freeze_sha256,
        git_head=execution_head,
        source_head=source_head,
        workflow_run_id="246813579",
        workflow_run_attempt="1",
    )
    validated = {
        "approval_artifact_sha256": hashlib.sha256(approval_raw).hexdigest(),
        "approved_request_sha256": request_sha256,
        "approved_workflow_run_id": "246813579",
        "approved_workflow_run_attempt": "1",
        "freeze_sha256": freeze_sha256,
        "git_head": execution_head,
        "source_head": source_head,
        "phase": trigger.EXPECTED_PHASE,
    }
    results = repository / "artifacts/trimem_v1/benchmark_exec/development"
    results.mkdir(parents=True)
    public_binding = benchmark_run.write_external_approval_evidence(
        results,
        split="development",
        approval_path=approval_path,
        validated=validated,
    )
    assert set(public_binding) == {
        "approval_artifact_sha256",
        "approved_request_sha256",
        "approved_workflow_run_id",
        "approved_workflow_run_attempt",
        "freeze_sha256",
        "git_head",
        "phase",
        "source_head",
    }
    monkeypatch.setattr(benchmark_matrix, "ROOT", repository)
    monkeypatch.setenv("GITHUB_RUN_ID", "246813579")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    aggregated = benchmark_matrix._approval_binding("development", results)
    assert aggregated == public_artifact.validate_public_approval_binding(
        aggregated,
        manifest="development",
    )
    assert aggregated["source_head"] == source_head

    wrong_phase = {**aggregated, "phase": "HELDOUT_BENCHMARK"}
    with pytest.raises(
        public_artifact.PublicArtifactError,
        match="phase differs from manifest",
    ):
        public_artifact.validate_public_approval_binding(
            wrong_phase,
            manifest="development",
        )

    for field, value in (
        ("approved_workflow_run_id", "0"),
        ("approved_workflow_run_id", 246813579),
        ("approved_workflow_run_attempt", "0"),
        ("approved_workflow_run_attempt", 1),
    ):
        malformed = {**aggregated, field: value}
        with pytest.raises(
            public_artifact.PublicArtifactError,
            match=f"invalid {field}",
        ):
            public_artifact.validate_public_approval_binding(
                malformed,
                manifest="development",
            )

    attempt_two = {**aggregated, "approved_workflow_run_attempt": "2"}
    with pytest.raises(
        public_artifact.PublicArtifactError,
        match="workflow run attempt 1",
    ):
        public_artifact.validate_public_approval_binding(
            attempt_two,
            manifest="development",
        )


def _public_selection_aggregate() -> dict[str, object]:
    rows = []
    resolved = {"baseline": 2, "precision": 3, "recall": 3, "balanced": 3}
    tokens = {"baseline": 1000, "precision": 950, "recall": 950, "balanced": 900}
    for index, candidate_id in enumerate(m2_candidates.CANDIDATE_IDS):
        rows.append(
            {
                "candidate_id": candidate_id,
                "completed_target_count": 12,
                "final_resume_cursor": 12,
                "resolved_count": resolved[candidate_id],
                "actual_total_tokens": tokens[candidate_id],
                "actual_usd": f"{1 + index / 10:.12f}",
                "sequence_sha256": "a" * 64,
                "runtime_lock_sha256": "sha256:" + "b" * 64,
                "m2_policy_manifest_sha256": "sha256:" + "c" * 64,
                "checkpoint_source_path": f"candidate-{candidate_id}.json",
                "checkpoint_source_file_sha256": "d" * 64,
                "checkpoint_digest": "sha256:" + "e" * 64,
                "namespace": f"candidate-{candidate_id}",
            }
        )
    selection = m2_candidates.select_development_candidate(rows)
    evidence = {
        "schema": "trimem/development-m2-selection-evidence/1.0",
        "status": "COMPLETE_PENDING_COMMIT_FREEZE_AND_HELDOUT_APPROVAL",
        "candidate_bundle_sha256": "sha256:" + hashlib.sha256(
            public_artifact._canonical(m2_candidates.load_bundle())
        ).hexdigest(),
        "candidate_summaries": rows,
        "selection": selection,
    }
    return {
        "development_selection": evidence,
        "development_selection_sha256": hashlib.sha256(
            public_artifact._canonical(evidence)
        ).hexdigest(),
        "restricted_selection_artifact_hashes": {
            "development_selection_evidence_sha256": "1" * 64,
            "selected_m2_checkpoint_sha256": "2" * 64,
            "selected_m2_proposal_sha256": "3" * 64,
        },
        "selected_candidate_id": selection["selected_candidate_id"],
    }


def test_restricted_selection_promotion_is_exactly_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "promotion-repository"
    results = repository / "artifacts/trimem_v1/benchmark_exec/development"
    promotion = repository / "artifacts/trimem_v1/development_selection"
    results.mkdir(parents=True)
    promotion.mkdir(parents=True)
    monkeypatch.setattr(benchmark_matrix, "ROOT", repository)

    rows = []
    summaries = []
    for index, candidate_id in enumerate(m2_candidates.CANDIDATE_IDS):
        checkpoint = {"digest": "sha256:" + f"{index + 1:x}" * 64}
        source = results / f"M2-{candidate_id}.post-development-frozen-checkpoint.json"
        source_raw = _write_json(source, checkpoint)
        rows.append(
            {
                "candidate_id": candidate_id,
                "completed_target_count": 12,
                "final_resume_cursor": 12,
                "resolved_count": index,
                "actual_total_tokens": 1000 - index,
                "actual_usd": f"{1 + index / 10:.12f}",
                "sequence_sha256": "a" * 64,
                "runtime_lock_sha256": "sha256:" + "b" * 64,
                "m2_policy_manifest_sha256": "sha256:" + "c" * 64,
                "checkpoint_source_path": source.relative_to(repository).as_posix(),
                "checkpoint_source_file_sha256": hashlib.sha256(source_raw).hexdigest(),
                "checkpoint_digest": checkpoint["digest"],
                "namespace": f"candidate-{candidate_id}",
            }
        )
        summaries.append(
            {
                "arm": f"M2-{candidate_id}",
                "candidate_id": candidate_id,
                "selected_checkpoint": checkpoint,
            }
        )
    selection = m2_candidates.select_development_candidate(rows)
    selected_id = selection["selected_candidate_id"]
    evidence = {
        "schema": "trimem/development-m2-selection-evidence/1.0",
        "status": "COMPLETE_PENDING_COMMIT_FREEZE_AND_HELDOUT_APPROVAL",
        "candidate_bundle_sha256": "sha256:" + hashlib.sha256(
            benchmark_matrix._canonical(m2_candidates.load_bundle())
        ).hexdigest(),
        "candidate_summaries": rows,
        "selection": selection,
    }
    evidence_raw = _write_json(
        promotion / "development_selection_evidence.json", evidence
    )
    selected_source = repository / next(
        row["checkpoint_source_path"]
        for row in rows
        if row["candidate_id"] == selected_id
    )
    checkpoint_path = promotion / "selected_m2_checkpoint.json"
    checkpoint_raw = selected_source.read_bytes()
    checkpoint_path.write_bytes(checkpoint_raw)
    checkpoint = json.loads(checkpoint_raw)
    candidate = m2_candidates.candidate_row(selected_id)
    proposal = {
        "schema": "trimem/selected-m2/1.0",
        "status": "FROZEN_AFTER_DEVELOPMENT",
        "candidate_bundle_path": "configs/trimem_v1/m2_candidate_bundles.json",
        "selected_candidate_id": selected_id,
        "selected_full_policy_path": candidate["full_policy_path"],
        "selected_full_policy_file_sha256": candidate["full_policy_file_sha256"],
        "selected_runtime_lock_sha256": candidate["runtime_lock_sha256"],
        "selected_checkpoint_path": checkpoint_path.relative_to(repository).as_posix(),
        "selected_checkpoint_file_sha256": hashlib.sha256(checkpoint_raw).hexdigest(),
        "selected_checkpoint_digest": checkpoint["digest"],
        "development_selection_evidence_path": (
            promotion / "development_selection_evidence.json"
        ).relative_to(repository).as_posix(),
        "development_selection_evidence_sha256": hashlib.sha256(
            evidence_raw
        ).hexdigest(),
        "heldout_execution": "PENDING_SEPARATE_EXEC_APPROVAL",
    }
    proposal_path = promotion / "selected_m2.proposed.json"
    proposal_raw = _write_json(proposal_path, proposal)

    assert benchmark_matrix._validate_development_promotion(
        results_dir=results,
        selection_evidence=evidence,
        selected_candidate_id=selected_id,
        summaries=summaries,
    ) == {
        "development_selection_evidence_sha256": hashlib.sha256(
            evidence_raw
        ).hexdigest(),
        "selected_m2_checkpoint_sha256": hashlib.sha256(checkpoint_raw).hexdigest(),
        "selected_m2_proposal_sha256": hashlib.sha256(proposal_raw).hexdigest(),
    }

    proposal["selected_candidate_id"] = "baseline"
    _write_json(proposal_path, proposal)
    with pytest.raises(benchmark_matrix.MatrixError, match="proposal differs"):
        benchmark_matrix._validate_development_promotion(
            results_dir=results,
            selection_evidence=evidence,
            selected_candidate_id=selected_id,
            summaries=summaries,
        )


def test_public_selection_trace_is_bound_and_fail_closed() -> None:
    aggregate = _public_selection_aggregate()
    assert public_artifact.validate_public_development_selection(aggregate) == aggregate

    wrong_candidate = deepcopy(aggregate)
    wrong_candidate["selected_candidate_id"] = "baseline"
    with pytest.raises(public_artifact.PublicArtifactError, match="differs from trace"):
        public_artifact.validate_public_development_selection(wrong_candidate)

    wrong_hash = deepcopy(aggregate)
    wrong_hash["development_selection_sha256"] = "0" * 64
    with pytest.raises(public_artifact.PublicArtifactError, match="evidence hash differs"):
        public_artifact.validate_public_development_selection(wrong_hash)

    nondeterministic = deepcopy(aggregate)
    nondeterministic["development_selection"]["selection"]["selected_candidate_id"] = (
        "baseline"
    )
    nondeterministic["development_selection_sha256"] = hashlib.sha256(
        public_artifact._canonical(nondeterministic["development_selection"])
    ).hexdigest()
    with pytest.raises(public_artifact.PublicArtifactError, match="not deterministic"):
        public_artifact.validate_public_development_selection(nondeterministic)

    leaked = deepcopy(aggregate)
    leaked["development_selection"]["candidate_summaries"][0]["source_row"] = {
        "private": True
    }
    leaked["development_selection_sha256"] = hashlib.sha256(
        public_artifact._canonical(leaked["development_selection"])
    ).hexdigest()
    with pytest.raises(public_artifact.PublicArtifactError, match="field set differs"):
        public_artifact.validate_public_development_selection(leaked)

    malformed_restricted_hash = deepcopy(aggregate)
    malformed_restricted_hash["restricted_selection_artifact_hashes"][
        "selected_m2_proposal_sha256"
    ] = "not-a-hash"
    with pytest.raises(public_artifact.PublicArtifactError, match="hashes are malformed"):
        public_artifact.validate_public_development_selection(
            malformed_restricted_hash
        )


def test_request_writer_refuses_dirty_or_repeat_state(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    source = _initialize(repository)
    report = trigger.write_request(repository)
    assert report["source_head"] == source
    assert report["status"] == "WROTE_ZERO_AUTHORITY_SENTINEL"
    with pytest.raises(trigger.DevelopmentTriggerError, match="clean worktree"):
        trigger.write_request(repository)


def _development_budget_ledger(
    tmp_path: Path, **cap_overrides: int
) -> benchmark_run.AtomicBudgetLedger:
    caps = deepcopy(trigger.HARD_CAPS)
    caps.update(cap_overrides)
    if any(
        field in cap_overrides
        for field in ("solve_calls", "decomposition_calls", "extraction_calls")
    ):
        caps["model_calls"] = sum(
            caps[field]
            for field in ("solve_calls", "decomposition_calls", "extraction_calls")
        )
        caps["paid_model_calls"] = caps["model_calls"]
    return benchmark_run.AtomicBudgetLedger(
        tmp_path / "budget-ledger.json",
        approval_digest="a" * 64,
        caps=caps,
        pricing={
            "input_per_million_tokens_usd": 0.75,
            "cached_input_per_million_tokens_usd": 0.075,
            "output_per_million_tokens_usd": 4.5,
        },
    )


def test_development_budget_ledger_carries_every_approved_call_cap(
    tmp_path: Path,
) -> None:
    ledger = _development_budget_ledger(tmp_path)
    assert {
        name: ledger.caps[name]
        for name in (
            "paid_model_calls",
            "solve_calls",
            "decomposition_calls",
            "extraction_calls",
        )
    } == {
        "paid_model_calls": 1872,
        "solve_calls": 1728,
        "decomposition_calls": 72,
        "extraction_calls": 72,
    }
    empty = ledger._empty()
    assert empty["schema"] == "trimem/atomic-budget-ledger/1.4"
    assert empty["approved_hard_cap"] == trigger.HARD_CAPS
    assert empty["approved_hard_cap_sha256"] == hashlib.sha256(
        benchmark_run.canonical_bytes(trigger.HARD_CAPS)
    ).hexdigest()


@pytest.mark.parametrize(
    ("call_kind", "cap_name"),
    (
        ("solve", "solve_calls"),
        ("decompose", "decomposition_calls"),
        ("extract", "extraction_calls"),
    ),
)
def test_role_call_cap_is_reserved_before_send_and_rejects_exact_overflow(
    tmp_path: Path, call_kind: str, cap_name: str
) -> None:
    ledger = _development_budget_ledger(tmp_path, **{cap_name: 1})
    task_arm_key = "M2-baseline:M2:target-001"
    ledger.reserve_task_arm(task_arm_key)
    reservation = ledger.reserve(
        f"{call_kind}-001",
        task_arm_key=task_arm_key,
        call_kind=call_kind,
        input_upper_bound=10,
        output_cap=benchmark_run.MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[call_kind],
    )
    assert reservation == hashlib.sha256(
        benchmark_run.canonical_bytes({
            "approval": "a" * 64,
            "logical_call_id": f"{call_kind}-001",
            "task_arm_key": task_arm_key,
            "call_kind": call_kind,
            "input_upper_bound": 10,
            "output_cap": benchmark_run.MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[
                call_kind
            ],
        })
    ).hexdigest()
    reserved = benchmark_run.read_json(ledger.path)
    assert reserved["actual"][cap_name] == 0
    assert reserved["outstanding"][cap_name] == 1

    before_pending_rejection = ledger.path.read_bytes()
    with pytest.raises(
        benchmark_run.BenchmarkExecutionError,
        match=rf"{cap_name} hard cap|task-arm role output pool",
    ):
        ledger.reserve(
            f"{call_kind}-while-pending",
            task_arm_key=task_arm_key,
            call_kind=call_kind,
            input_upper_bound=10,
            output_cap=benchmark_run.MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[call_kind],
        )
    assert ledger.path.read_bytes() == before_pending_rejection

    ledger.reconcile(
        f"{call_kind}-001",
        reservation,
        input_tokens=7,
        cached_input_tokens=2,
        output_tokens=11,
        status="SUCCESS",
    )
    reconciled = benchmark_run.read_json(ledger.path)
    assert reconciled["actual"][cap_name] == 1
    assert reconciled["outstanding"][cap_name] == 0
    assert reconciled["actual"]["paid_model_calls"] == 1
    assert reconciled["outstanding"]["paid_model_calls"] == 0

    before_rejection = ledger.path.read_bytes()
    with pytest.raises(
        benchmark_run.BenchmarkExecutionError,
        match=rf"{cap_name} hard cap|task-arm role output pool",
    ):
        ledger.reserve(
            f"{call_kind}-002",
            task_arm_key=task_arm_key,
            call_kind=call_kind,
            input_upper_bound=10,
            output_cap=benchmark_run.MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[call_kind],
        )
    assert ledger.path.read_bytes() == before_rejection


def test_unknown_provider_failure_consumes_role_reservation_conservatively(
    tmp_path: Path,
) -> None:
    ledger = _development_budget_ledger(tmp_path, extraction_calls=1)
    task_arm_key = "M2-baseline:M2:target-001"
    ledger.reserve_task_arm(task_arm_key)
    reservation = ledger.reserve(
        "extract-001",
        task_arm_key=task_arm_key,
        call_kind="extract",
        input_upper_bound=13,
        output_cap=benchmark_run.MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND["extract"],
    )
    ledger.reconcile(
        "extract-001",
        reservation,
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        status="UNKNOWN_FAILURE_CONSERVATIVE",
        conservative_unknown=True,
    )
    state = benchmark_run.read_json(ledger.path)
    assert state["outstanding"]["extraction_calls"] == 0
    assert state["actual"]["extraction_calls"] == 1
    assert state["actual"]["paid_model_calls"] == 1
    assert state["actual"]["input_tokens"] == 13
    assert state["actual"]["output_tokens"] == 8_192


@pytest.mark.parametrize("call_kind", ("decompose", "extract"))
def test_output_cap_must_equal_frozen_call_kind_limit_before_send(
    tmp_path: Path, call_kind: str
) -> None:
    ledger = _development_budget_ledger(tmp_path)
    task_arm_key = "M2-baseline:M2:target-001"
    ledger.reserve_task_arm(task_arm_key)
    frozen_cap = benchmark_run.MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[call_kind]
    before_rejection = ledger.path.read_bytes()
    with pytest.raises(
        benchmark_run.BenchmarkExecutionError,
        match="output cap differs from the frozen runtime cap",
    ):
        ledger.reserve(
            f"{call_kind}-wrong-cap",
            task_arm_key=task_arm_key,
            call_kind=call_kind,
            input_upper_bound=10,
            output_cap=frozen_cap - 1,
        )
    assert ledger.path.read_bytes() == before_rejection


def test_unknown_call_kind_fails_before_mutating_ledger(tmp_path: Path) -> None:
    ledger = _development_budget_ledger(tmp_path)
    task_arm_key = "M2-baseline:M2:target-001"
    ledger.reserve_task_arm(task_arm_key)
    before_rejection = ledger.path.read_bytes()
    with pytest.raises(
        benchmark_run.BenchmarkExecutionError,
        match="unknown call kind",
    ):
        ledger.reserve(
            "other-001",
            task_arm_key=task_arm_key,
            call_kind="other",
            input_upper_bound=10,
            output_cap=20,
        )
    assert ledger.path.read_bytes() == before_rejection


def _provider_outcome_fixture(
    accounting: dict[str, int], *, reserved_input: int, reserved_output: int
) -> dict[str, object]:
    calls = accounting["model_gateway_calls"]
    return {
        "provider_status_distribution": {"SUCCESS": calls},
        "incomplete_count": 0,
        "refusal_count": 0,
        "structured_output_schema_failure_count": 0,
        "provider_reported_usage": {
            "available_calls": calls,
            "unavailable_calls": 0,
            "complete": True,
            "input_tokens": accounting["input_tokens"],
            "cached_input_tokens": accounting["cached_input_tokens"],
            "output_tokens": accounting["output_tokens"],
            "reasoning_tokens": accounting["reasoning_tokens"],
        },
        "ledger_reservation": {
            "calls": calls,
            "input_upper_bound": reserved_input,
            "output_cap": reserved_output,
            "conservatively_charged_calls": 0,
        },
    }


def _single_task_terminal_budget(
    tmp_path: Path,
) -> tuple[
    benchmark_run.AtomicBudgetLedger,
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    ledger = _development_budget_ledger(
        tmp_path,
        task_arm_runs=1,
        benchmark_grader_containers=1,
        solve_calls=1,
        decomposition_calls=1,
        extraction_calls=1,
    )
    task_key = "M0:M0:target-001"
    task_reservation = ledger.reserve_task_arm(task_key)
    calls = (
        ("solve", 7, 2, 5),
        ("decompose", 11, 0, 3),
        ("extract", 13, 1, 4),
    )
    for call_kind, input_tokens, cached_tokens, output_tokens in calls:
        logical_id = f"{call_kind}-001"
        reservation = ledger.reserve(
            logical_id,
            task_arm_key=task_key,
            call_kind=call_kind,
            input_upper_bound=input_tokens + 5,
            output_cap=benchmark_run.MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[call_kind],
        )
        ledger.reconcile(
            logical_id,
            reservation,
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
            status="SUCCESS",
        )
    ledger.complete_task_arm(
        task_key,
        task_reservation,
        status="SUCCESS",
        container_started=True,
    )
    accounting = {field: 0 for field in benchmark_matrix.ACCOUNTING_FIELDS}
    accounting.update({
        "solve_calls": 1,
        "decomposition_calls": 1,
        "extraction_calls": 1,
        "actual_decomposition_output_tokens": 3,
        "actual_solve_output_tokens": 5,
        "actual_extraction_output_tokens": 4,
        "solve_output_pool_capacity": 49_152,
        "remaining_solve_output_tokens": 49_147,
        "input_tokens": 31,
        "cached_input_tokens": 3,
        "output_tokens": 12,
        "model_gateway_calls": 3,
        "paid_model_calls": 3,
        "grader_calls": 1,
        "grader_containers": 1,
        "official_grader_runs": 1,
    })
    pricing = {
        "input_per_million_tokens_usd": 0.75,
        "cached_input_per_million_tokens_usd": 0.075,
        "output_per_million_tokens_usd": 4.5,
    }
    actual_usd = benchmark_run.actual_usd_for_accounting(accounting, pricing)
    execution_lock = "sha256:" + "1" * 64
    provider_outcomes = _provider_outcome_fixture(
        accounting, reserved_input=46, reserved_output=18_432
    )
    record: dict[str, object] = {
        "actual_accounting": accounting,
        "provider_outcomes": provider_outcomes,
        "actual_usd": actual_usd,
        "arm": "M0",
        "runtime_arm": "M0",
        "target_id": "target-001",
        "execution_lock_hash": execution_lock,
    }
    summary: dict[str, object] = {
        "arm": "M0",
        "actual_accounting": deepcopy(accounting),
        "provider_outcomes": deepcopy(provider_outcomes),
        "actual_usd": actual_usd,
        "execution_lock_hash": execution_lock,
    }
    return ledger, record, summary, pricing


def _two_task_terminal_budget(
    tmp_path: Path,
) -> tuple[
    benchmark_run.AtomicBudgetLedger,
    list[dict[str, object]],
    dict[str, dict[str, object]],
    dict[str, object],
]:
    ledger = _development_budget_ledger(
        tmp_path,
        task_arm_runs=2,
        benchmark_grader_containers=2,
        solve_calls=3,
        decomposition_calls=2,
        extraction_calls=2,
        model_calls=7,
        paid_model_calls=7,
    )
    pricing: dict[str, object] = {
        "input_per_million_tokens_usd": 0.75,
        "cached_input_per_million_tokens_usd": 0.075,
        "output_per_million_tokens_usd": 4.5,
    }
    records: list[dict[str, object]] = []
    projections: dict[str, dict[str, object]] = {}
    for arm, target_id, solve_calls, input_tokens, cached_tokens, output_tokens in (
        ("M0", "target-001", 2, 7, 1, 3),
        ("M1", "target-002", 1, 11, 4, 9),
    ):
        task_key = f"{arm}:{arm}:{target_id}"
        task_reservation = ledger.reserve_task_arm(task_key)
        call_kinds = ("solve",) * solve_calls + ("decompose", "extract")
        for call_index, call_kind in enumerate(call_kinds):
            logical_id = f"{arm}-{call_kind}-{call_index}"
            reservation = ledger.reserve(
                logical_id,
                task_arm_key=task_key,
                call_kind=call_kind,
                input_upper_bound=input_tokens + 5,
                output_cap=benchmark_run.MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[
                    call_kind
                ],
            )
            ledger.reconcile(
                logical_id,
                reservation,
                input_tokens=input_tokens,
                cached_input_tokens=cached_tokens,
                output_tokens=output_tokens,
                status="SUCCESS",
            )
        ledger.complete_task_arm(
            task_key,
            task_reservation,
            status="SUCCESS",
            container_started=True,
        )
        accounting = {field: 0 for field in benchmark_matrix.ACCOUNTING_FIELDS}
        accounting.update({
            "solve_calls": solve_calls,
            "decomposition_calls": 1,
            "extraction_calls": 1,
            "actual_decomposition_output_tokens": output_tokens,
            "actual_solve_output_tokens": output_tokens * solve_calls,
            "actual_extraction_output_tokens": output_tokens,
            "solve_output_pool_capacity": 49_152,
            "remaining_solve_output_tokens": 49_152 - output_tokens * solve_calls,
            "input_tokens": input_tokens * len(call_kinds),
            "cached_input_tokens": cached_tokens * len(call_kinds),
            "output_tokens": output_tokens * len(call_kinds),
            "model_gateway_calls": len(call_kinds),
            "paid_model_calls": len(call_kinds),
            "grader_calls": 1,
            "grader_containers": 1,
            "official_grader_runs": 1,
        })
        actual_usd = benchmark_run.actual_usd_for_accounting(accounting, pricing)
        provider_outcomes = _provider_outcome_fixture(
            accounting,
            reserved_input=(input_tokens + 5) * len(call_kinds),
            reserved_output=sum(
                benchmark_run.MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[kind]
                for kind in call_kinds
            ),
        )
        records.append({
            "actual_accounting": accounting,
            "provider_outcomes": provider_outcomes,
            "actual_usd": actual_usd,
            "arm": arm,
            "runtime_arm": arm,
            "target_id": target_id,
            "execution_lock_hash": "sha256:" + ("1" if arm == "M0" else "2") * 64,
        })
        projections[task_key] = {
            "input_tokens": accounting["input_tokens"],
            "cached_input_tokens": accounting["cached_input_tokens"],
            "output_tokens": accounting["output_tokens"],
            "solve_calls": solve_calls,
            "decomposition_calls": 1,
            "extraction_calls": 1,
            "model_gateway_calls": len(call_kinds),
            "paid_model_calls": len(call_kinds),
            "total_usd": actual_usd,
        }
    return ledger, records, projections, pricing


def test_runner_terminal_budget_binds_result_summary_session_and_ledger(
    tmp_path: Path,
) -> None:
    ledger, record, summary, pricing = _single_task_terminal_budget(tmp_path)
    result_path = tmp_path / "M0" / "000-target-001" / "target-001.result.json"
    _write_json(result_path, record)
    benchmark_run.prepare_arm_identity(
        tmp_path,
        arm="M0",
        split="development",
        experiment_id="trimemv1-bbbbbbbbbbbb-m0",
        execution_lock_hash=str(record["execution_lock_hash"]),
        resume=False,
    )
    evidence = benchmark_run.validate_phase_completion(
        tmp_path,
        split="development",
        summaries=[summary],
        ledger=ledger,
        hard_cap=ledger.approved_hard_cap,
        pricing=pricing,
    )
    assert evidence["task_arm_runs"] == 1
    assert evidence["actual_accounting"]["paid_model_calls"] == 3
    assert evidence["execution_locks"] == {"M0": "sha256:" + "1" * 64}


def test_runner_terminal_budget_rejects_cross_task_token_or_role_swap(
    tmp_path: Path,
) -> None:
    ledger, _records, projections, _pricing = _two_task_terminal_budget(tmp_path)
    state = benchmark_run.read_json(ledger.path)

    token_swap = deepcopy(projections)
    for field in ("cached_input_tokens", "output_tokens", "total_usd"):
        token_swap["M0:M0:target-001"][field], token_swap["M1:M1:target-002"][field] = (
            token_swap["M1:M1:target-002"][field],
            token_swap["M0:M0:target-001"][field],
        )
    with pytest.raises(
        benchmark_run.BenchmarkExecutionError,
        match="per-task request/result accounting differs",
    ):
        ledger.finalize(
            expected_actual=state["actual"],
            expected_task_arms=token_swap,
        )

    role_swap = deepcopy(projections)
    for field in ("solve_calls", "model_gateway_calls", "paid_model_calls"):
        role_swap["M0:M0:target-001"][field], role_swap["M1:M1:target-002"][field] = (
            role_swap["M1:M1:target-002"][field],
            role_swap["M0:M0:target-001"][field],
        )
    with pytest.raises(
        benchmark_run.BenchmarkExecutionError,
        match="per-task request/result accounting differs",
    ):
        ledger.finalize(
            expected_actual=state["actual"],
            expected_task_arms=role_swap,
        )


def _shrink_solve_reservation_below_actual(value: dict[str, object]) -> None:
    request = value["requests"]["solve-001"]
    request["input_upper_bound"] = request["input_tokens"] - 1
    request["reservation_id"] = hashlib.sha256(
        benchmark_run.canonical_bytes({
            "approval": value["approval_digest"],
            "logical_call_id": "solve-001",
            "task_arm_key": request["task_arm_key"],
            "call_kind": request["call_kind"],
            "input_upper_bound": request["input_upper_bound"],
            "output_cap": request["output_cap"],
        })
    ).hexdigest()
    request["reserved_usd"] = (
        request["input_upper_bound"] * value["pricing"]["input"]
        + request["output_cap"] * value["pricing"]["output"]
    ) / 1_000_000


LEDGER_ROW_TAMPERS = (
    (
        lambda value: value["requests"]["solve-001"].__setitem__(
            "unexpected", True
        ),
        "terminal request shape differs",
    ),
    (
        lambda value: value["task_arms"]["M0:M0:target-001"].__setitem__(
            "unexpected", True
        ),
        "task-arm/result accounting differs",
    ),
    (
        lambda value: value["requests"]["solve-001"].__setitem__(
            "reservation_id", "0" * 64
        ),
        "request reservation identity differs",
    ),
    (
        lambda value: value["task_arms"]["M0:M0:target-001"].__setitem__(
            "reservation_id", "0" * 64
        ),
        "task-arm/result accounting differs",
    ),
    (
        lambda value: value["requests"]["solve-001"].__setitem__(
            "reserved_usd", value["requests"]["solve-001"]["reserved_usd"] + 1
        ),
        "reserved USD differs",
    ),
    (
        lambda value: value["requests"]["solve-001"].__setitem__(
            "input_upper_bound", 0
        ),
        "reservation bounds are invalid",
    ),
    (
        lambda value: value["requests"]["solve-001"].__setitem__(
            "output_cap", 0
        ),
        "reservation bounds are invalid",
    ),
    (
        lambda value: value["requests"].__setitem__(
            "renamed-solve-001", value["requests"].pop("solve-001")
        ),
        "request reservation identity differs",
    ),
    (
        _shrink_solve_reservation_below_actual,
        "actual usage exceeds its reservation",
    ),
)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.__setitem__("outstanding", {}), "counter shape"),
        (
            lambda value: value["outstanding"].__setitem__("total_usd", 0.5),
            "outstanding total_usd",
        ),
        (
            lambda value: value["actual"].__setitem__(
                "input_tokens", value["actual"]["input_tokens"] + 1
            ),
            "actual input_tokens differs",
        ),
        (
            lambda value: value["requests"]["solve-001"].update(
                {"call_kind": "other", "call_cap_name": None}
            ),
            "role binding differs",
        ),
        (
            lambda value: value["approved_hard_cap"].__setitem__(
                "total_usd", 49.0
            ),
            "approval/cap identity mismatch",
        ),
        *LEDGER_ROW_TAMPERS,
    ],
)
def test_terminal_budget_ledger_tampering_fails_closed(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], None],
    message: str,
) -> None:
    ledger, record, _summary, _pricing = _single_task_terminal_budget(tmp_path)
    state = benchmark_run.read_json(ledger.path)
    mutation(state)
    _write_json(ledger.path, state)
    expected = {
        **state["actual"],
        "input_tokens": 31,
    }
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match=message):
        ledger.finalize(
            expected_actual=expected,
            expected_task_arms={
                "M0:M0:target-001": {
                    "input_tokens": 31,
                    "cached_input_tokens": 3,
                    "output_tokens": 12,
                    "solve_calls": 1,
                    "decomposition_calls": 1,
                    "extraction_calls": 1,
                    "model_gateway_calls": 3,
                    "paid_model_calls": 3,
                    "total_usd": record["actual_usd"],
                }
            },
        )


def _development_phase_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for index in range(72):
        accounting = {field: 0 for field in benchmark_matrix.ACCOUNTING_FIELDS}
        accounting.update({
            "solve_calls": 12,
            "decomposition_calls": 1,
            "extraction_calls": 1,
            "input_tokens": 164_000,
            "output_tokens": 6_000,
            "model_gateway_calls": 14,
            "paid_model_calls": 14,
            "grader_calls": 1,
            "grader_containers": 1,
            "official_grader_runs": 1,
        })
        records.append({"target_id": f"target-{index:03d}", "actual_accounting": accounting})
    return records


def test_development_phase_budget_recomputes_exact_frozen_workload() -> None:
    pricing = {
        "input_per_million_tokens_usd": 0.75,
        "cached_input_per_million_tokens_usd": 0.075,
        "output_per_million_tokens_usd": 4.5,
    }
    evidence = benchmark_matrix._validate_phase_budget(
        _development_phase_records(),
        pricing=pricing,
        hard_cap=deepcopy(trigger.HARD_CAPS),
    )
    assert evidence["task_arm_runs"] == 72
    assert evidence["model_calls"] == 1008
    assert evidence["actual_accounting"]["solve_calls"] == 864
    assert evidence["actual_accounting"]["decomposition_calls"] == 72
    assert evidence["actual_accounting"]["extraction_calls"] == 72
    assert evidence["actual_accounting"]["input_tokens"] == 11_808_000
    assert evidence["actual_accounting"]["output_tokens"] == 432_000
    assert evidence["total_usd"] == "10.800000000000"
    assert evidence["hard_cap"] == trigger.HARD_CAPS


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda rows: rows[0]["actual_accounting"].__setitem__(
                "input_tokens", 500_001
            ),
            "per-task hard cap",
        ),
        (
            lambda rows: [
                row["actual_accounting"].__setitem__(
                        "output_tokens", 65_537 if index == 0 else 65_536
                )
                for index, row in enumerate(rows)
            ],
            "output_tokens exceeds",
        ),
        (lambda rows: rows.pop(), "exact task"),
    ],
)
def test_development_phase_budget_rejects_cap_or_workload_drift(
    mutate: Callable[[list[dict[str, object]]], object],
    message: str,
) -> None:
    records = _development_phase_records()
    mutate(records)
    with pytest.raises(benchmark_matrix.MatrixError, match=message):
        benchmark_matrix._validate_phase_budget(
            records,
            pricing={
                "input_per_million_tokens_usd": 0.75,
                "cached_input_per_million_tokens_usd": 0.075,
                "output_per_million_tokens_usd": 4.5,
            },
            hard_cap=deepcopy(trigger.HARD_CAPS),
        )


def test_aggregate_budget_evidence_binds_approval_cap_model_and_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, record, summary, pricing = _single_task_terminal_budget(tmp_path)
    phase = benchmark_matrix._validate_phase_budget(
        [record], pricing=pricing, hard_cap=ledger.approved_hard_cap
    )
    monkeypatch.setattr(
        benchmark_matrix,
        "_frozen_file_hash",
        lambda relative: "2" * 64 if "model_lock" in relative else "3" * 64,
    )
    evidence = benchmark_matrix._validate_budget_ledger_evidence(
        tmp_path,
        records=[record],
        pricing=pricing,
        hard_cap=ledger.approved_hard_cap,
        phase_budget=phase,
        approval_binding={"approval_artifact_sha256": "a" * 64},
        execution_locks={"M0": str(summary["execution_lock_hash"])},
    )
    assert evidence["approval_artifact_sha256"] == "a" * 64
    assert evidence["approved_hard_cap_sha256"] == hashlib.sha256(
        benchmark_matrix._canonical(ledger.approved_hard_cap)
    ).hexdigest()
    assert evidence["model_lock_sha256"] == "2" * 64

    tampered = benchmark_run.read_json(ledger.path)
    tampered["actual"]["output_tokens"] += 1
    _write_json(ledger.path, tampered)
    with pytest.raises(benchmark_matrix.MatrixError, match="actual output_tokens"):
        benchmark_matrix._validate_budget_ledger_evidence(
            tmp_path,
            records=[record],
            pricing=pricing,
            hard_cap=ledger.approved_hard_cap,
            phase_budget=phase,
            approval_binding={"approval_artifact_sha256": "a" * 64},
            execution_locks={"M0": str(summary["execution_lock_hash"])},
        )


@pytest.mark.parametrize(("mutation", "message"), LEDGER_ROW_TAMPERS)
def test_aggregate_budget_ledger_row_tampering_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], None],
    message: str,
) -> None:
    ledger, record, summary, pricing = _single_task_terminal_budget(tmp_path)
    phase = benchmark_matrix._validate_phase_budget(
        [record], pricing=pricing, hard_cap=ledger.approved_hard_cap
    )
    tampered = benchmark_run.read_json(ledger.path)
    mutation(tampered)
    _write_json(ledger.path, tampered)
    monkeypatch.setattr(
        benchmark_matrix,
        "_frozen_file_hash",
        lambda relative: "2" * 64 if "model_lock" in relative else "3" * 64,
    )
    with pytest.raises(benchmark_matrix.MatrixError, match=message):
        benchmark_matrix._validate_budget_ledger_evidence(
            tmp_path,
            records=[record],
            pricing=pricing,
            hard_cap=ledger.approved_hard_cap,
            phase_budget=phase,
            approval_binding={"approval_artifact_sha256": "a" * 64},
            execution_locks={"M0": str(summary["execution_lock_hash"])},
        )


def test_aggregate_budget_rejects_cross_stream_token_swap_with_same_global_totals(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, records, _projections, pricing = _two_task_terminal_budget(tmp_path)
    tampered = deepcopy(records)
    left = tampered[0]["actual_accounting"]
    right = tampered[1]["actual_accounting"]
    for field in ("cached_input_tokens", "output_tokens"):
        left[field], right[field] = right[field], left[field]
    for record in tampered:
        record["actual_usd"] = benchmark_run.actual_usd_for_accounting(
            record["actual_accounting"], pricing
        )
    phase = benchmark_matrix._validate_phase_budget(
        tampered,
        pricing=pricing,
        hard_cap=ledger.approved_hard_cap,
    )
    monkeypatch.setattr(
        benchmark_matrix,
        "_frozen_file_hash",
        lambda relative: "2" * 64 if "model_lock" in relative else "3" * 64,
    )
    with pytest.raises(
        benchmark_matrix.MatrixError,
        match="per-task request/result accounting differs",
    ):
        benchmark_matrix._validate_budget_ledger_evidence(
            tmp_path,
            records=tampered,
            pricing=pricing,
            hard_cap=ledger.approved_hard_cap,
            phase_budget=phase,
            approval_binding={"approval_artifact_sha256": "a" * 64},
            execution_locks={
                "M0": str(records[0]["execution_lock_hash"]),
                "M1": str(records[1]["execution_lock_hash"]),
            },
        )

    role_tampered = deepcopy(records)
    for field in ("solve_calls", "model_gateway_calls", "paid_model_calls"):
        role_tampered[0]["actual_accounting"][field], role_tampered[1]["actual_accounting"][field] = (
            role_tampered[1]["actual_accounting"][field],
            role_tampered[0]["actual_accounting"][field],
        )
    phase = benchmark_matrix._validate_phase_budget(
        role_tampered,
        pricing=pricing,
        hard_cap=ledger.approved_hard_cap,
    )
    with pytest.raises(
        benchmark_matrix.MatrixError,
        match="per-task request/result accounting differs",
    ):
        benchmark_matrix._validate_budget_ledger_evidence(
            tmp_path,
            records=role_tampered,
            pricing=pricing,
            hard_cap=ledger.approved_hard_cap,
            phase_budget=phase,
            approval_binding={"approval_artifact_sha256": "a" * 64},
            execution_locks={
                "M0": str(records[0]["execution_lock_hash"]),
                "M1": str(records[1]["execution_lock_hash"]),
            },
        )


def test_aggregate_execution_lock_requires_result_summary_and_session_identity(
    tmp_path: Path,
) -> None:
    _ledger, record, summary, _pricing = _single_task_terminal_budget(tmp_path)
    head = "b" * 40
    benchmark_run.prepare_arm_identity(
        tmp_path,
        arm="M0",
        split="development",
        experiment_id="trimemv1-bbbbbbbbbbbb-m0",
        execution_lock_hash=str(record["execution_lock_hash"]),
        resume=False,
    )
    assert benchmark_matrix._validate_execution_lock_evidence(
        "development", tmp_path, [record], [summary], {"git_head": head}
    ) == {"M0": "sha256:" + "1" * 64}
    record["execution_lock_hash"] = "sha256:" + "9" * 64
    with pytest.raises(benchmark_matrix.MatrixError, match="result/summary"):
        benchmark_matrix._validate_execution_lock_evidence(
            "development", tmp_path, [record], [summary], {"git_head": head}
        )
