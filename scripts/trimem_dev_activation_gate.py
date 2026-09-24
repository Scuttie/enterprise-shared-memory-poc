"""Fail-closed external approval gate for the DEV activation diagnostic.

The gate is intentionally credential-free with respect to models and graders.
It validates a strict base64 approval, the current Git identity, and the fully
frozen diagnostic/source-bank closure before atomically materializing the exact
approval bytes for the separately invoked production executor.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from trimem_dev_activation_diagnostic import (  # noqa: E402
    DiagnosticContractError,
    MATRIX_PATH,
    POLICY_PATH,
    file_sha256,
    load_and_validate_contract,
)


APPROVAL_SCHEMA = "trimem/dev-activation-exec-approval/1.1"
APPROVED_PHASE = "POST_DEV_ACTIVATION_DIAGNOSTIC"
MAX_APPROVAL_LIFETIME = timedelta(days=7)
FUTURE_CLOCK_SKEW = timedelta(minutes=5)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
APPROVAL_FIELDS = {
    "approval_actor",
    "approval_nonce",
    "approved_at_utc",
    "expires_at_utc",
    "approved_phase",
    "diagnostic_id",
    "repository",
    "git_head",
    "approved_workflow_run_id",
    "approved_workflow_run_attempt",
    "approved_model_id",
    "approved_openai_key_commitment",
    "workflow_event",
    "matrix_raw_sha256",
    "policy_raw_sha256",
    "source_bank_manifest_sha256",
    "hard_caps",
}


class DiagnosticApprovalError(ValueError):
    """The diagnostic approval is malformed, stale, or incorrectly bound."""


def diagnostic_credential_binding(
    *,
    diagnostic_id: str,
    git_head: str,
    source_bank_manifest_sha256: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    model_id: str,
    approval_nonce: str,
) -> dict[str, str]:
    """Return the exact existing-provider HMAC field shape for this run."""

    values: dict[str, object] = {
        "request_id": diagnostic_id,
        "execution_head": git_head,
        "source_head": source_bank_manifest_sha256,
        "workflow_run_id": str(workflow_run_id),
        "workflow_run_attempt": str(workflow_run_attempt),
        "model_id": model_id,
        "approval_nonce": approval_nonce,
    }
    if not all(isinstance(value, str) and value for value in values.values()):
        raise DiagnosticApprovalError("diagnostic credential binding is incomplete")
    return values  # type: ignore[return-value]


def canonical_approval_bytes(document: Mapping[str, Any]) -> bytes:
    """Serialize an approval without a BOM, newline, NaN, or key-order drift."""

    return json.dumps(
        dict(document),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise DiagnosticApprovalError(f"duplicate approval JSON key: {key}")
        value[key] = child
    return value


def _reject_constant(value: str) -> None:
    raise DiagnosticApprovalError(f"non-finite approval JSON number: {value}")


def decode_approval_base64(encoded_value: str) -> tuple[dict[str, Any], bytes]:
    if not isinstance(encoded_value, str) or not encoded_value:
        raise DiagnosticApprovalError("fresh external approval secret is missing")
    try:
        encoded = encoded_value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise DiagnosticApprovalError("approval base64 is not ASCII") from exc
    if any(byte in b" \t\r\n" for byte in encoded):
        raise DiagnosticApprovalError("approval base64 contains whitespace")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DiagnosticApprovalError("approval base64 is malformed") from exc
    if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
        raise DiagnosticApprovalError("approval JSON contains a BOM or NUL byte")
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DiagnosticApprovalError("approval is not strict UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise DiagnosticApprovalError("approval JSON root must be an object")
    if raw != canonical_approval_bytes(document):
        raise DiagnosticApprovalError("approval JSON bytes are not canonical")
    return document, raw


def utc_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DiagnosticApprovalError(f"{field} must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise DiagnosticApprovalError(f"{field} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise DiagnosticApprovalError(f"{field} is not UTC")
    return parsed


def validate_approval_document(
    document: Mapping[str, Any],
    *,
    now: datetime,
    diagnostic_id: str,
    repository: str,
    git_head: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    workflow_event: str,
    matrix_raw_sha256: str,
    policy_raw_sha256: str,
    source_bank_manifest_sha256: str,
    model_id: str,
    hard_caps: Mapping[str, Any],
) -> dict[str, Any]:
    if set(document) != {"schema", "approval"} or document.get("schema") != APPROVAL_SCHEMA:
        raise DiagnosticApprovalError("diagnostic approval schema/root field drift")
    approval = document.get("approval")
    if not isinstance(approval, dict) or set(approval) != APPROVAL_FIELDS:
        raise DiagnosticApprovalError("diagnostic approval field-set drift")
    exact = {
        "approved_phase": APPROVED_PHASE,
        "diagnostic_id": diagnostic_id,
        "repository": repository,
        "git_head": git_head,
        "approved_workflow_run_id": workflow_run_id,
        "approved_workflow_run_attempt": workflow_run_attempt,
        "approved_model_id": model_id,
        "workflow_event": workflow_event,
        "matrix_raw_sha256": matrix_raw_sha256,
        "policy_raw_sha256": policy_raw_sha256,
        "source_bank_manifest_sha256": source_bank_manifest_sha256,
    }
    for field, expected in exact.items():
        if approval.get(field) != expected:
            raise DiagnosticApprovalError(f"approval binding mismatch: {field}")
    if workflow_event != "push":
        raise DiagnosticApprovalError("diagnostic execution approval requires the exact feature-branch push run")
    if not HEX40.fullmatch(git_head):
        raise DiagnosticApprovalError("approval Git head is not an exact commit")
    if type(workflow_run_id) is not int or workflow_run_id <= 0:
        raise DiagnosticApprovalError("workflow run ID is invalid")
    if type(workflow_run_attempt) is not int or workflow_run_attempt != 2:
        raise DiagnosticApprovalError(
            "workflow run attempt must be exactly 2 after the attempt-1 handshake"
        )
    if approval.get("hard_caps") != dict(hard_caps):
        raise DiagnosticApprovalError("approval hard caps differ from frozen policy")
    actor = approval.get("approval_actor")
    nonce = approval.get("approval_nonce")
    if not isinstance(actor, str) or not actor.strip():
        raise DiagnosticApprovalError("approval actor is missing")
    if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32,128}", nonce):
        raise DiagnosticApprovalError("approval nonce is not 128-bit-or-greater lowercase hex")
    diagnostic_credential_binding(
        diagnostic_id=diagnostic_id,
        git_head=git_head,
        source_bank_manifest_sha256=source_bank_manifest_sha256,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        model_id=model_id,
        approval_nonce=nonce,
    )
    if not SHA256.fullmatch(
        str(approval.get("approved_openai_key_commitment"))
    ):
        raise DiagnosticApprovalError(
            "approved OpenAI key commitment is malformed"
        )
    for field in (
        "matrix_raw_sha256",
        "policy_raw_sha256",
        "source_bank_manifest_sha256",
    ):
        if not SHA256.fullmatch(str(approval.get(field))):
            raise DiagnosticApprovalError(f"approval {field} is malformed")

    if now.tzinfo is None:
        raise DiagnosticApprovalError("approval validation clock must be timezone-aware")
    observed_now = now.astimezone(timezone.utc)
    issued = utc_timestamp(approval.get("approved_at_utc"), "approved_at_utc")
    expires = utc_timestamp(approval.get("expires_at_utc"), "expires_at_utc")
    if issued > observed_now + FUTURE_CLOCK_SKEW:
        raise DiagnosticApprovalError("approval issuance time is in the future")
    if expires <= issued or expires - issued > MAX_APPROVAL_LIFETIME:
        raise DiagnosticApprovalError("approval lifetime exceeds the seven-day contract")
    if observed_now < issued - FUTURE_CLOCK_SKEW or observed_now >= expires:
        raise DiagnosticApprovalError("fresh external approval is not currently valid")
    return dict(approval)


def _git_head(root: Path) -> str:
    result = subprocess.run(
        _hermetic_git_command(["rev-parse", "HEAD"]),
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=_hermetic_git_environment(),
    )
    value = result.stdout.strip()
    if result.returncode != 0 or not HEX40.fullmatch(value):
        raise DiagnosticApprovalError("cannot resolve exact current Git head")
    return value


def _hermetic_git_environment() -> dict[str, str]:
    """Return the minimum non-secret environment needed by local Git reads."""

    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP"}
    environment = {
        key: value for key, value in os.environ.items() if key.upper() in allowed
    }
    environment.update(
        {
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
            "LANG": "C",
        }
    )
    return environment


def _hermetic_git_command(arguments: Sequence[str]) -> list[str]:
    return [
        "git",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        *arguments,
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval-env", default="TRIMEM_DEV_ACTIVATION_APPROVAL_B64")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow-run-id", type=int, required=True)
    parser.add_argument("--workflow-run-attempt", type=int, required=True)
    parser.add_argument("--workflow-event", required=True)
    parser.add_argument("--output-approval", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        document, raw = decode_approval_base64(os.environ.get(args.approval_env, ""))
        manifest, policy, cells, source_bank_sha256 = load_and_validate_contract(
            ROOT,
            require_source_bank=True,
            require_tracked=True,
        )
        if source_bank_sha256 is None:
            raise DiagnosticApprovalError("source bank did not produce a frozen hash")
        approval = validate_approval_document(
            document,
            now=datetime.now(timezone.utc),
            diagnostic_id=manifest["diagnostic_id"],
            repository=args.repository,
            git_head=_git_head(ROOT),
            workflow_run_id=args.workflow_run_id,
            workflow_run_attempt=args.workflow_run_attempt,
            workflow_event=args.workflow_event,
            matrix_raw_sha256=file_sha256(ROOT / MATRIX_PATH),
            policy_raw_sha256=file_sha256(ROOT / POLICY_PATH),
            source_bank_manifest_sha256=source_bank_sha256,
            model_id=policy["frozen_inputs"]["model_lock"]["model_id"],
            hard_caps=policy["hard_caps"],
        )
        args.output_approval.parent.mkdir(parents=True, exist_ok=True)
        with args.output_approval.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(args.output_approval, 0o600)
        except OSError:
            pass
        print(json.dumps({
            "status": "APPROVAL_GATE_PASS_READY_FOR_BOUND_EXECUTOR",
            "approved_phase": approval["approved_phase"],
            "approval_artifact_sha256": hashlib.sha256(raw).hexdigest(),
            "cell_count": len(cells),
            "model_calls": 0,
            "official_grader_runs": 0,
            "paid_model_calls": 0,
            "total_usd": "0.000000000000",
        }, sort_keys=True))
        return 0
    except (DiagnosticApprovalError, DiagnosticContractError, OSError, ValueError) as exc:
        print(json.dumps({
            "status": "FAIL_CLOSED_NO_EXECUTION",
            "reason": str(exc),
            "model_calls": 0,
            "official_grader_runs": 0,
            "paid_model_calls": 0,
            "total_usd": "0.000000000000",
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
