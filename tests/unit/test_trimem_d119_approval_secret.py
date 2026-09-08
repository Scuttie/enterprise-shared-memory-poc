from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_d119_approval_secret as producer  # noqa: E402
from trimem_exec_approval import (  # noqa: E402
    DEVELOPMENT_APPROVAL_FIELDS,
    build_external_approval_document,
)


def _accept_pinned_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        producer,
        "validate_pinned_gh_binary",
        lambda _path: {"status": "PASS"},
    )


def _document() -> dict[str, object]:
    return {
        "approval": {
            "approved_git_commit": "a" * 40,
            "approved_workflow_run_attempt": 1,
        },
        "approved_request_sha256": "sha256:" + "b" * 64,
        "request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_019",
        "schema": "trimem/external-exec-approval/1.2",
    }


def test_d119_producer_emits_exact_canonical_bytes_without_bom_or_whitespace() -> None:
    raw, encoded = producer.encode_approval_document(_document())

    assert raw == json.dumps(
        _document(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert encoded == base64.b64encode(raw)
    assert encoded.isascii()
    assert all(forbidden not in encoded for forbidden in (b"\r", b"\n", b" "))
    assert producer.validate_encoded_approval(encoded) == raw


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: b"\xef\xbb\xbf" + value, "UTF-8 BOM"),
        (lambda value: value + b"\r", "CR"),
        (lambda value: value + b"\n", "LF"),
        (lambda value: value[:4] + b" " + value[4:], "space"),
    ),
)
def test_d119_producer_rejects_bom_cr_lf_and_space(
    mutation: object, message: str
) -> None:
    _, encoded = producer.encode_approval_document(_document())

    with pytest.raises(producer.ApprovalSecretProducerError, match=message):
        producer.validate_encoded_approval(mutation(encoded))  # type: ignore[operator]


def test_d119_install_uses_python_binary_stdin_without_shell_or_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh = tmp_path / "gh"
    gh.write_bytes(b"pinned fixture")
    _, encoded = producer.encode_approval_document(_document())
    observed: dict[str, object] = {}

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        observed["command"] = command
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    _accept_pinned_gh(monkeypatch)
    monkeypatch.setattr(producer.subprocess, "run", run)
    evidence = producer.install_approval_secret(
        encoded,
        gh_binary=gh,
        repository="Scuttie/enterprise-shared-memory-poc",
    )

    assert observed.pop("command") == [
            str(gh),
            "secret",
            "set",
            "TRIMEM_EXEC_APPROVAL_B64",
            "--env",
            "trimem-benchmark-exec",
            "--repo",
            "Scuttie/enterprise-shared-memory-poc",
        ]
    assert observed.pop("input") == encoded
    assert observed.pop("capture_output") is True
    assert observed.pop("check") is True
    assert observed.pop("shell") is False
    assert observed.pop("text") is False
    assert observed.pop("timeout") == producer.SECRET_SUBPROCESS_TIMEOUT_SECONDS
    child_env = observed.pop("env")
    assert isinstance(child_env, dict)
    assert producer.REQUIRED_SECRET_NAMES.isdisjoint(child_env)
    assert not any(name.upper().startswith("DOCKER_") for name in child_env)
    assert observed == {}
    assert evidence["transport"] == "PYTHON_SUBPROCESS_BINARY_STDIN"
    assert "secret_sha256" not in evidence


