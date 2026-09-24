from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import trimem_development_trigger_d112 as d112  # noqa: E402
import trimem_development_trigger_d113 as d113  # noqa: E402
import trimem_development_trigger_d114 as trigger  # noqa: E402


EXPECTED_REMOTE_GATE_SPECS = (
    (".github/workflows/ci-trimem.yml", "push", None),
    (".github/workflows/ci-trimem-grader-loader.yml", "push", None),
    (".github/workflows/ci-trimem-harness-lock.yml", "push", None),
    (".github/workflows/ci-trimem-multi-swe-contract.yml", "push", None),
    (".github/workflows/ci-trimem-e2e.yml", "push", None),
    (".github/workflows/ci-trimem-dev-toolchain.yml", "push", None),
    (".github/workflows/ci.yml", "pull_request", 18),
    (".github/workflows/codeql.yml", "pull_request", 18),
    (".github/workflows/ci-docs.yml", "pull_request", 18),
    (".github/workflows/ci-company-package.yml", "pull_request", 18),
    (".github/workflows/ci-company-harness.yml", "pull_request", 18),
    (".github/workflows/ci-company-demo.yml", "pull_request", 18),
    (".github/workflows/ci-trimem-harness-lock.yml", "pull_request", 18),
    (".github/workflows/ci-oidc.yml", "pull_request", 18),
    (".github/workflows/ci-experience-schema.yml", "pull_request", 18),
    (".github/workflows/ci-oss-release.yml", "pull_request", 18),
    (".github/workflows/ci-trimem-grader-loader.yml", "pull_request", 18),
    (".github/workflows/ci-trimem-multi-swe-contract.yml", "pull_request", 18),
    (".github/workflows/ci-trimem-e2e.yml", "pull_request", 18),
    (".github/workflows/ci-trimem.yml", "pull_request", 18),
)


