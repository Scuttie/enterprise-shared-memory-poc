from __future__ import annotations

import ast
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import venv

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_dev_activation_diagnostic as diagnostic  # noqa: E402
import trimem_dev_activation_approval as approval_builder  # noqa: E402
import trimem_dev_activation_gate as gate  # noqa: E402
import trimem_freeze as freeze  # noqa: E402
import trimem_verify_ready as readiness  # noqa: E402
import trimem_dev_activation_source_bank as source_bank  # noqa: E402


WORKFLOW = ROOT / ".github/workflows/ci-trimem-dev-activation-diagnostic.yml"
TEST_API_KEY = "sk-trimem-diagnostic-test-key-0000000000000000"


def test_all_pre_model_child_process_environments_drop_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import trimem_benchmark_run as benchmark
    import trimem_pull_locked_images as image_pull

    poison = {
        "OPENAI_API_KEY": "sk-poison",
        "TRIMEM_DEV_ACTIVATION_APPROVAL_B64": "approval-poison",
        "TRIMEM_EVIDENCE_PASSPHRASE": "evidence-poison",
        "GH_TOKEN": "gh-poison",
        "GITHUB_TOKEN": "github-poison",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.hooksPath",
        "GIT_CONFIG_VALUE_0": "poison-hook",
    }
    for key, value in poison.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DOCKER_CONTEXT", "fixture-context")

    docker_env = image_pull._docker_cli_environment()
    assert docker_env["DOCKER_CONTEXT"] == "fixture-context"
    assert not set(poison).intersection(docker_env)
    for git_env in (
        benchmark._hermetic_git_environment(),
        diagnostic._hermetic_git_environment(),
        gate._hermetic_git_environment(),
    ):
        assert not set(poison).intersection(git_env)
        assert git_env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert git_env["GIT_CONFIG_GLOBAL"] == os.devnull

    observed: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(argv, **kwargs):
        observed.append((list(argv), dict(kwargs["env"])))
        if argv[0] == "docker":
            return subprocess.CompletedProcess(argv, 0, stdout=b"[]", stderr=b"")
        if "ls-files" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="tracked\n", stderr="")
        if "rev-list" in argv:
            return subprocess.CompletedProcess(
                argv, 0, stdout="a" * 40 + " " + "b" * 40 + "\n", stderr=""
            )
        if "rev-parse" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="a" * 40 + "\n", stderr="")
        raise AssertionError(argv)

    with monkeypatch.context() as patcher:
        patcher.setattr(diagnostic.subprocess, "run", fake_run)
        diagnostic._require_tracked(tmp_path, "tracked.json")
    with monkeypatch.context() as patcher:
        patcher.setattr(gate.subprocess, "run", fake_run)
        assert gate._git_head(tmp_path) == "a" * 40
    with monkeypatch.context() as patcher:
        patcher.setattr(benchmark.subprocess, "run", fake_run)
        monkeypatch.setattr(benchmark, "ROOT", tmp_path)
        assert benchmark.git_head() == "a" * 40
        benchmark.git_tracked(tmp_path / "tracked.json")
        assert benchmark._run_command(
            ["git", "-C", str(tmp_path), "rev-parse", "HEAD"]
        ).stdout.strip() == "a" * 40
        with pytest.raises(benchmark.BenchmarkExecutionError, match="only hermetic Git"):
            benchmark._run_command(["python", "untrusted.py"])
    sentinel = tmp_path / "request.json"
    sentinel.write_bytes(b"{}")
    with monkeypatch.context() as patcher:
        patcher.setattr(benchmark.subprocess, "run", fake_run)
        patcher.setattr(benchmark, "git_head", lambda: "a" * 40)
        patcher.setattr(
            benchmark, "read_json", lambda _path: {"source_head": "b" * 40}
        )
        patcher.setattr(
            benchmark,
            "validate_grader_smoke_request_document",
            lambda *_args, **_kwargs: {"status": "PASS"},
        )
        patcher.setenv("GITHUB_EVENT_NAME", "push")
        assert benchmark.validate_grader_smoke_sentinel(sentinel)["status"] == "PASS"
    with monkeypatch.context() as patcher:
        patcher.setattr(image_pull.subprocess, "run", fake_run)
        image_pull._run(
            ["docker", "image", "inspect", "fixture@sha256:" + "b" * 64],
            tmp_path / "docker-evidence",
            0,
            "inspect",
        )
    assert len(observed) == 7
    assert all(
        not set(poison).intersection(environment)
        for _argv, environment in observed
    )
    for argv, _environment in observed[:6]:
        assert argv[:2] == ["git", "--no-replace-objects"]
        assert "core.fsmonitor=false" in argv
        assert f"core.hooksPath={os.devnull}" in argv