def test_d119_all_three_environment_secrets_use_exact_binary_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh = tmp_path / "gh"
    gh.write_bytes(b"pinned fixture")
    _, approval = producer.encode_approval_document(_document())
    values = {
        "OPENAI_API_KEY": b"fixture-openai-key-material-123",
        "TRIMEM_EVIDENCE_PASSPHRASE": b"A9!evidence-passphrase-fixture-0123456789",
        "TRIMEM_EXEC_APPROVAL_B64": approval,
    }
    calls: list[tuple[list[str], dict[str, object]]] = []
    installed: set[str] = set()

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, kwargs))
        if command[1:3] == ["secret", "list"]:
            stdout = json.dumps(
                [{"name": name} for name in sorted(installed)]
            ).encode("utf-8")
        elif command[1:3] == ["secret", "set"]:
            installed.add(command[3])
            stdout = b""
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    _accept_pinned_gh(monkeypatch)
    monkeypatch.setattr(producer.subprocess, "run", run)
    evidence = producer.install_required_environment_secrets(
        values,
        gh_binary=gh,
        repository="Scuttie/enterprise-shared-memory-poc",
    )

    set_calls = [item for item in calls if item[0][1:3] == ["secret", "set"]]
    assert len(set_calls) == 3
    assert {command[3] for command, _ in set_calls} == producer.REQUIRED_SECRET_NAMES
    for command, kwargs in set_calls:
        assert command[:3] == [str(gh), "secret", "set"]
        assert kwargs["input"] == values[command[3]]
        assert kwargs["capture_output"] is True
        assert kwargs["check"] is True
        assert kwargs["shell"] is False
        assert kwargs["text"] is False
        assert type(kwargs["input"]) is bytes
    assert installed == producer.REQUIRED_SECRET_NAMES
    assert evidence["installed_secret_names"] == sorted(producer.REQUIRED_SECRET_NAMES)
    assert evidence["transport"] == "PYTHON_SUBPROCESS_BINARY_STDIN"
    assert all("secret_sha256" not in row for row in evidence["results"])
    assert "delete every name" in evidence["failure_cleanup_contract"]


@pytest.mark.parametrize(
    "names",
    (
        {"TRIMEM_EXEC_APPROVAL_B64", "OPENAI_API_KEY"},
        {
            "TRIMEM_EXEC_APPROVAL_B64",
            "OPENAI_API_KEY",
            "TRIMEM_EVIDENCE_PASSPHRASE",
            "UNEXPECTED",
        },
    ),
)
def test_d119_all_secret_installer_rejects_missing_or_extra_names(
    names: set[str], tmp_path: Path
) -> None:
    gh = tmp_path / "gh"
    gh.write_bytes(b"pinned fixture")
    values = {name: b"fixture-value-that-is-long-enough" for name in names}

    with pytest.raises(
        producer.ApprovalSecretProducerError,
        match="secret name set differs",
    ):
        producer.install_required_environment_secrets(
            values,
            gh_binary=gh,
            repository="Scuttie/enterprise-shared-memory-poc",
        )


