"""Pure external builder for an exact attempt-2 DEV diagnostic approval.

This module does not dispatch a workflow, install a secret, or write a file.
The external operator serializes the returned document with
``canonical_approval_bytes`` and uses ``Path.write_bytes`` for both the JSON
and strict base64 material, preserving the established no-BOM/no-newline
production contract.
"""
from __future__ import annotations

from typing import Any, Mapping

from enterprise_memory.providers.openai_credential import (
    compute_openai_key_commitment,
)
from trimem_dev_activation_gate import (
    APPROVAL_SCHEMA,
    APPROVED_PHASE,
    DiagnosticApprovalError,
    canonical_approval_bytes,
    diagnostic_credential_binding,
    utc_timestamp,
    validate_approval_document,
)


def build_approval_document(
    *,
    diagnostic_id: str,
    repository: str,
    git_head: str,
    workflow_run_id: int,
    matrix_raw_sha256: str,
    policy_raw_sha256: str,
    source_bank_manifest_sha256: str,
    model_id: str,
    hard_caps: Mapping[str, Any],
    approval_actor: str,
    approval_nonce: str,
    approved_at_utc: str,
    expires_at_utc: str,
    openai_api_key: object,
) -> dict[str, Any]:
    """Build and self-validate the only accepted attempt-2 approval shape."""

    binding = diagnostic_credential_binding(
        diagnostic_id=diagnostic_id,
        git_head=git_head,
        source_bank_manifest_sha256=source_bank_manifest_sha256,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=2,
        model_id=model_id,
        approval_nonce=approval_nonce,
    )
    document = {
        "schema": APPROVAL_SCHEMA,
        "approval": {
            "approval_actor": approval_actor,
            "approval_nonce": approval_nonce,
            "approved_at_utc": approved_at_utc,
            "expires_at_utc": expires_at_utc,
            "approved_phase": APPROVED_PHASE,
            "diagnostic_id": diagnostic_id,
            "repository": repository,
            "git_head": git_head,
            "approved_workflow_run_id": workflow_run_id,
            "approved_workflow_run_attempt": 2,
            "approved_model_id": model_id,
            "approved_openai_key_commitment": compute_openai_key_commitment(
                openai_api_key,
                binding,
            ),
            "workflow_event": "push",
            "matrix_raw_sha256": matrix_raw_sha256,
            "policy_raw_sha256": policy_raw_sha256,
            "source_bank_manifest_sha256": source_bank_manifest_sha256,
            "hard_caps": dict(hard_caps),
        },
    }
    issued = utc_timestamp(approved_at_utc, "approved_at_utc")
    validate_approval_document(
        document,
        now=issued,
        diagnostic_id=diagnostic_id,
        repository=repository,
        git_head=git_head,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=2,
        workflow_event="push",
        matrix_raw_sha256=matrix_raw_sha256,
        policy_raw_sha256=policy_raw_sha256,
        source_bank_manifest_sha256=source_bank_manifest_sha256,
        model_id=model_id,
        hard_caps=hard_caps,
    )
    raw = canonical_approval_bytes(document)
    if (
        raw.startswith(b"\xef\xbb\xbf")
        or b"\x00" in raw
        or b"\r" in raw
        or b"\n" in raw
    ):
        raise DiagnosticApprovalError(
            "canonical approval bytes are not single-line UTF-8"
        )
    return document


__all__ = ["build_approval_document", "canonical_approval_bytes"]
