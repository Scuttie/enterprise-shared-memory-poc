"""Create and install the DEV approval secret through a bytes-only boundary.

This module deliberately keeps approval construction separate from secret
transport.  It canonicalizes an already-built external approval document,
encodes it with :mod:`base64`, and supplies the exact encoded bytes to the
pinned GitHub CLI over a binary subprocess stdin pipe.  PowerShell text I/O,
shell interpolation, clipboard transfer, and Unicode repair are not part of
the contract.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from enterprise_memory.providers.openai_credential import (  # noqa: E402
    OpenAICredentialValidationError,
    validate_openai_api_key,
    verify_openai_key_commitment,
)
from trimem_exec_approval import (  # noqa: E402
    ApprovalValidationError,
    validate_external_approval_document,
)
from trimem_install_pinned_gh import (  # noqa: E402
    GhCliInstallError,
    load_gh_cli_lock,
    verify_observer_gh,
)

APPROVAL_SECRET_NAME = "TRIMEM_EXEC_APPROVAL_B64"
APPROVAL_ENVIRONMENT = "trimem-benchmark-exec"
APPROVAL_REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
OPENAI_SECRET_NAME = "OPENAI_API_KEY"
EVIDENCE_SECRET_NAME = "TRIMEM_EVIDENCE_PASSPHRASE"
REQUIRED_SECRET_NAMES = frozenset(
    {APPROVAL_SECRET_NAME, OPENAI_SECRET_NAME, EVIDENCE_SECRET_NAME}
)
PARTIAL_INSTALL_CLEANUP_CONTRACT = (
    "Before protected-run approval, delete every name in REQUIRED_SECRET_NAMES "
    "if the exact three-secret installation does not return PASS."
)
MIN_EVIDENCE_PASSPHRASE_BYTES = 32
MAX_EVIDENCE_PASSPHRASE_BYTES = 256
DEFAULT_GH_LOCK_PATH = ROOT / "configs/trimem_v1/gh_cli_lock.json"
DEFAULT_POLICY_REQUEST_PATH = ROOT / "configs/trimem_v1/benchmark_exec_request.json"
DEFAULT_COST_PLAN_PATH = ROOT / "configs/trimem_v1/cost_plan.json"
DEFAULT_FREEZE_PATH = ROOT / "artifacts/trimem_v1/freeze.json"
SECRET_SUBPROCESS_TIMEOUT_SECONDS = 60
APPROVAL_TOP_LEVEL_FIELDS = {
    "approval",
    "approved_request_sha256",
    "request_id",
    "schema",
}
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class ApprovalSecretProducerError(ValueError):
    """Raised when approval bytes or their transport contract differ."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ApprovalSecretProducerError(message)


def canonical_approval_bytes(document: Mapping[str, Any]) -> bytes:
    """Return the one accepted UTF-8 representation of an approval document."""

    _require(
        isinstance(document, dict) and set(document) == APPROVAL_TOP_LEVEL_FIELDS,
        "external approval top-level field set differs",
    )
    try:
        raw = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ApprovalSecretProducerError(
            "external approval is not canonical JSON data"
        ) from exc
    _require(not raw.startswith(b"\xef\xbb\xbf"), "approval JSON has a UTF-8 BOM")
    _require(b"\x00" not in raw, "approval JSON contains NUL")
    return raw


def load_canonical_approval(path: Path) -> tuple[dict[str, Any], bytes]:
    """Read strict UTF-8 JSON and reject any noncanonical source bytes."""

    source = path.read_bytes()
    _require(not source.startswith(b"\xef\xbb\xbf"), "approval JSON has a UTF-8 BOM")
    _require(b"\x00" not in source, "approval JSON contains NUL")
    try:
        decoded = source.decode("utf-8", errors="strict")
        document = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApprovalSecretProducerError(
            "approval JSON is not strict canonical UTF-8 JSON"
        ) from exc
    _require(isinstance(document, dict), "external approval must be a JSON object")
    canonical = canonical_approval_bytes(document)
    _require(source == canonical, "approval JSON source bytes are not canonical")
    return document, canonical