@pytest.mark.parametrize(
    ("repository", "environment", "message"),
    (
        (
            "Scuttie/wrong-repository",
            producer.APPROVAL_ENVIRONMENT,
            "repository identity differs",
        ),
        (
            producer.APPROVAL_REPOSITORY,
            "wrong-environment",
            "environment identity differs",
        ),
        (
            producer.APPROVAL_REPOSITORY,
            "trimem-benchmark-exec\n",
            "environment identity differs",
        ),
    ),
)
def test_d119_secret_install_is_bound_to_exact_repository_and_environment(
    repository: str,
    environment: str,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh = tmp_path / "gh"
    gh.write_bytes(b"pinned fixture")
    _, encoded = producer.encode_approval_document(_document())
    _accept_pinned_gh(monkeypatch)

    with pytest.raises(producer.ApprovalSecretProducerError, match=message):
        producer.install_environment_secret(
            producer.APPROVAL_SECRET_NAME,
            encoded,
            gh_binary=gh,
            repository=repository,
            environment=environment,
        )


@pytest.mark.parametrize(
    ("name", "value", "message"),
    (
        ("OPENAI_API_KEY", b"\xef\xbb\xbffixture-openai-key-material-123", "NON_ASCII"),
        ("OPENAI_API_KEY", b"fixture-openai-key-material-123\n", "CONTROL_CHARACTER"),
        (
            "TRIMEM_EVIDENCE_PASSPHRASE",
            b"\xef\xbb\xbfpassphrase-fixture-that-is-long-enough",
            "UTF-8 BOM",
        ),
        (
            "TRIMEM_EVIDENCE_PASSPHRASE",
            b"passphrase fixture that is long enough",
            "whitespace or control",
        ),
    ),
)
def test_d119_nonapproval_secret_bytes_fail_closed(
    name: str, value: bytes, message: str
) -> None:
    with pytest.raises(producer.ApprovalSecretProducerError, match=message):
        producer.validate_environment_secret(name, value)


def test_d119_failed_secret_installation_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh = tmp_path / "gh"
    gh.write_bytes(b"pinned fixture")
    _, encoded = producer.encode_approval_document(_document())

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.CalledProcessError(
            1,
            command,
            output=b"must-not-surface",
            stderr=b"must-not-surface",
        )

    monkeypatch.setattr(producer.subprocess, "run", run)
    _accept_pinned_gh(monkeypatch)
    with pytest.raises(
        producer.ApprovalSecretProducerError,
        match="bytes-only protected environment secret installation failed",
    ) as failure:
        producer.install_approval_secret(
            encoded,
            gh_binary=gh,
            repository="Scuttie/enterprise-shared-memory-poc",
        )
    assert "must-not-surface" not in str(failure.value)


def test_d119_partial_required_install_fails_closed_with_cleanup_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh = tmp_path / "gh"
    gh.write_bytes(b"pinned fixture")
    _, approval = producer.encode_approval_document(_document())
    values = {
        "OPENAI_API_KEY": b"fixture-openai-key-material-123",
        "TRIMEM_EVIDENCE_PASSPHRASE": b"A9!evidence-passphrase-fixture-0123456789",
        "TRIMEM_EXEC_APPROVAL_B64": approval,
    }
    set_calls = 0
    delete_calls: list[str] = []
    installed: set[str] = set()

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal set_calls
        if command[1:3] == ["secret", "list"]:
            stdout = json.dumps(
                [{"name": name} for name in sorted(installed)]
            ).encode("utf-8")
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")
        if command[1:3] == ["secret", "set"]:
            set_calls += 1
            if set_calls == 2:
                raise subprocess.CalledProcessError(1, command, stderr=b"private")
            installed.add(command[3])
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
        if command[1:3] == ["secret", "delete"]:
            delete_calls.append(command[3])
            installed.discard(command[3])
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
        raise AssertionError(command)

    _accept_pinned_gh(monkeypatch)
    monkeypatch.setattr(producer.subprocess, "run", run)
    with pytest.raises(
        producer.ApprovalSecretProducerError,
        match="installed prefix was rolled back to the verified empty state",
    ) as failure:
        producer.install_required_environment_secrets(
            values,
            gh_binary=gh,
            repository="Scuttie/enterprise-shared-memory-poc",
        )
    assert set_calls == 2
    assert installed == set()
    assert set(delete_calls) == producer.REQUIRED_SECRET_NAMES
    assert "private" not in str(failure.value)
    assert producer.PARTIAL_INSTALL_CLEANUP_CONTRACT.startswith(
        "Before protected-run approval"
    )


def test_d119_timeout_after_remote_mutation_rolls_back_all_three_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh = tmp_path / "gh"
    gh.write_bytes(b"pinned fixture")
    _, approval = producer.encode_approval_document(_document())
    values = {
        "OPENAI_API_KEY": b"fixture-openai-key-material-123",
        "TRIMEM_EVIDENCE_PASSPHRASE": b"A9!evidence-passphrase-fixture-0123456789",
        "TRIMEM_EXEC_APPROVAL_B64": approval,
    }
    installed: set[str] = set()
    deleted: list[str] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if command[1:3] == ["secret", "list"]:
            stdout = json.dumps(
                [{"name": name} for name in sorted(installed)]
            ).encode("utf-8")
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")
        if command[1:3] == ["secret", "set"]:
            installed.add(command[3])
            raise subprocess.TimeoutExpired(command, timeout=60)
        if command[1:3] == ["secret", "delete"]:
            deleted.append(command[3])
            installed.discard(command[3])
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
        raise AssertionError(command)

    _accept_pinned_gh(monkeypatch)
    monkeypatch.setattr(producer.subprocess, "run", run)
    with pytest.raises(
        producer.ApprovalSecretProducerError,
        match="rolled back to the verified empty state",
    ):
        producer.install_required_environment_secrets(
            values,
            gh_binary=gh,
            repository="Scuttie/enterprise-shared-memory-poc",
        )
    assert set(deleted) == producer.REQUIRED_SECRET_NAMES
    assert installed == set()


def test_d119_cli_has_no_single_secret_install_route() -> None:
    parser = producer.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--approval-json",
                "approval.json",
                "--approval-b64-output",
                "approval.b64",
                "--install",
            ]
        )