def _blob(commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "cat-file", "blob", f"{commit}:{path}"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout


def test_d114_identity_and_exact_013_git_blob_are_locked() -> None:
    assert trigger.PREVIOUS_SOURCE_HEAD == (
        "cb17ceae0fbc951dff34213de977a73b5405fefc"
    )
    assert trigger.PREVIOUS_EXECUTION_HEAD == (
        "35bfa338915d731dab499f2dfee08b38741bfe8d"
    )
    assert trigger.PREVIOUS_RUN_ID == 34_138_918_074
    assert trigger.PREVIOUS_RUN_ATTEMPT == 1
    assert trigger.REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014"
    assert trigger.REQUEST_SCHEMA == "trimem/development-tuning-branch-trigger/1.14"
    assert trigger.SENTINEL_PATH.endswith("DEVELOPMENT_TUNING_EXEC_REQUEST_014.json")
    assert trigger.REQUIRED_EXTERNAL_AUTHORIZATION == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014_APPROVED_ONCE"
    )

    raw = _blob(trigger.PREVIOUS_EXECUTION_HEAD, trigger.PREVIOUS_SENTINEL_PATH)
    assert len(raw) == trigger.PREVIOUS_SENTINEL_BYTES == 21_784
    assert hashlib.sha256(raw).hexdigest() == trigger.PREVIOUS_SENTINEL_SHA256
    assert trigger.PREVIOUS_SENTINEL_SHA256 == (
        "a500568cedfa800bd85e20263b604fa2c1d24f634644d5ef14f517a8330b6417"
    )
    tree = subprocess.run(
        [
            "git",
            "ls-tree",
            trigger.PREVIOUS_EXECUTION_HEAD,
            "--",
            trigger.PREVIOUS_SENTINEL_PATH,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout
    assert (
        f"100644 blob {trigger.PREVIOUS_SENTINEL_BLOB_OID}\t"
        f"{trigger.PREVIOUS_SENTINEL_PATH}\n"
    ) == tree


def test_previous_013_request_is_canonical_zero_authority() -> None:
    request = trigger._load_previous_request(ROOT, trigger.PREVIOUS_EXECUTION_HEAD)
    assert request["request_id"] == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_013"
    assert request["request_sha256"] == (
        "sha256:" + trigger.PREVIOUS_REQUEST_PAYLOAD_SHA256
    )
    assert request["actual_execution_authorized"] is False
    assert request["external_execution_approval_received"] is False
    assert all(value == 0 for value in request["activation_actuals"].values())
    assert all(value == 0 for value in request["pre_execution_actuals"].values())


def test_d114_freezes_all_twenty_exact_head_remote_gates() -> None:
    assert len(trigger.REMOTE_GATE_SPECS) == 20
    assert trigger.REMOTE_GATE_SPECS == EXPECTED_REMOTE_GATE_SPECS
    assert trigger.REQUIRED_REMOTE_GATE_WORKFLOWS == tuple(
        dict.fromkeys(spec[0] for spec in EXPECTED_REMOTE_GATE_SPECS)
    )


def test_d114_context_is_nested_atomic_and_restores_on_failure() -> None:
    before_d113 = {
        "request_id": d113.REQUEST_ID,
        "request_schema": d113.REQUEST_SCHEMA,
        "sentinel_path": d113.SENTINEL_PATH,
        "source_validator": d113._validate_source_impl,
        "remote_gate_specs": d113.REMOTE_GATE_SPECS,
        "remote_gate_workflows": d113.REQUIRED_REMOTE_GATE_WORKFLOWS,
    }
    before_d112 = {
        "request_id": d112.REQUEST_ID,
        "request_schema": d112.REQUEST_SCHEMA,
        "sentinel_path": d112.SENTINEL_PATH,
        "remote_gate_specs": d112.REMOTE_GATE_SPECS,
        "remote_gate_workflows": d112.REQUIRED_REMOTE_GATE_WORKFLOWS,
    }

    with pytest.raises(RuntimeError, match="fixture failure"):
        with trigger._d114_runtime_context():
            assert d113.REQUEST_ID == trigger.REQUEST_ID
            assert d113.SENTINEL_PATH == trigger.SENTINEL_PATH
            assert d113.REMOTE_GATE_SPECS == EXPECTED_REMOTE_GATE_SPECS
            assert d113.REQUIRED_REMOTE_GATE_WORKFLOWS == (
                trigger.REQUIRED_REMOTE_GATE_WORKFLOWS
            )
            assert d112.REQUEST_ID == before_d112["request_id"]
            assert d112.REMOTE_GATE_SPECS == EXPECTED_REMOTE_GATE_SPECS
            assert d112.REQUIRED_REMOTE_GATE_WORKFLOWS == (
                trigger.REQUIRED_REMOTE_GATE_WORKFLOWS
            )
            with d113._d113_runtime_context():
                assert d112.REQUEST_ID == trigger.REQUEST_ID
                assert d112.REQUEST_SCHEMA == trigger.REQUEST_SCHEMA
                assert d112.SENTINEL_PATH == trigger.SENTINEL_PATH
                assert d112.REMOTE_GATE_SPECS == EXPECTED_REMOTE_GATE_SPECS
                assert d112.REQUIRED_REMOTE_GATE_WORKFLOWS == (
                    trigger.REQUIRED_REMOTE_GATE_WORKFLOWS
                )
            assert d112.REQUEST_ID == before_d112["request_id"]
            assert d112.REMOTE_GATE_SPECS == EXPECTED_REMOTE_GATE_SPECS
            raise RuntimeError("fixture failure")

    assert d113.REQUEST_ID == before_d113["request_id"]
    assert d113.REQUEST_SCHEMA == before_d113["request_schema"]
    assert d113.SENTINEL_PATH == before_d113["sentinel_path"]
    assert d113._validate_source_impl is before_d113["source_validator"]
    assert d113.REMOTE_GATE_SPECS == before_d113["remote_gate_specs"]
    assert d113.REQUIRED_REMOTE_GATE_WORKFLOWS == before_d113[
        "remote_gate_workflows"
    ]
    assert d112.REQUEST_ID == before_d112["request_id"]
    assert d112.REQUEST_SCHEMA == before_d112["request_schema"]
    assert d112.SENTINEL_PATH == before_d112["sentinel_path"]
    assert d112.REMOTE_GATE_SPECS == before_d112["remote_gate_specs"]
    assert d112.REQUIRED_REMOTE_GATE_WORKFLOWS == before_d112[
        "remote_gate_workflows"
    ]


def test_generic_runtime_wrapper_observes_d114_then_restores(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed: list[tuple[str, str]] = []

    def fake_runtime(*args: object, **kwargs: object) -> dict[str, str]:
        del args, kwargs
        observed.append((d113.REQUEST_ID, d113.SENTINEL_PATH))
        return {"status": "PASS"}

    monkeypatch.setattr(d113, "validate_runner_host_preflight", fake_runtime)
    original_id = d113.REQUEST_ID
    assert trigger.validate_runner_host_preflight(tmp_path, tmp_path / "event") == {
        "status": "PASS"
    }
    assert observed == [(trigger.REQUEST_ID, trigger.SENTINEL_PATH)]
    assert d113.REQUEST_ID == original_id
    assert d113.validate_runner_host_preflight is fake_runtime


def test_post_setup_fix_does_not_weaken_strict_library_binding() -> None:
    central = trigger.POST_SETUP_REQUIRED_LD_LIBRARY_PATH
    dual = trigger.EXEC_013_OBSERVED_LD_LIBRARY_PATH
    assert d112._require_exact_python_library_binding(
        {"LD_LIBRARY_PATH": central}, label="D1.14 exact step env"
    ) == central
    with pytest.raises(d112.DevelopmentTriggerError, match="LD_LIBRARY_PATH"):
        d112._require_exact_python_library_binding(
            {"LD_LIBRARY_PATH": dual}, label="EXEC _013 observed dual path"
        )
    with pytest.raises(d112.DevelopmentTriggerError, match="LD_LIBRARY_PATH"):
        d112._require_exact_python_library_binding(
            {"LD_LIBRARY_PATH": central + ":/usr/local/lib"},
            label="unexpected suffix",
        )


def test_failure_fixture_is_exact_preinstall_and_zero_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = (ROOT / trigger.PREVIOUS_FAILURE_FIXTURE_PATH).read_bytes()
    monkeypatch.setattr(trigger, "commit_bytes", lambda *args: raw)
    value = trigger._validate_previous_run_fixture(ROOT, "f" * 40)
    assert value["workflow_run"]["id"] == trigger.PREVIOUS_RUN_ID
    assert value["boundary"]["dependency_install_started"] is False
    assert value["boundary"]["harness_materialization_started"] is False
    assert value["boundary"]["protected_environment_entered"] is False
    assert value["actuals"]["model_api_calls"] == 0
    assert value["actuals"]["grader_containers"] == 0
    assert value["actuals"]["benchmark_image_pulls"] == 0
    assert value["actuals"]["total_usd"] == 0.0


def test_control_plane_allowlist_excludes_science_and_both_sentinels() -> None:
    assert set(trigger.ALLOWED_RECOVERY_PATHS).isdisjoint(
        trigger.PRESERVED_SCIENTIFIC_PATHS
    )
    assert trigger.PREVIOUS_SENTINEL_PATH not in trigger.ALLOWED_RECOVERY_PATHS
    assert trigger.SENTINEL_PATH not in trigger.ALLOWED_RECOVERY_PATHS
    assert set(trigger.REQUIRED_RECOVERY_CHANGES) <= trigger.ALLOWED_RECOVERY_PATHS
    assert trigger.REQUIRED_RECOVERY_CHANGES[
        "tests/unit/test_trimem_d114_post_setup_environment.py"
    ] == "A"
    for workflow in (
        ".github/workflows/ci-experience-schema.yml",
        ".github/workflows/ci-oidc.yml",
        ".github/workflows/ci-oss-release.yml",
        ".github/workflows/ci-trimem-e2e.yml",
        ".github/workflows/ci-trimem-harness-lock.yml",
        ".github/workflows/ci-trimem-multi-swe-contract.yml",
    ):
        assert trigger.REQUIRED_RECOVERY_CHANGES[workflow] == "M"
    assert "tests/unit/test_trimem_d113_e1_trigger.py" not in (
        trigger.REQUIRED_RECOVERY_CHANGES
    )


def test_request_payload_retains_science_and_has_no_execution_authority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    previous = {
        "control_plane": {"phase": "DEVELOPMENT_TUNING"},
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
            "target_order": list(trigger.EXPECTED_TARGET_ORDER),
            "stream_order": list(trigger.EXPECTED_STREAM_ORDER),
        },
    }
    validated = {
        "bindings": {"freeze_sha256": "sha256:" + "a" * 64},
        "hard_cap": deepcopy(trigger.EXPECTED_DEVELOPMENT_HARD_CAP),
        "previous_request": previous,
    }
    monkeypatch.setattr(trigger, "resolve_repository_root", lambda path: path)
    monkeypatch.setattr(trigger, "_validate_source_impl", lambda *args: validated)
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
    monkeypatch.setattr(
        trigger,
        "_request_execution_contracts",
        lambda bindings: {"required_order": ["D1.14 exact binding"]},
    )

    request = trigger.build_request(
        tmp_path,
        source_head="e" * 40,
        remote_gate_evidence={"gate": "PASS"},
        runner_readiness={"runner": "READY"},
    )
    assert request["request_id"] == trigger.REQUEST_ID
    assert request["actual_execution_authorized"] is False
    assert request["external_execution_approval_received"] is False
    assert request["pre_execution_actuals"]["paid_model_calls"] == 0
    assert request["pre_execution_actuals"]["grader_containers"] == 0
    assert request["pre_execution_actuals"]["task_arm_runs"] == 0
    assert request["exact_model"] == previous["exact_model"]
    assert request["scientific_workload"] == previous["scientific_workload"]
    assert "DEVELOPMENT_TUNING_EXEC_REQUEST_013_rerun_or_attempt_2" in (
        request["prohibited_actions"]
    )
    assert "DEVELOPMENT_TUNING_EXEC_REQUEST_015" in request["prohibited_actions"]
    assert request["required_external_authorization"] == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014_APPROVED_ONCE"
    )