def validate_encoded_approval(encoded: bytes) -> bytes:
    """Validate strict single-line canonical base64 and return decoded JSON bytes."""

    _require(type(encoded) is bytes and bool(encoded), "approval base64 must be bytes")
    _require(
        not encoded.startswith(b"\xef\xbb\xbf"),
        "approval base64 has a UTF-8 BOM",
    )
    _require(encoded.isascii(), "approval base64 must contain ASCII bytes only")
    for forbidden, label in (
        (b"\r", "CR"),
        (b"\n", "LF"),
        (b" ", "space"),
        (b"\t", "tab"),
    ):
        _require(forbidden not in encoded, f"approval base64 contains {label}")
    _require(len(encoded) % 4 == 0, "approval base64 length is not divisible by four")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ApprovalSecretProducerError("approval base64 is invalid") from exc
    _require(base64.b64encode(raw) == encoded, "approval base64 is not canonical")
    _require(not raw.startswith(b"\xef\xbb\xbf"), "decoded approval JSON has a UTF-8 BOM")
    _require(b"\x00" not in raw, "decoded approval JSON contains NUL")
    return raw


def encode_approval_document(document: Mapping[str, Any]) -> tuple[bytes, bytes]:
    """Return canonical approval JSON bytes and their canonical base64 bytes."""

    raw = canonical_approval_bytes(document)
    encoded = base64.b64encode(raw)
    _require(validate_encoded_approval(encoded) == raw, "approval base64 round trip differs")
    return raw, encoded


def validate_evidence_passphrase(value: bytes) -> bytes:
    """Require a strong, printable, whitespace-free ASCII passphrase."""

    _require(type(value) is bytes, "evidence passphrase must be bytes")
    _require(
        MIN_EVIDENCE_PASSPHRASE_BYTES
        <= len(value)
        <= MAX_EVIDENCE_PASSPHRASE_BYTES,
        "evidence passphrase length is invalid",
    )
    _require(
        not value.startswith(b"\xef\xbb\xbf"),
        "evidence passphrase has a UTF-8 BOM",
    )
    _require(value.isascii(), "evidence passphrase must be ASCII")
    _require(
        all(0x21 <= byte <= 0x7E for byte in value),
        "evidence passphrase contains whitespace or control bytes",
    )
    return value


def validate_environment_secret(name: str, value: bytes) -> bytes:
    """Validate one and only one of the three protected environment secrets."""

    _require(name in REQUIRED_SECRET_NAMES, "environment secret name is not allowed")
    _require(type(value) is bytes, "environment secret value must be bytes")
    if name == APPROVAL_SECRET_NAME:
        validate_encoded_approval(value)
        return value
    if name == OPENAI_SECRET_NAME:
        try:
            return validate_openai_api_key(value)
        except OpenAICredentialValidationError as exc:
            raise ApprovalSecretProducerError(exc.classification) from None
    return validate_evidence_passphrase(value)


def _secret_subprocess_environment() -> dict[str, str]:
    """Retain GitHub auth/config while excluding benchmark and Docker secrets."""

    return {
        key: value
        for key, value in os.environ.items()
        if key not in REQUIRED_SECRET_NAMES
        and not key.upper().startswith("DOCKER_")
    }


def validate_pinned_gh_binary(
    gh_binary: Path, *, gh_lock_path: Path = DEFAULT_GH_LOCK_PATH
) -> dict[str, Any]:
    """Bind the observer binary to the committed cross-platform gh lock."""

    try:
        return verify_observer_gh(load_gh_cli_lock(gh_lock_path), gh_binary)
    except (OSError, GhCliInstallError, ValueError) as exc:
        raise ApprovalSecretProducerError("pinned GitHub CLI validation failed") from None