@pytest.mark.parametrize("failure", ["timeout", "launch"])
def test_image_pull_failure_paths_still_use_sanitized_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    import trimem_pull_locked_images as image_pull

    monkeypatch.setenv("OPENAI_API_KEY", "sk-poison")
    monkeypatch.setenv("TRIMEM_EVIDENCE_PASSPHRASE", "evidence-poison")
    observed = {}

    def fail(argv, **kwargs):
        observed.update(kwargs["env"])
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, timeout=3600)
        raise OSError("fixture launch failure")

    monkeypatch.setattr(image_pull.subprocess, "run", fail)
    with pytest.raises(image_pull.BenchmarkExecutionError):
        image_pull._run(
            ["docker", "pull", "fixture@sha256:" + "c" * 64],
            tmp_path / failure,
            0,
            "pull",
        )
    assert "OPENAI_API_KEY" not in observed
    assert "TRIMEM_EVIDENCE_PASSPHRASE" not in observed
    assert (tmp_path / failure / "000-pull" / "stage.json").is_file()


def _read_lf(path: Path) -> str:
    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    assert not raw.startswith(b"\xef\xbb\xbf")
    return raw.decode("utf-8")


def test_isolated_preinstall_preflight_keeps_site_packages_and_adds_src(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    venv.EnvBuilder(with_pip=False).create(runtime)
    runtime_python = (
        runtime / "Scripts" / "python.exe"
        if os.name == "nt"
        else runtime / "bin" / "python"
    )
    purelib_result = subprocess.run(
        [
            str(runtime_python),
            "-c",
            "import sysconfig; print(sysconfig.get_path('purelib'))",
        ],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    purelib = Path(purelib_result.stdout.strip())
    purelib.mkdir(parents=True, exist_ok=True)
    (purelib / "trimem_dependency_probe.py").write_text(
        "TOKEN = 'dependency-site-packages'\n", encoding="utf-8"
    )
    scripts = tmp_path / "scripts"
    source = tmp_path / "src"
    scripts.mkdir()
    source.mkdir()
    (source / "trimem_source_probe.py").write_text(
        "TOKEN = 'source-tree'\n", encoding="utf-8"
    )
    (scripts / "trimem_dev_activation_diagnostic.py").write_text(
        "from trimem_dependency_probe import TOKEN as dependency_token\n"
        "from trimem_source_probe import TOKEN as source_token\n"
        "assert dependency_token == 'dependency-site-packages'\n"
        "assert source_token == 'source-tree'\n"
        "print('TRIMEM_ISOLATED_PREINSTALL_PREFLIGHT_PASS')\n",
        encoding="utf-8",
    )
    command = (
        "import runpy,sys; sys.path[:0]=['scripts','src','.']; "
        "sys.argv=['trimem_dev_activation_diagnostic.py','preflight']; "
        "runpy.run_path('scripts/trimem_dev_activation_diagnostic.py',"
        "run_name='__main__')"
    )
    completed = subprocess.run(
        [str(runtime_python), "-I", "-c", command],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "TRIMEM_ISOLATED_PREINSTALL_PREFLIGHT_PASS" in completed.stdout

    site_suppressed = subprocess.run(
        [str(runtime_python), "-I", "-S", "-c", command],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        text=True,
    )
    assert site_suppressed.returncode != 0
    assert "trimem_dependency_probe" in site_suppressed.stderr


def _approval(now: datetime) -> tuple[dict, dict]:
    policy = diagnostic.strict_json_load(ROOT / diagnostic.POLICY_PATH)
    bindings = {
        "diagnostic_id": "TRIMEM_V1_DEV_ACTIVATION_DIAGNOSTIC_001",
        "repository": "Scuttie/enterprise-shared-memory-poc",
        "git_head": "a" * 40,
        "workflow_run_id": 123456,
        "workflow_run_attempt": 2,
        "workflow_event": "push",
        "matrix_raw_sha256": "b" * 64,
        "policy_raw_sha256": "c" * 64,
        "source_bank_manifest_sha256": "d" * 64,
        "model_id": policy["frozen_inputs"]["model_lock"]["model_id"],
        "hard_caps": policy["hard_caps"],
    }
    document = approval_builder.build_approval_document(
        diagnostic_id=bindings["diagnostic_id"],
        repository=bindings["repository"],
        git_head=bindings["git_head"],
        workflow_run_id=bindings["workflow_run_id"],
        matrix_raw_sha256=bindings["matrix_raw_sha256"],
        policy_raw_sha256=bindings["policy_raw_sha256"],
        source_bank_manifest_sha256=bindings["source_bank_manifest_sha256"],
        model_id=bindings["model_id"],
        hard_caps=bindings["hard_caps"],
        approval_actor="independent-approver",
        approval_nonce="e" * 32,
        approved_at_utc=now.isoformat().replace("+00:00", "Z"),
        expires_at_utc=(now + timedelta(hours=1)).isoformat().replace(
            "+00:00", "Z"
        ),
        openai_api_key=TEST_API_KEY,
    )
    return document, bindings


def test_separate_workflow_has_clean_handshake_and_exact_attempt_2_production_job() -> None:
    text = _read_lf(WORKFLOW)
    contract, production = text.split("  diagnostic-execution:", 1)
    assert "pull_request:" in contract
    assert "push:" in contract
    assert "workflow_dispatch:" in contract
    assert "python scripts/trimem_dev_activation_diagnostic.py contract" in contract
    for required in (
        "reports/TRIMEM_DEV_ACTIVATION_DIAGNOSTIC*.md",
        "artifacts/trimem_v1/**",
        "configs/trimem_v1/**",
        "scripts/trimem_*.py",
        "tests/trimem/e2e/**",
        "scripts/trimem_freeze.py",
        "scripts/trimem_verify_ready.py",
        "configs/trimem_v1/dev_activation_source_bank_payloads/**",
        "configs/trimem_v1/m2_candidates/recall.json",
        "artifacts/trimem_v1/grader_image_lock.json",
        "scripts/trimem_benchmark_run.py",
        "scripts/trimem_d117_checkout_rehearsal.py",
        "scripts/trimem_d118_grader_factory_rehearsal.py",
        "src/enterprise_memory/trimem/**",
        "src/enterprise_memory/trimem/checkpoint.py",
        "src/enterprise_memory/trimem/retrieval_store.py",
        "tests/unit/test_trimem_dev_activation_executor.py",
        "tests/unit/test_trimem_dev_activation_github_capture.py",
        "tests/unit/test_trimem_working_retrieval.py",
        "tests/unit/test_trimem_postgres_retrieval.py",
    ):
        assert required in contract
    assert "secrets." not in contract
    assert "environment:" not in contract
    assert "diagnostic-approval-handshake:" in contract
    assert "github.run_attempt == 1" in contract
    assert "workflow_run_attempt=2" in contract
    assert "model_calls=0 grader_runs=0 paid_model_calls=0 total_usd=0" in contract
    assert (
        "if: github.event_name == 'push' && github.run_attempt == 2"
        in production
    )
    assert "github.run_attempt >= 2" not in production
    assert (
        "runs-on: [self-hosted, linux, x64, trimem-dev-activation-diagnostic]"
        in production
    )
    assert (
        "runs-on: [self-hosted, linux, x64, trimem-ubuntu-24.04, trimem-benchmark]"
        not in production
    )
    assert "timeout-minutes: 7200" in production
    assert "environment: trimem-benchmark-exec" in production
    assert production.count("          set -euo pipefail") > 0
    assert production.count("          set -euo pipefail\n          umask 077") == (
        production.count("          set -euo pipefail")
    )
    assert "Verify cached protected runner toolchain before setup-python" in production
    assert production.index(
        "Verify cached protected runner toolchain before setup-python"
    ) < production.index("actions/setup-python@")
    preinstall_order = (
        "Verify frozen source before any installation",
        "Install exact pinned GitHub CLI for evidence custody",
        "Verify exact pinned GitHub CLI before credentials",
        "Install hash-locked production dependencies",
        "Verify frozen diagnostic before editable code installation",
        "Install editable project after diagnostic preflight",
    )
    assert list(map(production.index, preinstall_order)) == sorted(
        map(production.index, preinstall_order)
    )
    assert (
        "python -I -S scripts/trimem_freeze.py --check --require-git-tracked"
        in production
    )
    assert (
        "python -I -c \"import runpy,sys; "
        "sys.path[:0]=['scripts','src','.']; "
        "sys.argv=['trimem_dev_activation_diagnostic.py','preflight']; "
        "runpy.run_path('scripts/trimem_dev_activation_diagnostic.py',"
        "run_name='__main__')\""
        in production
    )
    assert "python -I -S -c \"import runpy,sys" not in production
    assert "id: pinned_gh_install" in production
    assert "id: pinned_gh_verification" in production
    inventory_step = production[
        production.index("- name: Inventory complete restricted diagnostic evidence") :
        production.index("- name: Encrypt complete restricted diagnostic evidence")
    ]
    assert "if: always()" in inventory_step
    assert "pinned_gh_verification" not in inventory_step
    assert "secrets.TRIMEM_DEV_ACTIVATION_APPROVAL_B64" in production
    assert "python -I -S scripts/trimem_dev_activation_gate.py" in production
    assert '--output-approval "$RUNNER_TEMP/trimem-dev-activation-approval.json"' in production
    assert "python scripts/trimem_d117_checkout_rehearsal.py" in production
    assert production.index(
        "python -I -S scripts/trimem_freeze.py --check --require-git-tracked"
    ) < production.index("python -m pip install --require-hashes")
    assert "python scripts/trimem_install_pinned_gh.py" in production
    assert "python scripts/trimem_verify_gh_lock.py" in production
    assert "from trimem_harness_lock import prepare_harnesses" in production
    assert "scripts/trimem_official_harness_loader_preflight.py" in production
    assert "python scripts/trimem_d118_grader_factory_rehearsal.py" in production
    assert "--synthetic" not in production
    assert "python scripts/trimem_dev_activation_executor.py prepare-images" in production
    assert "python scripts/trimem_validate_openai_credential.py" in production
    assert "python scripts/trimem_verify_openai_key_binding.py" in production
    assert "python scripts/trimem_dev_activation_executor.py execute" in production
    assert "--workspace-root .trimem-exec/devdiag-workspaces" in production
    assert "first_executor_status" in production
    assert "retry_arguments+=(--resume)" in production
    assert "executor-invocation-2.stdout.log" in production
    assert "python scripts/trimem_dev_activation_diagnostic.py aggregate" in production
    assert "python scripts/trimem_dev_activation_executor.py cleanup-images" in production
    assert "python scripts/trimem_evidence_inventory.py" in production
    assert "openssl enc -aes-256-cbc -salt -pbkdf2" in production
    assert "python scripts/trimem_verify_remote_custody.py" in production
    for artifact_name in (
        "trimem-dev-activation-diagnostic-public",
        "trimem-dev-activation-diagnostic-restricted-encrypted",
        "trimem-dev-activation-diagnostic-evidence-inventory",
    ):
        assert f"name: {artifact_name}" in production
    custody_step = production[
        production.index(
            "- name: Verify durable external artifact custody before plaintext cleanup"
        ) : production.index("- name: Upload sanitized diagnostic custody result")
    ]
    assert "steps.public_upload.outcome == 'success' ||" in custody_step
    assert "steps.public_upload.outcome == 'skipped'" in custody_step
    assert "PUBLIC_UPLOAD_OUTCOME: ${{ steps.public_upload.outcome }}" in custody_step
    assert (
        "--public-artifact-name trimem-dev-activation-diagnostic-public"
        in custody_step
    )
    assert '--public-artifact-id "$PUBLIC_ARTIFACT_ID"' in custody_step
    assert '--public-artifact-digest "$PUBLIC_ARTIFACT_DIGEST"' in custody_step
    assert (
        "--restricted-artifact-name "
        "trimem-dev-activation-diagnostic-restricted-encrypted"
        in custody_step
    )
    assert (
        "--inventory-artifact-name "
        "trimem-dev-activation-diagnostic-evidence-inventory"
        in custody_step
    )
    custody_gh_step = production[
        production.index(
            "- name: Ensure exact pinned GitHub CLI for every custody path"
        ) : production.index("- name: Inventory complete restricted diagnostic evidence")
    ]
    assert "if: always()" in custody_gh_step
    assert "python scripts/trimem_install_pinned_gh.py" in custody_gh_step
    assert "python scripts/trimem_verify_gh_lock.py" in custody_gh_step
    assert 'printf \'%s\\n\' "$observed_bin" >> "$GITHUB_PATH"' in custody_gh_step
    assert production.index(
        "- name: Ensure exact pinned GitHub CLI for every custody path"
    ) < production.index("- name: Inventory complete restricted diagnostic evidence")
    assert production.count(
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
    ) == 4
    ordered = (
        "python scripts/trimem_d117_checkout_rehearsal.py",
        "from trimem_harness_lock import prepare_harnesses",
        "scripts/trimem_official_harness_loader_preflight.py",
        "python scripts/trimem_d118_grader_factory_rehearsal.py",
        "python -I -S scripts/trimem_dev_activation_gate.py",
        "python scripts/trimem_dev_activation_executor.py prepare-images",
        "python scripts/trimem_validate_openai_credential.py",
        "python scripts/trimem_verify_openai_key_binding.py",
        "python scripts/trimem_dev_activation_executor.py execute",
        "python scripts/trimem_dev_activation_diagnostic.py aggregate",
        "python scripts/trimem_dev_activation_executor.py cleanup-images",
        "python scripts/trimem_evidence_inventory.py",
        "openssl enc -aes-256-cbc -salt -pbkdf2",
        "python scripts/trimem_verify_remote_custody.py",
        "Remove plaintext and temporary diagnostic execution material",
    )
    assert list(map(production.index, ordered)) == sorted(
        map(production.index, ordered)
    )
    assert set(
        re.findall(r"\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)", text)
    ) == {
        "OPENAI_API_KEY",
        "TRIMEM_DEV_ACTIVATION_APPROVAL_B64",
        "TRIMEM_EVIDENCE_PASSPHRASE",
    }
    for forbidden in (
        "github.run_attempt >= 2",
        "trimem_action_canary.py",
        "python scripts/trimem_benchmark_run.py",
        "python scripts/trimem_official_grader.py",
        "python scripts/trimem_pull_locked_images.py",
        "docker run",
        "continue-on-error",
        "|| true",
        "pull_request_target:",
    ):
        assert forbidden not in text
    for forbidden in ("postgres", "qdrant", "alembic", "heldout"):
        assert forbidden not in production.casefold()


def test_gate_source_has_no_provider_grader_or_benchmark_import() -> None:
    source = _read_lf(ROOT / "scripts/trimem_dev_activation_gate.py")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(
        marker in name
        for name in imported
        for marker in ("provider", "grader", "benchmark_run", "docker")
    )


def test_external_approval_base64_is_strict_and_bom_fails_closed() -> None:
    now = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
    document, _ = _approval(now)
    raw = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert raw == gate.canonical_approval_bytes(document)
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\x00" not in raw and b"\r" not in raw and b"\n" not in raw
    observed, observed_raw = gate.decode_approval_base64(
        base64.b64encode(raw).decode("ascii")
    )
    assert observed == document
    assert observed_raw == raw

    with pytest.raises(gate.DiagnosticApprovalError, match="BOM"):
        gate.decode_approval_base64(
            base64.b64encode(b"\xef\xbb\xbf" + raw).decode("ascii")
        )
    with pytest.raises(gate.DiagnosticApprovalError, match="whitespace"):
        gate.decode_approval_base64(base64.b64encode(raw).decode("ascii") + "\n")
    noncanonical = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
    with pytest.raises(gate.DiagnosticApprovalError, match="not canonical"):
        gate.decode_approval_base64(
            base64.b64encode(noncanonical).decode("ascii")
        )


def test_external_approval_binds_fresh_run_attempt_head_hashes_and_caps() -> None:
    now = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
    document, bindings = _approval(now)
    approval = gate.validate_approval_document(document, now=now, **bindings)
    assert approval["approved_phase"] == "POST_DEV_ACTIVATION_DIAGNOSTIC"

    wrong_event = dict(bindings)
    wrong_event["workflow_event"] = "workflow_dispatch"
    with pytest.raises(
        gate.DiagnosticApprovalError,
        match="approval binding mismatch: workflow_event",
    ):
        gate.validate_approval_document(document, now=now, **wrong_event)

    wrong_attempt = dict(bindings)
    wrong_attempt["workflow_run_attempt"] = 3
    with pytest.raises(gate.DiagnosticApprovalError, match="run_attempt"):
        gate.validate_approval_document(document, now=now, **wrong_attempt)
    attempt_three = dict(bindings)
    attempt_three["workflow_run_attempt"] = 3
    attempt_three_document = json.loads(json.dumps(document))
    attempt_three_document["approval"]["approved_workflow_run_attempt"] = 3
    with pytest.raises(gate.DiagnosticApprovalError, match="exactly 2"):
        gate.validate_approval_document(
            attempt_three_document,
            now=now,
            **attempt_three,
        )
    attempt_one = dict(bindings)
    attempt_one["workflow_run_attempt"] = 1
    attempt_one_document = json.loads(json.dumps(document))
    attempt_one_document["approval"]["approved_workflow_run_attempt"] = 1
    with pytest.raises(gate.DiagnosticApprovalError, match="exactly 2"):
        gate.validate_approval_document(attempt_one_document, now=now, **attempt_one)
    with pytest.raises(gate.DiagnosticApprovalError, match="not currently valid"):
        gate.validate_approval_document(
            document,
            now=now + timedelta(hours=2),
            **bindings,
        )
    overlong = json.loads(json.dumps(document))
    overlong["approval"]["expires_at_utc"] = (
        now + timedelta(days=7, seconds=1)
    ).isoformat().replace("+00:00", "Z")
    with pytest.raises(gate.DiagnosticApprovalError, match="seven-day"):
        gate.validate_approval_document(overlong, now=now, **bindings)


def test_diagnostic_openai_key_commitment_is_key_and_run_bound() -> None:
    from trimem_openai_model_access_check import (
        verify_approval_credential_binding,
    )

    document, _ = _approval(datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc))
    assert verify_approval_credential_binding(TEST_API_KEY, document)
    assert not verify_approval_credential_binding(TEST_API_KEY + "x", document)
    for field, replacement in (
        ("approval_nonce", "f" * 32),
        ("git_head", "f" * 40),
        ("approved_model_id", "gpt-5.4-mini-wrong-snapshot"),
    ):
        changed = json.loads(json.dumps(document))
        changed["approval"][field] = replacement
        assert not verify_approval_credential_binding(TEST_API_KEY, changed)


def test_gate_main_materializes_exact_approved_bytes_and_refuses_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    document, bindings = _approval(now)
    raw = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    monkeypatch.setenv(
        "TRIMEM_DEV_ACTIVATION_APPROVAL_B64",
        base64.b64encode(raw).decode("ascii"),
    )
    monkeypatch.setattr(gate, "_git_head", lambda _root: bindings["git_head"])
    monkeypatch.setattr(
        gate,
        "load_and_validate_contract",
        lambda *_args, **_kwargs: (
            {"diagnostic_id": bindings["diagnostic_id"]},
            {
                "frozen_inputs": {
                    "model_lock": {"model_id": bindings["model_id"]}
                },
                "hard_caps": bindings["hard_caps"],
            },
            [{} for _ in range(36)],
            bindings["source_bank_manifest_sha256"],
        ),
    )
    monkeypatch.setattr(
        gate,
        "file_sha256",
        lambda path: (
            bindings["matrix_raw_sha256"]
            if path.name == "dev_activation_manifest.json"
            else bindings["policy_raw_sha256"]
        ),
    )
    output = tmp_path / "approval.json"
    argv = [
        "--repository",
        bindings["repository"],
        "--workflow-run-id",
        str(bindings["workflow_run_id"]),
        "--workflow-run-attempt",
        "2",
        "--workflow-event",
        "push",
        "--output-approval",
        str(output),
    ]
    assert gate.main(argv) == 0
    assert output.read_bytes() == raw
    assert gate.main(argv) == 2
    assert output.read_bytes() == raw


def test_static_readiness_reports_source_bank_ready_without_authorizing_exec() -> None:
    state = readiness.validate_dev_activation_diagnostic_contract(
        require_git_tracked=False
    )
    assert state == {
        "status": "FROZEN_CONTRACT_SOURCE_BANK_READY",
        "diagnostic_id": "TRIMEM_V1_DEV_ACTIVATION_DIAGNOSTIC_001",
        "cell_count": 36,
        "arms": ["C0", "C1", "C2"],
        "source_bank_plan_status": "FROZEN_PRE_EXEC_SOURCE_SELECTION",
        "source_bank_plan_raw_sha256": source_bank.file_sha256(
            ROOT / source_bank.PLAN_PATH
        ),
        "source_bank_source_mode": "FROZEN_PUBLIC_GITHUB_ORACLE_SOURCE_PRS",
        "source_bank_declared_oracle_pr_count": 12,
        "source_bank_status": "FROZEN_VERIFIED_TARGET_DISJOINT",
        "source_bank_manifest_sha256": (
            "8a0600e8d18f5234bd35d675f8e5cb8eb827aac4e4498547db02fc689a83d309"
        ),
        "source_bank_snapshot_sha256": (
            "55fe3c03ef545181986605166247f78896c5fcd2db37535d19f574781c16be1e"
        ),
        "source_bank_covered_target_count": 12,
        "source_bank_zero_candidate_target_count": 0,
        "selected_m2_candidate_id": "recall",
        "historical_exec_022_request_head": (
            "889f4fc0d461d812b531f9413aeaceb2ec3b9fff"
        ),
        "selected_runtime_lock_sha256": (
            "f38dbb148e7c7e0573bfab87400ebb9c0c4a786f888d4315d214fdca289fb581"
        ),
        "adaptive_runtime_lock_sha256": (
            "c31840b1413fe045e94bef1949419f72c856eda9abbcc69c52bffc700bbf4652"
        ),
        "external_approval_status": "MISSING_NOT_EVALUATED_BY_STATIC_READINESS",
        "execution_allowed": False,
        "model_calls_for_readiness": 0,
        "official_grader_runs_for_readiness": 0,
        "hard_caps": diagnostic.strict_json_load(
            ROOT / diagnostic.POLICY_PATH
        )["hard_caps"],
    }


def test_freeze_allowlists_complete_frozen_diagnostic_and_source_bank_closure() -> None:
    required = {
        "configs/trimem_v1/dev_activation_manifest.json",
        "configs/trimem_v1/dev_activation_policy.json",
        "configs/trimem_v1/dev_activation_source_bank_manifest.json",
        "configs/trimem_v1/dev_activation_source_bank_plan.json",
        "artifacts/trimem_v1/dev_activation_diagnostic/exec_022_abstention_recoverability.json",
        "artifacts/trimem_v1/dev_activation_diagnostic/exec_022_abstention_projection.json",
        "artifacts/trimem_v1/dev_activation_diagnostic/source_bank_candidate_audit.json",
        "artifacts/trimem_v1/dev_activation_diagnostic/source_chronology_cache.json",
        "scripts/trimem_dev_activation_diagnostic.py",
        "scripts/trimem_dev_activation_approval.py",
        "scripts/trimem_dev_activation_executor.py",
        "scripts/trimem_dev_activation_gate.py",
        "scripts/trimem_dev_activation_github_capture.py",
        "scripts/trimem_dev_activation_source_bank.py",
        "src/enterprise_memory/trimem/adaptive_horizon.py",
        "tests/unit/test_trimem_adaptive_horizon.py",
        "tests/unit/test_trimem_dev_activation_diagnostic.py",
        "tests/unit/test_trimem_dev_activation_executor.py",
        "tests/unit/test_trimem_dev_activation_github_capture.py",
        "tests/unit/test_trimem_dev_activation_readiness.py",
        "tests/unit/test_trimem_dev_activation_source_bank.py",
        ".github/workflows/ci-trimem-dev-activation-diagnostic.yml",
        "reports/TRIMEM_DEV_ACTIVATION_DIAGNOSTIC.md",
        "reports/TRIMEM_DEV_ACTIVATION_DIAGNOSTIC_CONTRACT.md",
    }
    assert required <= set(freeze.FROZEN_PATHS)
    assert all((ROOT / relative).is_file() for relative in required)
    assert set(freeze.DEV_ACTIVATION_SOURCE_BANK_PAYLOAD_PATHS) == {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "configs/trimem_v1/dev_activation_source_bank_payloads").iterdir()
        if path.is_file()
    }
    assert set(freeze.DEV_ACTIVATION_SOURCE_BANK_RAW_EVIDENCE_PATHS) == {
        path.relative_to(ROOT).as_posix()
        for path in (
            ROOT / "artifacts/trimem_v1/dev_activation_diagnostic/github_raw"
        ).iterdir()
        if path.is_file()
    }
    attributes = _read_lf(ROOT / ".gitattributes")
    assert (
        "artifacts/trimem_v1/dev_activation_diagnostic/github_raw/** -text"
        in attributes
    )


def test_source_bank_plan_is_credential_free_and_frozen_before_results() -> None:
    plan, development, grader, specs = source_bank.load_committed_contracts(ROOT)
    assert plan["status"] == "FROZEN_PRE_EXEC_SOURCE_SELECTION"
    assert plan["execution_authorized"] is False
    assert plan["public_github_capture_allowed"] is True
    assert plan["model_or_grader_calls_allowed"] is False
    assert plan["read_only_same_snapshot_for_C1_and_C2"] is True
    assert development["target_set_sha256"] == (
        "e7da59b3c2638c89da4e333a7391851e992c122acac11bc9edf60619cfd5eff2"
    )
    assert set(specs) == set(source_bank.REQUIRED_DATASETS)
    assert grader["schema"] == "trimem/grader-lock/1.0"


def test_recall_dqn_claim_absent_and_adaptive_allowance_is_per_subtask() -> None:
    policy = diagnostic.strict_json_load(ROOT / diagnostic.POLICY_PATH)
    assert policy["development_protocol_binding"] == {
        "adaptive_runtime_lock_sha256": (
            "c31840b1413fe045e94bef1949419f72c856eda9abbcc69c52bffc700bbf4652"
        ),
        "historical_runtime_lock_sha256": (
            "f38dbb148e7c7e0573bfab87400ebb9c0c4a786f888d4315d214fdca289fb581"
        ),
        "only_registered_runtime_change": (
            "ENABLE_IDENTICAL_FROZEN_ADAPTIVE_HORIZON_FOR_C0_C1_C2"
        ),
        "public_results_raw_sha256": (
            "a983bcd807d80520349942d296d8b4910bf7c5eb4f1079185aca1937adacd9a1"
        ),
        "selected_candidate_id": "recall",
        "selection_execution_head": "889f4fc0d461d812b531f9413aeaceb2ec3b9fff",
        "selection_rule_outcome_reoptimized": False,
        "selection_workflow_run_attempt": 1,
        "selection_workflow_run_id": 34292287112,
        "status": (
            "FROZEN_EXEC_022_SELECTED_RECALL_WITH_DIAGNOSTIC_ADAPTIVE_HORIZON"
        ),
    }
    assert policy["arms"]["C2"]["bypass"] == [
        "RETRIEVAL_SCORE_ADMISSION_MIN_CONFIDENCE",
        "RETRIEVAL_SCORE_ADMISSION_MIN_MARGIN",
    ]
    assert "retention actions only" in policy["arms"]["C1"]["dqn_semantics"]
    assert policy["historical_abstention_projection"][
        "dqn_recall_action_claim_allowed"
    ] is False
    assert policy["reason_taxonomy"][
        "router_selected_abstain_with_valid_candidate"
    ] == []
    assert policy["source_bank"]["runtime_safe_pool_metadata"] == {
        "changed_paths_role": "SEPARATE_CANONICAL_SOURCE_FEATURE_NOT_PATH_SCOPE",
        "path_scope": "**",
        "permission_scope": "PUBLIC_READ",
        "tenant_scope": "BENCHMARK_ISOLATED",
        "version_scope": "EXACT_SOURCE_COMMIT",
    }
    assert policy["source_bank"]["payload_root"] == (
        "dev_activation_source_bank_payloads"
    )
    horizon = policy["adaptive_horizon"]
    assert horizon["extension_budget_scope"] == "PER_SUBTASK_ACTIVE_NODE"
    assert horizon["max_extensions_per_subtask"] == 2
    assert horizon["max_steps_per_subtask"] == 16
    assert "max_extensions_per_task" not in horizon
    assert policy["canary_policy"] == {
        "authorized": False,
        "included_in_scientific_model_calls": False,
        "model_call_cap": 0,
        "required_authority_if_proposed_later": "SEPARATE_EXTERNAL_CANARY_APPROVAL",
    }
    assert policy["hard_caps"] == {
        "cached_input_tokens": 18_000_000,
        "decomposition_calls": 36,
        "extraction_calls": 36,
        "grader_containers": 36,
        "input_tokens": 18_000_000,
        "max_input_tokens_per_task_arm": 500_000,
        "max_output_tokens_per_task_arm": 65_536,
        "model_calls": 936,
        "model_calls_per_task_arm": 26,
        "official_grader_runs": 36,
        "output_tokens": 2_359_296,
        "paid_model_calls": 936,
        "protocol_canary_calls": 0,
        "scientific_model_calls": 936,
        "solve_calls": 864,
        "task_arm_runs": 36,
        "total_usd": "25.000000000000",
        "uncached_token_cost_ceiling_usd": "24.116832000000",
    }


def test_historical_exec_022_is_static_evidence_only_after_diagnostic_commit() -> None:
    policy = diagnostic.strict_json_load(ROOT / diagnostic.POLICY_PATH)
    historical_head = policy["development_protocol_binding"][
        "selection_execution_head"
    ]

    assert historical_head != readiness.git_head()
    assert (
        readiness.validate_historical_d123_exec_022_evidence(historical_head)
        == historical_head
    )
    with pytest.raises(ValueError, match="commits exist after the active `_022` request"):
        readiness.validate_d123_exec_022_activation()


def test_historical_exec_022_evidence_rejects_nonancestor_and_old_dev_exec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import trimem_benchmark_run as benchmark

    historical_head = diagnostic.strict_json_load(
        ROOT / diagnostic.POLICY_PATH
    )["development_protocol_binding"]["selection_execution_head"]
    monkeypatch.setattr(readiness, "_execution_head_is_ancestor", lambda _head: False)
    with pytest.raises(ValueError, match="is not a strict ancestor"):
        readiness.validate_historical_d123_exec_022_evidence(historical_head)

    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", benchmark.DEVELOPMENT_WORKFLOW_REF)
    monkeypatch.setenv("GITHUB_WORKFLOW_SHA", readiness.git_head())
    with pytest.raises(
        benchmark.BenchmarkExecutionError,
        match="trigger commit is not the exclusive `_022` sentinel addition",
    ):
        benchmark.validate_exec_approval(
            "development",
            tmp_path / "missing-old-dev-approval.json",
        )