def test_d119_cli_writes_encoded_output_with_write_bytes(tmp_path: Path) -> None:
    raw, encoded = producer.encode_approval_document(_document())
    approval_path = tmp_path / "approval.json"
    output_path = tmp_path / "approval.b64"
    approval_path.write_bytes(raw)

    assert producer.main(
        [
            "--approval-json",
            str(approval_path),
            "--approval-b64-output",
            str(output_path),
        ]
    ) == 0
    assert output_path.read_bytes() == encoded


def test_d119_loader_rejects_noncanonical_json_source_bytes(tmp_path: Path) -> None:
    raw, _ = producer.encode_approval_document(_document())
    approval_path = tmp_path / "approval.json"
    approval_path.write_bytes(raw + b"\n")

    with pytest.raises(
        producer.ApprovalSecretProducerError,
        match="source bytes are not canonical",
    ):
        producer.load_canonical_approval(approval_path)


def test_d119_required_install_prevalidates_full_run_and_key_binding(
    tmp_path: Path,
) -> None:
    key = b"fixture-openai-key-material-123"
    execution_head = "a" * 40
    source_head = "b" * 40
    run_id = "34200000000"
    request = {
        "exact_model": {"model_id": "gpt-5.4-mini-2026-03-17"},
        "phase": "DEVELOPMENT_TUNING",
        "request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_019",
        "required_external_approval_fields": list(DEVELOPMENT_APPROVAL_FIELDS),
        "source_head": source_head,
    }
    hard_cap = {
        "benchmark_grader_containers": 72,
        "input_tokens": 36_004_096,
        "output_tokens": 4_720_640,
        "paid_model_calls": 1_873,
        "task_arm_runs": 72,
        "total_usd": 50.0,
    }
    paths = {
        "request": tmp_path / "request.json",
        "policy": tmp_path / "policy.json",
        "cost": tmp_path / "cost.json",
        "freeze": tmp_path / "freeze.json",
    }
    paths["request"].write_bytes(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    )
    paths["policy"].write_bytes(b"{}")
    paths["cost"].write_bytes(
        json.dumps(
            {"phase_hard_caps": {"DEVELOPMENT_TUNING": hard_cap}},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    paths["freeze"].write_bytes(b'{"schema":"fixture"}')
    document = build_external_approval_document(
        request_id=request["request_id"],
        request_sha256=producer.hashlib.sha256(paths["request"].read_bytes()).hexdigest(),
        git_commit=execution_head,
        freeze_sha256=producer.hashlib.sha256(paths["freeze"].read_bytes()).hexdigest(),
        phase="DEVELOPMENT_TUNING",
        task_arm_runs=72,
        paid_model_call_cap=1_873,
        input_token_cap=36_004_096,
        output_token_cap=4_720_640,
        currency_hard_cap=50.0,
        grader_containers=72,
        workflow_run_id=int(run_id),
        workflow_run_attempt=1,
        legal_terms_acceptance=True,
        approval_actor="fixture-actor",
        approval_timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        source_git_commit=source_head,
        openai_api_key=key,
        approval_nonce="fixture-nonce-0123456789",
        model_id=request["exact_model"]["model_id"],
    )

    validated = producer.validate_run_bound_development_approval(
        document,
        openai_api_key=key,
        request_path=paths["request"],
        policy_request_path=paths["policy"],
        cost_plan_path=paths["cost"],
        freeze_path=paths["freeze"],
        git_head=execution_head,
        source_head=source_head,
        workflow_run_id=run_id,
        workflow_run_attempt="1",
    )
    assert validated["approved_workflow_run_id"] == int(run_id)

    with pytest.raises(
        producer.ApprovalSecretProducerError,
        match="run-bound external approval validation failed",
    ):
        producer.validate_run_bound_development_approval(
            document,
            openai_api_key=key,
            request_path=paths["request"],
            policy_request_path=paths["policy"],
            cost_plan_path=paths["cost"],
            freeze_path=paths["freeze"],
            git_head=execution_head,
            source_head=source_head,
            workflow_run_id="34200000001",
            workflow_run_attempt="1",
        )