def _run_gh_control(
    command: list[str], *, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command,
            input=input_bytes,
            capture_output=True,
            check=True,
            shell=False,
            text=False,
            timeout=SECRET_SUBPROCESS_TIMEOUT_SECONDS,
            env=_secret_subprocess_environment(),
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ApprovalSecretProducerError(
            "bytes-only protected environment secret control failed"
        ) from None


def list_environment_secret_names(
    *, gh_binary: Path, repository: str, environment: str
) -> set[str]:
    """Return only live secret names; GitHub never returns secret values."""

    _require(repository == APPROVAL_REPOSITORY, "repository identity differs")
    _require(environment == APPROVAL_ENVIRONMENT, "environment identity differs")

    completed = _run_gh_control(
        [
            str(gh_binary),
            "secret",
            "list",
            "--env",
            environment,
            "--repo",
            repository,
            "--json",
            "name",
        ]
    )
    try:
        value = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApprovalSecretProducerError("GitHub secret-name list is invalid") from None
    _require(isinstance(value, list), "GitHub secret-name list is not an array")
    names: set[str] = set()
    for row in value:
        _require(
            isinstance(row, dict)
            and set(row) == {"name"}
            and isinstance(row["name"], str)
            and bool(row["name"]),
            "GitHub secret-name row differs",
        )
        _require(row["name"] not in names, "GitHub secret-name list has duplicates")
        names.add(row["name"])
    return names


def rollback_environment_secrets(
    names: Sequence[str],
    *,
    gh_binary: Path,
    repository: str,
    environment: str,
) -> None:
    """Attempt all three deletions; the caller then verifies exact zero live."""

    _require(repository == APPROVAL_REPOSITORY, "repository identity differs")
    _require(environment == APPROVAL_ENVIRONMENT, "environment identity differs")
    _require(
        len(set(names)) == len(names) and set(names) == REQUIRED_SECRET_NAMES,
        "secret rollback name set differs",
    )
    for name in reversed(tuple(names)):
        # A timeout from ``secret set`` is ambiguous: the remote mutation may
        # have succeeded even though no local success result was returned.
        # Delete every allowed name and use the subsequent live exact-zero
        # observation as the authoritative rollback result. Individual delete
        # exit codes are therefore not interpreted.
        try:
            subprocess.run(
                [
                    str(gh_binary), "secret", "delete", name,
                    "--env", environment, "--repo", repository,
                ],
                input=None,
                capture_output=True,
                check=False,
                shell=False,
                text=False,
                timeout=SECRET_SUBPROCESS_TIMEOUT_SECONDS,
                env=_secret_subprocess_environment(),
            )
        except (OSError, subprocess.TimeoutExpired):
            continue


def install_environment_secret(
    name: str,
    value: bytes,
    *,
    gh_binary: Path,
    repository: str,
    environment: str = APPROVAL_ENVIRONMENT,
    _pinned_gh_verified: bool = False,
) -> dict[str, object]:
    """Install exact bytes using ``subprocess.run(input=bytes)`` and no shell.

    The captured GitHub CLI streams are intentionally discarded.  A failed
    process is re-raised as a sanitized producer error so neither the secret
    nor arbitrary CLI output can enter logs.
    """

    validated = validate_environment_secret(name, value)
    _require(gh_binary.is_file(), "pinned gh binary is missing")
    if not _pinned_gh_verified:
        validate_pinned_gh_binary(gh_binary)
    _require(REPOSITORY.fullmatch(repository) is not None, "repository identity is invalid")
    _require(repository == APPROVAL_REPOSITORY, "repository identity differs")
    _require(environment == APPROVAL_ENVIRONMENT, "environment identity differs")
    command = [
        str(gh_binary),
        "secret",
        "set",
        name,
        "--env",
        environment,
        "--repo",
        repository,
    ]
    try:
        _run_gh_control(command, input_bytes=validated)
    except ApprovalSecretProducerError:
        raise ApprovalSecretProducerError(
            "bytes-only protected environment secret installation failed"
        ) from None
    return {
        "environment": environment,
        "repository": repository,
        "secret_name": name,
        "status": "PASS",
        "transport": "PYTHON_SUBPROCESS_BINARY_STDIN",
    }


def install_required_environment_secrets(
    secrets: Mapping[str, bytes],
    *,
    gh_binary: Path,
    repository: str,
    environment: str = APPROVAL_ENVIRONMENT,
) -> dict[str, object]:
    """Install the exact three-name secret set through binary stdin only."""

    _require(
        isinstance(secrets, dict) and set(secrets) == REQUIRED_SECRET_NAMES,
        "protected environment secret name set differs",
    )
    validate_pinned_gh_binary(gh_binary)
    _require(
        list_environment_secret_names(
            gh_binary=gh_binary,
            repository=repository,
            environment=environment,
        )
        == set(),
        "protected environment secret set is not empty before installation",
    )
    results: list[dict[str, object]] = []
    try:
        for name in sorted(REQUIRED_SECRET_NAMES):
            results.append(
                install_environment_secret(
                    name,
                    secrets[name],
                    gh_binary=gh_binary,
                    repository=repository,
                    environment=environment,
                    _pinned_gh_verified=True,
                )
            )
        _require(
            list_environment_secret_names(
                gh_binary=gh_binary,
                repository=repository,
                environment=environment,
            )
            == REQUIRED_SECRET_NAMES,
            "protected environment secret set differs after installation",
        )
    except ApprovalSecretProducerError:
        try:
            rollback_environment_secrets(
                sorted(REQUIRED_SECRET_NAMES),
                gh_binary=gh_binary,
                repository=repository,
                environment=environment,
            )
            _require(
                list_environment_secret_names(
                    gh_binary=gh_binary,
                    repository=repository,
                    environment=environment,
                )
                == set(),
                "protected environment secret rollback did not restore empty state",
            )
        except ApprovalSecretProducerError:
            raise ApprovalSecretProducerError(
                "required secret-set installation and exact-prefix rollback failed; "
                "delete the exact three-name allowlist before protected-run approval"
            ) from None
        raise ApprovalSecretProducerError(
            "required secret-set installation failed and its installed prefix "
            "was rolled back to the verified empty state"
        ) from None
    return {
        "failure_cleanup_contract": PARTIAL_INSTALL_CLEANUP_CONTRACT,
        "environment": environment,
        "installed_secret_names": sorted(REQUIRED_SECRET_NAMES),
        "repository": repository,
        "results": results,
        "status": "PASS",
        "transport": "PYTHON_SUBPROCESS_BINARY_STDIN",
    }


def install_approval_secret(
    encoded: bytes,
    *,
    gh_binary: Path,
    repository: str,
    environment: str = APPROVAL_ENVIRONMENT,
) -> dict[str, object]:
    """Compatibility wrapper for a single bytes-only approval installation."""

    evidence = install_environment_secret(
        APPROVAL_SECRET_NAME,
        encoded,
        gh_binary=gh_binary,
        repository=repository,
        environment=environment,
    )
    return {
        **evidence,
        "approval_b64_bytes": len(encoded),
        "approval_b64_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def validate_run_bound_development_approval(
    document: Mapping[str, Any],
    *,
    openai_api_key: bytes,
    request_path: Path,
    policy_request_path: Path,
    cost_plan_path: Path,
    freeze_path: Path,
    git_head: str,
    source_head: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
) -> dict[str, Any]:
    """Run the production approval and key-commitment checks before upload."""

    def load_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
        raw = path.read_bytes()
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApprovalSecretProducerError(f"{label} is not strict JSON") from None
        _require(isinstance(value, dict), f"{label} is not an object")
        return value, raw

    request, request_raw = load_object(request_path, "committed execution request")
    policy, _ = load_object(policy_request_path, "benchmark approval policy")
    cost, _ = load_object(cost_plan_path, "cost plan")
    _, freeze_raw = load_object(freeze_path, "committed freeze")
    hard_cap = cost.get("phase_hard_caps", {}).get("DEVELOPMENT_TUNING")
    _require(isinstance(hard_cap, dict), "development hard cap is missing")
    request_sha256 = hashlib.sha256(request_raw).hexdigest()
    freeze_sha256 = hashlib.sha256(freeze_raw).hexdigest()
    try:
        validated = validate_external_approval_document(
            document,
            request=request,
            policy_request=policy,
            phase="DEVELOPMENT_TUNING",
            hard_cap=hard_cap,
            request_sha256=request_sha256,
            freeze_sha256=freeze_sha256,
            git_head=git_head,
            source_head=source_head,
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
        )
    except ApprovalValidationError as exc:
        raise ApprovalSecretProducerError(
            "run-bound external approval validation failed"
        ) from None
    _require(workflow_run_attempt == "1", "DEV approval requires run attempt one")
    binding = {
        "request_id": str(document["request_id"]),
        "execution_head": git_head,
        "source_head": source_head,
        "workflow_run_id": workflow_run_id,
        "workflow_run_attempt": workflow_run_attempt,
        "model_id": str(request.get("exact_model", {}).get("model_id", "")),
        "approval_nonce": str(validated.get("approval_nonce", "")),
    }
    _require(
        verify_openai_key_commitment(
            openai_api_key,
            binding,
            validated.get("approved_openai_key_commitment"),
        ),
        "approval OpenAI-key commitment differs",
    )
    return validated


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--approval-json", type=Path, required=True)
    parser.add_argument("--approval-b64-output", type=Path, required=True)
    parser.add_argument("--install-required", action="store_true")
    parser.add_argument("--gh-binary", type=Path)
    parser.add_argument("--repository")
    parser.add_argument("--environment", default=APPROVAL_ENVIRONMENT)
    parser.add_argument("--openai-key-file", type=Path)
    parser.add_argument("--evidence-passphrase-file", type=Path)
    parser.add_argument("--request-json", type=Path)
    parser.add_argument("--policy-request", type=Path, default=DEFAULT_POLICY_REQUEST_PATH)
    parser.add_argument("--cost-plan", type=Path, default=DEFAULT_COST_PLAN_PATH)
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE_PATH)
    parser.add_argument("--git-head")
    parser.add_argument("--source-head")
    parser.add_argument("--workflow-run-id")
    parser.add_argument("--workflow-run-attempt")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    document, source = load_canonical_approval(args.approval_json)
    raw, encoded = encode_approval_document(document)
    _require(raw == source, "approval JSON changed during encoding")
    args.approval_b64_output.write_bytes(encoded)
    evidence: dict[str, object] = {
        "approval_b64_bytes": len(encoded),
        "approval_b64_sha256": hashlib.sha256(encoded).hexdigest(),
        "approval_json_bytes": len(raw),
        "approval_json_sha256": hashlib.sha256(raw).hexdigest(),
        "status": "PASS",
    }
    if args.install_required:
        _require(args.gh_binary is not None, "--install-required requires --gh-binary")
        _require(args.repository is not None, "--install-required requires --repository")
        _require(
            args.openai_key_file is not None,
            "--install-required requires --openai-key-file",
        )
        _require(
            args.evidence_passphrase_file is not None,
            "--install-required requires --evidence-passphrase-file",
        )
        _require(args.request_json is not None, "--install-required requires --request-json")
        _require(args.git_head is not None, "--install-required requires --git-head")
        _require(args.source_head is not None, "--install-required requires --source-head")
        _require(
            args.workflow_run_id is not None,
            "--install-required requires --workflow-run-id",
        )
        _require(
            args.workflow_run_attempt is not None,
            "--install-required requires --workflow-run-attempt",
        )
        openai_api_key = args.openai_key_file.read_bytes()
        validate_run_bound_development_approval(
            document,
            openai_api_key=openai_api_key,
            request_path=args.request_json,
            policy_request_path=args.policy_request,
            cost_plan_path=args.cost_plan,
            freeze_path=args.freeze,
            git_head=args.git_head,
            source_head=args.source_head,
            workflow_run_id=args.workflow_run_id,
            workflow_run_attempt=args.workflow_run_attempt,
        )
        evidence["installation"] = install_required_environment_secrets(
            {
                APPROVAL_SECRET_NAME: encoded,
                OPENAI_SECRET_NAME: openai_api_key,
                EVIDENCE_SECRET_NAME: args.evidence_passphrase_file.read_bytes(),
            },
            gh_binary=args.gh_binary,
            repository=args.repository,
            environment=args.environment,
        )
    print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
