from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_grader_smoke_failure_evidence as evidence  # noqa: E402


def _committed_raw() -> tuple[bytes, bytes]:
    receipt = (ROOT / evidence.FAILURE_RECEIPT_PATH).read_bytes()
    inventory = (ROOT / evidence.EVIDENCE_INVENTORY_PATH).read_bytes()
    return receipt, inventory


def _write_pair(root: Path, receipt: bytes, inventory: bytes) -> None:
    receipt_path = root / evidence.FAILURE_RECEIPT_PATH
    inventory_path = root / evidence.EVIDENCE_INVENTORY_PATH
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(receipt)
    inventory_path.write_bytes(inventory)


def test_committed_failure_evidence_is_exact_and_canonical() -> None:
    receipt = evidence.validate_committed_failure_evidence(ROOT)
    receipt_raw, inventory_raw = _committed_raw()

    assert receipt["schema"] == "trimem/grader-smoke-failure-receipt/1.0"
    assert receipt["status"] == "FAIL"
    assert receipt["endpoint"] == (
        "TRIMEM_GRADER_SMOKE_ADAPTER_CONTRACT_NOT_READY"
    )
    assert receipt["development_approval_allowed"] is False
    assert receipt["authoritative_campaign"] == {
        "aggregate_created": False,
        "attestation_created": False,
        "authoritative_result_rows": 0,
        "expected_cells": 12,
        "formal_result_rows": 5,
        "forensic_executed_outcomes": 6,
        "public_result_created": False,
        "scientific_result": "NOT_AGGREGATED",
        "status": "FAILED_BEFORE_FAIL_CLOSED_AGGREGATION",
    }
    assert receipt["execution_accounting"] == evidence.EXECUTION_ACCOUNTING
    assert receipt["diagnostic_progress"]["evidence_counts"] == {
        "formal_result_rows": {
            "digest_match": 5,
            "host_prepare_sh_access_count": 0,
            "patch_applied": 5,
            "source_image_build_count": 0,
            "submitted_patch_identity": 5,
            "tests_executed": 5,
        },
        "forensic_executed_outcomes": {
            "digest_match": 6,
            "host_prepare_sh_access_count": 0,
            "patch_applied": 6,
            "source_image_build_count": 0,
            "submitted_patch_identity": 6,
            "tests_executed": 6,
        },
    }
    assert receipt["failure_analysis"]["primary"]["code"] == (
        "MULTI_SWE_VALID_RESOLVED_CONFLATION"
    )
    assert receipt["failure_analysis"]["secondary"]["code"] == (
        "FAILURE_REPORT_IDENTITY_LOCATION_MASKING"
    )
    assert evidence.canonical_bytes(receipt, pretty=True) == receipt_raw
    assert hashlib.sha256(receipt_raw).hexdigest() == (
        "fe9f98a07be06d7c5ee56110b0bc2058e9271f26ef0086b2232332aa7da42978"
    )
    assert len(inventory_raw) == 50977
    assert hashlib.sha256(inventory_raw).hexdigest() == (
        "c61ffdff2ab8857e8ebd212df9d8190b9424ebafd0c3a092b91de3a311108004"
    )


def test_receipt_contains_no_restricted_payload_or_raw_log_markers() -> None:
    receipt_raw, _inventory_raw = _committed_raw()
    forbidden = (
        b"FAIL_TO_PASS",
        b"PASS_TO_PASS",
        b"applied.patch",
        b"dataset.jsonl",
        b"prediction.jsonl",
        b"config.json",
        b'"stdout"',
        b'"stderr"',
        b'"raw_report"',
        b"passphrase",
    )
    assert all(marker not in receipt_raw for marker in forbidden)


def test_validator_rejects_resealed_provenance_tamper(tmp_path: Path) -> None:
    receipt_raw, inventory_raw = _committed_raw()
    receipt = json.loads(receipt_raw)
    receipt.pop("receipt_payload_sha256")
    receipt["workflow_run"]["head_sha"] = "f" * 40
    tampered = evidence._seal_payload(receipt)
    _write_pair(
        tmp_path,
        evidence.canonical_bytes(tampered, pretty=True),
        inventory_raw,
    )

    with pytest.raises(evidence.FailureEvidenceError, match="exact payload"):
        evidence.validate_committed_failure_evidence(tmp_path)


def test_validator_rejects_inventory_raw_byte_tamper(tmp_path: Path) -> None:
    receipt_raw, inventory_raw = _committed_raw()
    _write_pair(tmp_path, receipt_raw, inventory_raw + b" ")

    with pytest.raises(evidence.FailureEvidenceError, match="byte count"):
        evidence.validate_committed_failure_evidence(tmp_path)


def test_receipt_sealer_rejects_sensitive_key() -> None:
    payload = evidence._expected_payload()
    payload["patch"] = "not permitted"
    with pytest.raises(evidence.FailureEvidenceError, match="forbidden keys"):
        evidence._seal_payload(payload)


def test_writer_refuses_any_existing_output_before_reading_sources(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / evidence.FAILURE_RECEIPT_PATH
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(b"occupied")

    with pytest.raises(evidence.FailureEvidenceError, match="overwrite"):
        evidence.write_failure_evidence(tmp_path / "missing-source", tmp_path)


def test_source_hash_guard_rejects_changed_bytes(tmp_path: Path) -> None:
    path = tmp_path / "source.json"
    path.write_bytes(b"{}\n")
    expected = {
        "source.json": (
            3,
            hashlib.sha256(b"different").hexdigest(),
        )
    }
    with pytest.raises(evidence.FailureEvidenceError, match="SHA-256"):
        evidence._verified_source(
            tmp_path,
            "source.json",
            expected_files=expected,
        )


def test_archive_guard_rejects_non_singleton_zip(tmp_path: Path) -> None:
    path = tmp_path / "two.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("first.json", b"{}")
        archive.writestr("second.json", b"{}")

    with pytest.raises(evidence.FailureEvidenceError, match="exactly one"):
        evidence._single_zip_member(
            path.read_bytes(), expected_name="first.json", label="fixture archive"
        )
