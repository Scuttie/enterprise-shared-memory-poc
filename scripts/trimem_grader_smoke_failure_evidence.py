"""Build and validate the sanitized receipt for the failed P0.1.4 smoke.

This module is deliberately specific to the one authorized workflow attempt.
It verifies the saved GitHub API documents, both downloaded artifact archives,
the exact non-sensitive inventory member, and a locally decrypted audit tar.
Only an allowlisted receipt and the original inventory bytes may be written to
the repository.  Restricted bytes are read for hashing/validation only and are
never copied or rendered by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
from typing import Any, BinaryIO, Mapping
import zipfile


FAILURE_RECEIPT_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/failure-receipt.json"
)
EVIDENCE_INVENTORY_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/evidence-inventory.json"
)

SCHEMA = "trimem/grader-smoke-failure-receipt/1.0"
INVENTORY_SCHEMA = "trimem/restricted-evidence-inventory/1.0"
ENDPOINT = "TRIMEM_GRADER_SMOKE_ADAPTER_CONTRACT_NOT_READY"
EXPECTED_REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
EXPECTED_BRANCH = "codex/trimem-coder-v1"
EXPECTED_HEAD = "0e9ed55196da922dcebf1fb33b73940873007180"
EXPECTED_RUN_ID = 33630256522
EXPECTED_RUN_ATTEMPT = 1
EXPECTED_WORKFLOW = ".github/workflows/trimem-grader-smoke.yml"
EXPECTED_WORKFLOW_ID = 347182465
EXPECTED_PREFLIGHT_JOB_ID = 100247658511
EXPECTED_EXECUTION_JOB_ID = 100247757174
EXPECTED_INVENTORY_ARTIFACT_ID = 9847127657
EXPECTED_RESTRICTED_ARTIFACT_ID = 9847128643

INVENTORY_MEMBER_NAME = "trimem-grader-smoke-evidence-inventory.json"
RESTRICTED_MEMBER_NAME = "trimem-grader-smoke-restricted.tar.enc"
RESTRICTED_TAR_NAME = "trimem-grader-smoke-restricted.tar"

HEX64 = re.compile(r"^[0-9a-f]{64}$")
RECEIPT_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")

SOURCE_FILES: dict[str, tuple[int, str]] = {
    "artifacts.json": (
        1530,
        "5c2378e89376151979fc70cd613b32378a0c4937f8634da2a54aca535bb0c2e4",
    ),
    "inventory-artifact.json": (
        746,
        "0b660e36f04a24112645fa531025d8be2e4adb28d1ae515d85ae6519bc6e79bb",
    ),
    "inventory-artifact.zip": (
        9231,
        "0b9379644d3a1e6dc15156bbb6e2e8a54ea7ec9fa94128c01bb50949e128aa75",
    ),
    "jobs.json": (
        7468,
        "3fee715f9a6e4be315d86ac8d54f3c190d83e81cbe7d238327955e49ae222cd8",
    ),
    "restricted-artifact.json": (
        751,
        "c7840624459765d1baa6e132c7e5c3d2722dcb226edb22d814f998caf2e0f2a3",
    ),
    "restricted-artifact.zip": (
        8819557,
        "c37878ac3076cb7abf2a5b746476e7f0664922e927a72f92b4ba30e72814219a",
    ),
    "run-attempt.json": (
        14529,
        "05b19bdd4a9555f9a844cd357a485a225ba481e239d00ed6bc375d3974f88b4b",
    ),
    RESTRICTED_MEMBER_NAME: (
        8816672,
        "6bcf9b094edb93246d915ac99a283474dc64e6e8288e4d2abaf5ab5d32ea501e",
    ),
    RESTRICTED_TAR_NAME: (
        8816640,
        "e6e9fc79a95ea88e7f66afa9eaa49a93b10e99aed17306c547f6ca64cff302d9",
    ),
}

EXPECTED_INVENTORY_RAW_SHA256 = (
    "c61ffdff2ab8857e8ebd212df9d8190b9424ebafd0c3a092b91de3a311108004"
)
EXPECTED_INVENTORY_BYTES = 50977
EXPECTED_INVENTORY_SHA256 = (
    "493bf56cd4919cb3924cc4e9e5ca21d7571818de0b36ec6682676df55be5dd76"
)
EXPECTED_INVENTORY_FILE_COUNT = 234
EXPECTED_INVENTORY_TOTAL_BYTES = 8416230

APPROVAL_BINDING: dict[str, str] = {
    "approval_artifact_sha256": (
        "26d65d462b09d2db6988bbe6842244278f49c58b559750a4b6455ceb1559c392"
    ),
    "approved_request_sha256": (
        "1cd2d983f9f140392c6c989a9a395c48d5ddc2176cb009b30a98a167c95218ef"
    ),
    "approved_workflow_run_attempt": "1",
    "approved_workflow_run_id": "33630256522",
    "freeze_sha256": (
        "583b8cf815ef78a1c29eb1f4c6cf25c01b0014cb511bd440e131e982e341eca1"
    ),
    "git_head": EXPECTED_HEAD,
    "phase": "GRADER_SMOKE",
}

EXPECTED_DIAGNOSTIC_ROWS: list[dict[str, Any]] = [
    {
        "benchmark_id": "swebench_verified",
        "container_started": True,
        "execution_status": "SUCCESS",
        "official_grader": True,
        "order_index": 0,
        "probe": "GOLD",
        "resolved": True,
        "target_id": "swebench_verified--astropy__astropy-13579--gold",
    },
    {
        "benchmark_id": "swebench_verified",
        "container_started": True,
        "execution_status": "SUCCESS",
        "official_grader": True,
        "order_index": 1,
        "probe": "NOOP_BASELINE",
        "resolved": False,
        "target_id": "swebench_verified--astropy__astropy-13579--noop-baseline",
    },
    {
        "benchmark_id": "swebench_verified",
        "container_started": True,
        "execution_status": "SUCCESS",
        "official_grader": True,
        "order_index": 2,
        "probe": "GOLD",
        "resolved": True,
        "target_id": "swebench_verified--pydata__xarray-6721--gold",
    },
    {
        "benchmark_id": "swebench_verified",
        "container_started": True,
        "execution_status": "SUCCESS",
        "official_grader": True,
        "order_index": 3,
        "probe": "NOOP_BASELINE",
        "resolved": False,
        "target_id": "swebench_verified--pydata__xarray-6721--noop-baseline",
    },
    {
        "benchmark_id": "multi_swe_bench_mini",
        "container_started": True,
        "execution_status": "SUCCESS",
        "official_grader": True,
        "order_index": 4,
        "probe": "GOLD",
        "resolved": True,
        "target_id": "multi_swe_bench_mini--vuejs__core-8911--gold",
    },
]

PARTIAL_TARGET_ID = "multi_swe_bench_mini--vuejs__core-8911--noop-baseline"
PARTIAL_ROOT = f"results/005-{PARTIAL_TARGET_ID}"
PARTIAL_FINAL_REPORT = (
    f"{PARTIAL_ROOT}/official-grader/{PARTIAL_TARGET_ID}/output/final_report.json"
)
PARTIAL_STATUS_REPORT = (
    f"{PARTIAL_ROOT}/official-grader/{PARTIAL_TARGET_ID}/work/"
    "vuejs/core/evals/pr-8911/report.json"
)
PARTIAL_CONTAINER_EXIT = (
    f"{PARTIAL_ROOT}/official-grader/{PARTIAL_TARGET_ID}/container-exit-status.json"
)

EVIDENCE_COUNTS: dict[str, dict[str, int]] = {
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

EXECUTION_ACCOUNTING: dict[str, int] = {
    "api_calls": 0,
    "cached_input_tokens": 0,
    "decomposition_calls": 0,
    "docker_pulls": 4,
    "extraction_calls": 0,
    "grader_calls": 6,
    "grader_containers": 6,
    "input_tokens": 0,
    "model_calls": 0,
    "model_gateway_calls": 0,
    "official_grader_runs": 6,
    "output_tokens": 0,
    "paid_model_calls": 0,
    "reasoning_tokens": 0,
    "solve_calls": 0,
    "task_arm_runs": 0,
    "total_usd": 0,
}

FORBIDDEN_RECEIPT_KEYS = {
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "dataset",
    "dataset_rows",
    "fix_patch",
    "gold_patch",
    "patch",
    "passphrase",
    "prediction",
    "private_inputs",
    "raw_log",
    "raw_logs",
    "raw_report",
    "secret",
    "stderr",
    "stdout",
    "test_names",
    "test_patch",
}
FORBIDDEN_RECEIPT_TEXT = (
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "applied.patch",
    "dataset.jsonl",
    "prediction.jsonl",
    "config.json",
    "trimem-evidence-passphrase",
)


class FailureEvidenceError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FailureEvidenceError(message)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_bytes(value: Any, *, pretty: bool) -> bytes:
    if pretty:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def strict_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise FailureEvidenceError(f"duplicate JSON key in {label}: {key}")
            value[key] = child
        return value

    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FailureEvidenceError(f"invalid UTF-8 JSON: {label}") from exc
    _require(isinstance(value, dict), f"JSON root is not an object: {label}")
    return value


def _verified_source(
    source_dir: Path,
    name: str,
    *,
    expected_files: Mapping[str, tuple[int, str]] = SOURCE_FILES,
) -> bytes:
    _require(name in expected_files, f"unexpected source file: {name}")
    path = source_dir / name
    _require(path.is_file() and not path.is_symlink(), f"missing regular source file: {name}")
    raw = path.read_bytes()
    expected_bytes, expected_sha = expected_files[name]
    _require(len(raw) == expected_bytes, f"source byte count differs: {name}")
    _require(_sha256(raw) == expected_sha, f"source SHA-256 differs: {name}")
    return raw


def _safe_member_name(name: str, *, label: str) -> str:
    normalized = name[2:] if name.startswith("./") else name
    path = PurePosixPath(normalized)
    _require(
        bool(normalized)
        and not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in normalized,
        f"unsafe {label} member path",
    )
    return path.as_posix()


def _single_zip_member(raw: bytes, *, expected_name: str, label: str) -> bytes:
    from io import BytesIO

    try:
        with zipfile.ZipFile(BytesIO(raw), "r") as archive:
            members = archive.infolist()
            _require(len(members) == 1, f"{label} must contain exactly one member")
            member = members[0]
            normalized = _safe_member_name(member.filename, label=label)
            _require(normalized == expected_name, f"{label} member name differs")
            _require(not member.is_dir(), f"{label} member is not a regular file")
            mode = member.external_attr >> 16
            _require(not stat.S_ISLNK(mode), f"{label} member is a symlink")
            _require(member.flag_bits & 0x1 == 0, f"{label} member is ZIP-encrypted")
            return archive.read(member)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise FailureEvidenceError(f"invalid {label}") from exc


def _validate_inventory(raw: bytes) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    _require(len(raw) == EXPECTED_INVENTORY_BYTES, "inventory byte count differs")
    _require(_sha256(raw) == EXPECTED_INVENTORY_RAW_SHA256, "inventory raw SHA-256 differs")
    value = strict_object(raw, label="evidence inventory")
    _require(canonical_bytes(value, pretty=False) + b"\n" == raw, "inventory bytes are not canonical")
    _require(
        set(value)
        == {
            "files",
            "inventory_sha256",
            "root",
            "schema",
            "total_bytes",
            "total_files",
        },
        "inventory field set differs",
    )
    rows = value.get("files")
    _require(isinstance(rows, list), "inventory files are not a list")
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        _require(
            isinstance(row, dict) and set(row) == {"bytes", "path", "sha256"},
            "inventory row field set differs",
        )
        path = row.get("path")
        digest = row.get("sha256")
        size = row.get("bytes")
        _require(isinstance(path, str), "inventory path is invalid")
        _require(_safe_member_name(path, label="inventory") == path, "inventory path differs")
        _require(path not in indexed, "inventory path is duplicated")
        _require(isinstance(digest, str) and HEX64.fullmatch(digest) is not None, "inventory hash is invalid")
        _require(type(size) is int and size >= 0, "inventory byte count is invalid")
        indexed[path] = row
    payload = {
        "files": rows,
        "root": value.get("root"),
        "schema": value.get("schema"),
        "total_bytes": sum(row["bytes"] for row in rows),
        "total_files": len(rows),
    }
    _require(
        value.get("schema") == INVENTORY_SCHEMA
        and value.get("root") == "grader_smoke_exec"
        and value.get("total_files") == EXPECTED_INVENTORY_FILE_COUNT
        and value.get("total_bytes") == EXPECTED_INVENTORY_TOTAL_BYTES
        and value.get("inventory_sha256") == EXPECTED_INVENTORY_SHA256
        and _sha256(canonical_bytes(payload, pretty=False)) == EXPECTED_INVENTORY_SHA256,
        "inventory seal or totals differ",
    )
    return value, indexed


def _hash_stream(stream: BinaryIO) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def _audit_tar(
    path: Path,
    *,
    inventory_raw: bytes,
    inventory_rows: Mapping[str, Mapping[str, Any]],
) -> dict[str, bytes]:
    selected_names = {
        "results/external-approval-evidence.json",
        "image-materialization/image-lifecycle-report.json",
        "workflow-image-cleanup/workflow-image-cleanup-report.json",
        f"{PARTIAL_ROOT}/report.json",
        PARTIAL_CONTAINER_EXIT,
        PARTIAL_FINAL_REPORT,
        PARTIAL_STATUS_REPORT,
        *(
            f"results/{row['order_index']:03d}-{row['target_id']}/{row['target_id']}.result.json"
            for row in EXPECTED_DIAGNOSTIC_ROWS
        ),
    }
    selected: dict[str, bytes] = {}
    observed: set[str] = set()
    inventory_member_seen = False
    try:
        with tarfile.open(path, "r:") as archive:
            for member in archive.getmembers():
                normalized = _safe_member_name(member.name, label="restricted tar")
                if member.isdir():
                    continue
                _require(member.isfile(), "restricted tar contains a non-regular member")
                _require(normalized not in observed, "restricted tar member is duplicated")
                observed.add(normalized)
                stream = archive.extractfile(member)
                _require(stream is not None, "restricted tar member cannot be read")
                if normalized == INVENTORY_MEMBER_NAME:
                    raw = stream.read()
                    _require(raw == inventory_raw, "restricted tar inventory member differs")
                    inventory_member_seen = True
                    continue
                row = inventory_rows.get(normalized)
                _require(isinstance(row, Mapping), "restricted tar contains an uninventoried file")
                if normalized in selected_names:
                    raw = stream.read()
                    _require(len(raw) == row["bytes"] and _sha256(raw) == row["sha256"], "selected restricted member differs from inventory")
                    selected[normalized] = raw
                else:
                    size, digest = _hash_stream(stream)
                    _require(size == row["bytes"] and digest == row["sha256"], "restricted member differs from inventory")
    except (tarfile.TarError, OSError) as exc:
        raise FailureEvidenceError("invalid restricted audit tar") from exc
    _require(inventory_member_seen, "restricted tar lacks its inventory member")
    _require(observed - {INVENTORY_MEMBER_NAME} == set(inventory_rows), "restricted tar/inventory exact file set differs")
    _require(set(selected) == selected_names, "restricted tar lacks required sanitized audit inputs")
    return selected


def _artifact_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "api_url": value.get("url"),
        "archive_download_url": value.get("archive_download_url"),
        "created_at": value.get("created_at"),
        "digest": value.get("digest"),
        "expired": value.get("expired"),
        "expires_at": value.get("expires_at"),
        "id": value.get("id"),
        "name": value.get("name"),
        "size_in_bytes": value.get("size_in_bytes"),
    }


def _validate_artifact(
    value: Mapping[str, Any],
    *,
    artifact_id: int,
    name: str,
    digest: str,
    size: int,
) -> dict[str, Any]:
    projection = _artifact_projection(value)
    _require(
        projection
        == {
            "api_url": f"https://api.github.com/repos/{EXPECTED_REPOSITORY}/actions/artifacts/{artifact_id}",
            "archive_download_url": f"https://api.github.com/repos/{EXPECTED_REPOSITORY}/actions/artifacts/{artifact_id}/zip",
            "created_at": (
                "2026-09-02T12:47:19Z"
                if artifact_id == EXPECTED_INVENTORY_ARTIFACT_ID
                else "2026-09-02T12:47:21Z"
            ),
            "digest": "sha256:" + digest,
            "expired": False,
            "expires_at": (
                "2026-10-02T12:47:19Z"
                if artifact_id == EXPECTED_INVENTORY_ARTIFACT_ID
                else "2026-09-16T12:47:19Z"
            ),
            "id": artifact_id,
            "name": name,
            "size_in_bytes": size,
        },
        f"artifact projection differs: {name}",
    )
    workflow_run = value.get("workflow_run")
    _require(
        isinstance(workflow_run, Mapping)
        and workflow_run.get("id") == EXPECTED_RUN_ID
        and workflow_run.get("head_branch") == EXPECTED_BRANCH
        and workflow_run.get("head_sha") == EXPECTED_HEAD,
        f"artifact workflow binding differs: {name}",
    )
    return projection


def _source_document(name: str, *, url: str) -> dict[str, Any]:
    size, digest = SOURCE_FILES[name]
    return {"bytes": size, "raw_sha256": "sha256:" + digest, "url": url}


def _expected_payload() -> dict[str, Any]:
    api_root = f"https://api.github.com/repos/{EXPECTED_REPOSITORY}"
    inventory_zip_sha = SOURCE_FILES["inventory-artifact.zip"][1]
    restricted_zip_sha = SOURCE_FILES["restricted-artifact.zip"][1]
    encrypted_size, encrypted_sha = SOURCE_FILES[RESTRICTED_MEMBER_NAME]
    tar_size, tar_sha = SOURCE_FILES[RESTRICTED_TAR_NAME]
    return {
        "approval_binding": APPROVAL_BINDING,
        "artifacts": {
            "encrypted_restricted_evidence": {
                "archive_bytes": SOURCE_FILES["restricted-artifact.zip"][0],
                "archive_raw_sha256": "sha256:" + restricted_zip_sha,
                "artifact_id": EXPECTED_RESTRICTED_ARTIFACT_ID,
                "artifact_name": "trimem-grader-smoke-restricted-encrypted",
                "created_at": "2026-09-02T12:47:21Z",
                "encrypted_member_bytes": encrypted_size,
                "encrypted_member_name": RESTRICTED_MEMBER_NAME,
                "encrypted_member_raw_sha256": "sha256:" + encrypted_sha,
                "expires_at": "2026-09-16T12:47:19Z",
                "expired_when_observed": False,
                "plaintext_or_secret_committed": False,
            },
            "evidence_inventory": {
                "archive_bytes": SOURCE_FILES["inventory-artifact.zip"][0],
                "archive_raw_sha256": "sha256:" + inventory_zip_sha,
                "artifact_id": EXPECTED_INVENTORY_ARTIFACT_ID,
                "artifact_name": "trimem-grader-smoke-evidence-inventory",
                "created_at": "2026-09-02T12:47:19Z",
                "expires_at": "2026-10-02T12:47:19Z",
                "expired_when_observed": False,
                "inventory_sha256": "sha256:" + EXPECTED_INVENTORY_SHA256,
                "member_bytes": EXPECTED_INVENTORY_BYTES,
                "member_name": INVENTORY_MEMBER_NAME,
                "member_raw_sha256": "sha256:" + EXPECTED_INVENTORY_RAW_SHA256,
                "restricted_file_count": EXPECTED_INVENTORY_FILE_COUNT,
                "restricted_total_bytes": EXPECTED_INVENTORY_TOTAL_BYTES,
            },
        },
        "authoritative_campaign": {
            "aggregate_created": False,
            "attestation_created": False,
            "authoritative_result_rows": 0,
            "expected_cells": 12,
            "formal_result_rows": 5,
            "forensic_executed_outcomes": 6,
            "public_result_created": False,
            "scientific_result": "NOT_AGGREGATED",
            "status": "FAILED_BEFORE_FAIL_CLOSED_AGGREGATION",
        },
        "development_approval_allowed": False,
        "diagnostic_progress": {
            "completed_rows": EXPECTED_DIAGNOSTIC_ROWS,
            "evidence_counts": EVIDENCE_COUNTS,
            "partial_outcome": {
                "formal_result_written": False,
                "official_final_report_resolved": False,
                "official_per_instance_valid": True,
                "order_index": 5,
                "probe": "NOOP_BASELINE",
                "target_id": PARTIAL_TARGET_ID,
            },
        },
        "endpoint": ENDPOINT,
        "execution_accounting": EXECUTION_ACCOUNTING,
        "failure_analysis": {
            "classification": "ADAPTER_EVIDENCE_CONTRACT_FAILURE",
            "primary": {
                "code": "MULTI_SWE_VALID_RESOLVED_CONFLATION",
                "failure_stage": "official_test_evidence",
                "interpretation": (
                    "upstream valid denotes evaluation validity and is not the "
                    "final resolved outcome"
                ),
                "official_final_report_resolved": False,
                "official_per_instance_valid": True,
                "original_error": (
                    "Multi-SWE official per-instance status identity/result mismatch"
                ),
            },
            "secondary": {
                "code": "FAILURE_REPORT_IDENTITY_LOCATION_MASKING",
                "consumer_lookup_location": "_trimem",
                "failure_identity_location": "TOP_LEVEL_FAILURE_REPORT",
                "masked_primary_error": True,
                "surfaced_error": "official grader private-input identity set differs",
            },
        },
        "image_lifecycle": {
            "exact_image_removals": 4,
            "max_resident_support_images": 1,
            "max_resident_target_images": 1,
            "resident_support_images": 0,
            "resident_target_images": 0,
            "status": "FAILED",
            "support_image_pulls": 1,
            "target_image_pulls": 3,
            "workflow_cleanup_status": "PASS",
        },
        "repository": EXPECTED_REPOSITORY,
        "restricted_evidence_audit": {
            "contents_published": False,
            "inventory_exact_file_set_verified": True,
            "local_audit_tar_bytes": tar_size,
            "local_audit_tar_raw_sha256": "sha256:" + tar_sha,
            "local_audit_tar_retained_in_repository": False,
        },
        "schema": SCHEMA,
        "source_documents": {
            "artifacts_api": _source_document(
                "artifacts.json",
                url=f"{api_root}/actions/runs/{EXPECTED_RUN_ID}/artifacts?per_page=100",
            ),
            "inventory_artifact_api": _source_document(
                "inventory-artifact.json",
                url=f"{api_root}/actions/artifacts/{EXPECTED_INVENTORY_ARTIFACT_ID}",
            ),
            "inventory_artifact_archive": _source_document(
                "inventory-artifact.zip",
                url=f"{api_root}/actions/artifacts/{EXPECTED_INVENTORY_ARTIFACT_ID}/zip",
            ),
            "jobs_api": _source_document(
                "jobs.json",
                url=(
                    f"{api_root}/actions/runs/{EXPECTED_RUN_ID}/attempts/"
                    f"{EXPECTED_RUN_ATTEMPT}/jobs?filter=all&per_page=100"
                ),
            ),
            "restricted_artifact_api": _source_document(
                "restricted-artifact.json",
                url=f"{api_root}/actions/artifacts/{EXPECTED_RESTRICTED_ARTIFACT_ID}",
            ),
            "restricted_artifact_archive": _source_document(
                "restricted-artifact.zip",
                url=f"{api_root}/actions/artifacts/{EXPECTED_RESTRICTED_ARTIFACT_ID}/zip",
            ),
            "workflow_run_attempt_api": _source_document(
                "run-attempt.json",
                url=(
                    f"{api_root}/actions/runs/{EXPECTED_RUN_ID}/attempts/"
                    f"{EXPECTED_RUN_ATTEMPT}"
                ),
            ),
        },
        "status": "FAIL",
        "workflow_job": {
            "completed_at": "2026-09-02T12:47:23Z",
            "conclusion": "failure",
            "failed_step": "Run bounded-disk exact GOLD and NOOP_BASELINE pairs serially",
            "id": EXPECTED_EXECUTION_JOB_ID,
            "name": "frozen-gold-noop-smoke",
            "post_failure_evidence_inventory": "success",
            "post_failure_evidence_upload": "success",
            "post_failure_encryption": "success",
            "post_failure_plaintext_cleanup": "success",
            "preflight_job_id": EXPECTED_PREFLIGHT_JOB_ID,
            "preflight_result": "success",
            "started_at": "2026-09-02T12:34:37Z",
            "status": "completed",
        },
        "workflow_run": {
            "actor": "Scuttie",
            "conclusion": "failure",
            "event": "push",
            "head_branch": EXPECTED_BRANCH,
            "head_sha": EXPECTED_HEAD,
            "html_url": f"https://github.com/{EXPECTED_REPOSITORY}/actions/runs/{EXPECTED_RUN_ID}",
            "id": EXPECTED_RUN_ID,
            "name": "TriMem V1 official grader smoke",
            "path": EXPECTED_WORKFLOW,
            "run_attempt": EXPECTED_RUN_ATTEMPT,
            "run_started_at": "2026-09-02T12:30:03Z",
            "status": "completed",
            "triggering_actor": "Scuttie",
            "updated_at": "2026-09-02T12:47:24Z",
            "workflow_id": EXPECTED_WORKFLOW_ID,
        },
    }


def _reject_sensitive_receipt(value: Any) -> None:
    if isinstance(value, Mapping):
        overlap = FORBIDDEN_RECEIPT_KEYS & set(value)
        _require(not overlap, f"failure receipt contains forbidden keys: {sorted(overlap)}")
        for child in value.values():
            _reject_sensitive_receipt(child)
    elif isinstance(value, list):
        for child in value:
            _reject_sensitive_receipt(child)
    elif isinstance(value, str):
        _require(
            not any(marker in value for marker in FORBIDDEN_RECEIPT_TEXT),
            "failure receipt contains forbidden restricted text",
        )


def _seal_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(payload)
    _reject_sensitive_receipt(value)
    value["receipt_payload_sha256"] = (
        "sha256:" + _sha256(canonical_bytes(value, pretty=False))
    )
    return value


def validate_receipt_document(raw: bytes) -> dict[str, Any]:
    value = strict_object(raw, label="failure receipt")
    _require(canonical_bytes(value, pretty=True) == raw, "failure receipt bytes are not canonical")
    _reject_sensitive_receipt(
        {key: child for key, child in value.items() if key != "receipt_payload_sha256"}
    )
    receipt_hash = value.get("receipt_payload_sha256")
    _require(
        isinstance(receipt_hash, str) and RECEIPT_HASH.fullmatch(receipt_hash) is not None,
        "failure receipt payload hash is invalid",
    )
    payload = {key: child for key, child in value.items() if key != "receipt_payload_sha256"}
    _require(
        receipt_hash == "sha256:" + _sha256(canonical_bytes(payload, pretty=False)),
        "failure receipt payload hash differs",
    )
    _require(payload == _expected_payload(), "failure receipt exact payload differs")
    return value


def _validate_run_and_jobs(run: Mapping[str, Any], jobs: Mapping[str, Any]) -> None:
    expected = _expected_payload()
    projected = {
        **{
            key: run.get(key)
            for key in (
                "conclusion",
                "event",
                "head_branch",
                "head_sha",
                "html_url",
                "id",
                "name",
                "path",
                "run_attempt",
                "run_started_at",
                "status",
                "updated_at",
                "workflow_id",
            )
        },
        "actor": run.get("actor", {}).get("login") if isinstance(run.get("actor"), Mapping) else None,
        "triggering_actor": (
            run.get("triggering_actor", {}).get("login")
            if isinstance(run.get("triggering_actor"), Mapping)
            else None
        ),
    }
    _require(projected == expected["workflow_run"], "workflow-run projection differs")
    repository = run.get("repository")
    _require(
        isinstance(repository, Mapping)
        and repository.get("full_name") == EXPECTED_REPOSITORY,
        "workflow-run repository differs",
    )
    rows = jobs.get("jobs")
    _require(jobs.get("total_count") == 2 and isinstance(rows, list) and len(rows) == 2, "workflow job set differs")
    indexed = {
        row.get("name"): row for row in rows if isinstance(row, Mapping)
    }
    _require(set(indexed) == {"branch-trigger-preflight", "frozen-gold-noop-smoke"}, "workflow job names differ")
    preflight = indexed["branch-trigger-preflight"]
    execution = indexed["frozen-gold-noop-smoke"]
    _require(
        preflight.get("id") == EXPECTED_PREFLIGHT_JOB_ID
        and preflight.get("status") == "completed"
        and preflight.get("conclusion") == "success",
        "preflight job projection differs",
    )
    _require(
        execution.get("id") == EXPECTED_EXECUTION_JOB_ID
        and execution.get("status") == "completed"
        and execution.get("conclusion") == "failure"
        and execution.get("started_at") == "2026-09-02T12:34:37Z"
        and execution.get("completed_at") == "2026-09-02T12:47:23Z",
        "execution job projection differs",
    )
    steps = execution.get("steps")
    _require(isinstance(steps, list), "execution job steps are missing")
    step_results = {
        row.get("name"): row.get("conclusion")
        for row in steps
        if isinstance(row, Mapping)
    }
    expected_steps = {
        "Aggregate exact target set fail closed": "skipped",
        "Attest exact uploaded and cleaned official smoke subject": "skipped",
        "Build deterministic official smoke attestation subject": "skipped",
        "Build public allowlisted result": "skipped",
        "Encrypt complete restricted evidence": "success",
        "Inventory every restricted evidence file": "success",
        "Remove plaintext and temporary EXEC material before signing": "success",
        "Run bounded-disk exact GOLD and NOOP_BASELINE pairs serially": "failure",
        "Upload encrypted restricted evidence": "success",
        "Upload non-sensitive restricted evidence inventory": "success",
        "Upload public smoke result": "skipped",
    }
    _require(
        all(step_results.get(name) == result for name, result in expected_steps.items()),
        "workflow failure/evidence step projection differs",
    )


def _validate_restricted_semantics(
    selected: Mapping[str, bytes],
    inventory_rows: Mapping[str, Mapping[str, Any]],
) -> None:
    approval = strict_object(
        selected["results/external-approval-evidence.json"],
        label="external approval evidence",
    )
    _require(approval == APPROVAL_BINDING, "external approval binding differs")
    restricted_approval = inventory_rows.get("results/restricted-external-approval.json")
    _require(
        isinstance(restricted_approval, Mapping)
        and restricted_approval.get("sha256")
        == APPROVAL_BINDING["approval_artifact_sha256"]
        and type(restricted_approval.get("bytes")) is int
        and restricted_approval["bytes"] > 0,
        "restricted approval inventory binding differs",
    )

    rows: list[dict[str, Any]] = []
    formal_evidence_counts = {
        "digest_match": 0,
        "host_prepare_sh_access_count": 0,
        "patch_applied": 0,
        "source_image_build_count": 0,
        "submitted_patch_identity": 0,
        "tests_executed": 0,
    }
    for expected in EXPECTED_DIAGNOSTIC_ROWS:
        path = (
            f"results/{expected['order_index']:03d}-{expected['target_id']}/"
            f"{expected['target_id']}.result.json"
        )
        result = strict_object(selected[path], label=f"diagnostic result {expected['order_index']}")
        projection = {
            key: result.get(key)
            for key in (
                "benchmark_id",
                "container_started",
                "execution_status",
                "official_grader",
                "order_index",
                "probe",
                "resolved",
                "target_id",
            )
        }
        _require(projection == expected, "diagnostic result projection differs")
        accounting = result.get("actual_accounting")
        _require(
            isinstance(accounting, Mapping)
            and accounting.get("grader_calls") == 1
            and accounting.get("grader_containers") == 1
            and accounting.get("official_grader_runs") == 1
            and all(
                value == 0
                for key, value in accounting.items()
                if key not in {"grader_calls", "grader_containers", "official_grader_runs"}
            ),
            "diagnostic result accounting differs",
        )
        execution_evidence = result.get("execution_evidence")
        _require(
            isinstance(execution_evidence, Mapping)
            and execution_evidence.get("patch_applied") is True
            and execution_evidence.get("tests_executed") is True
            and execution_evidence.get("digest_match") is True
            and execution_evidence.get("submitted_patch_identity") is True
            and execution_evidence.get("host_prepare_sh_access_count") == 0
            and execution_evidence.get("source_image_build_count") == 0
            and execution_evidence.get("api_calls") == 0,
            "diagnostic result execution evidence differs",
        )
        for key in (
            "patch_applied",
            "tests_executed",
            "digest_match",
            "submitted_patch_identity",
        ):
            formal_evidence_counts[key] += 1
        formal_evidence_counts["host_prepare_sh_access_count"] += int(
            execution_evidence["host_prepare_sh_access_count"]
        )
        formal_evidence_counts["source_image_build_count"] += int(
            execution_evidence["source_image_build_count"]
        )
        rows.append(projection)
    _require(rows == EXPECTED_DIAGNOSTIC_ROWS, "diagnostic result order differs")
    _require(
        formal_evidence_counts == EVIDENCE_COUNTS["formal_result_rows"],
        "formal result execution evidence counts differ",
    )

    partial_raw = selected[f"{PARTIAL_ROOT}/report.json"]
    _require(bool(partial_raw), "partial failure report is empty")
    partial = strict_object(partial_raw, label="partial failure report")
    trimem = partial.get("_trimem")
    _require(
        partial.get("failure_stage") == "official_test_evidence"
        and partial.get("reason")
        == "Multi-SWE official per-instance status identity/result mismatch"
        and partial.get("resolved") is False
        and isinstance(partial.get("materialized_private_inputs"), list)
        and len(partial["materialized_private_inputs"]) == 3
        and isinstance(trimem, Mapping)
        and "materialized_private_inputs" not in trimem,
        "primary or secondary adapter failure evidence differs",
    )
    execution_contract = trimem.get("execution_contract")
    execution_control = trimem.get("execution_control_evidence")
    _require(
        isinstance(execution_contract, Mapping)
        and execution_contract.get("schema")
        == "trimem/official-grader-execution-contract/1.0"
        and execution_contract.get("container_exit_status")
        == "CAPTURED_AND_FULL_DOMAIN_VALIDATED"
        and execution_contract.get("container_image_execution") == "IMMUTABLE_DIGEST"
        and execution_contract.get("execution_mode") == "instance_only"
        and execution_contract.get("profile") == "MULTI_SWE_PREBUILT_EVALUATION"
        and execution_contract.get("api_calls") == 0
        and execution_contract.get("host_prepare_script_reads") == 0
        and execution_contract.get("source_image_build_calls") == 0
        and execution_contract.get("submitted_patch_bytes") == 165
        and execution_contract.get("submitted_patch_sha256")
        == "0f4fb705a73dd7e804773b35e2ab0e4e2f17248c571e69333e9b8de7c2025775"
        and isinstance(execution_control, Mapping)
        and execution_control.get("schema")
        == "trimem/official-grader-execution-control/1.0"
        and execution_control.get("profile") == "MULTI_SWE_PREBUILT_EVALUATION"
        and execution_control.get("host_prepare_script_reads") == 0
        and execution_control.get("source_image_build_calls") == 0
        and execution_control.get("support_container_bootstrap_calls") == 0
        and execution_control.get("upstream_module_main_executed") is False,
        "partial execution contract/control evidence differs",
    )
    materialized_patch = partial.get("materialized_patch_evidence")
    _require(
        isinstance(materialized_patch, Mapping)
        and materialized_patch == trimem.get("materialized_patch_evidence")
        and materialized_patch.get("schema")
        == "trimem/materialized-submitted-patch-evidence/1.0"
        and materialized_patch.get("bytes")
        == execution_contract.get("submitted_patch_bytes")
        and materialized_patch.get("sha256")
        == execution_contract.get("submitted_patch_sha256")
        and materialized_patch.get("request_identity_match") is True
        and materialized_patch.get("purged_after_capture") is True,
        "partial materialized patch identity/purge evidence differs",
    )
    image_evidence = partial.get("image_evidence")
    _require(
        isinstance(image_evidence, list)
        and len(image_evidence) == 2
        and all(
            isinstance(row, Mapping)
            and isinstance(row.get("expected"), str)
            and RECEIPT_HASH.fullmatch(row["expected"]) is not None
            and row.get("observed") == [row["expected"]]
            and isinstance(row.get("image"), str)
            and row["image"].endswith("@" + row["expected"])
            for row in image_evidence
        ),
        "partial expected/observed image evidence differs",
    )

    final_report_raw = selected[PARTIAL_FINAL_REPORT]
    _require(bool(final_report_raw), "partial official final report is empty")
    final_report = strict_object(final_report_raw, label="partial official final report")
    canonical_id = "vuejs/core:pr-8911"
    _require(
        final_report.get("total_instances") == 1
        and final_report.get("submitted_instances") == 1
        and final_report.get("completed_instances") == 1
        and final_report.get("incomplete_instances") == 0
        and final_report.get("resolved_instances") == 0
        and final_report.get("unresolved_instances") == 1
        and final_report.get("empty_patch_instances") == 0
        and final_report.get("error_instances") == 0
        and final_report.get("submitted_ids") == [canonical_id]
        and final_report.get("completed_ids") == [canonical_id]
        and final_report.get("resolved_ids") == []
        and final_report.get("unresolved_ids") == [canonical_id]
        and final_report.get("incomplete_ids") == []
        and final_report.get("empty_patch_ids") == []
        and final_report.get("error_ids") == [],
        "partial official outcome projection differs",
    )
    status_report_raw = selected[PARTIAL_STATUS_REPORT]
    _require(bool(status_report_raw), "partial per-instance status is empty")
    status_report = strict_object(status_report_raw, label="partial per-instance status")
    _require(
        set(status_report)
        == {
            "error_msg",
            "f2p_tests",
            "fix_patch_result",
            "fixed_tests",
            "n2p_tests",
            "number",
            "org",
            "p2p_tests",
            "repo",
            "run_result",
            "s2p_tests",
            "test_patch_result",
            "valid",
        }
        and status_report.get("valid") is True,
        "partial official validity/status projection differs",
    )
    test_observation_count = 0
    for key in ("run_result", "test_patch_result", "fix_patch_result"):
        result = status_report.get(key)
        _require(
            isinstance(result, Mapping)
            and set(result)
            == {
                "failed_count",
                "failed_tests",
                "passed_count",
                "passed_tests",
                "skipped_count",
                "skipped_tests",
            }
            and all(
                type(result.get(f"{state}_count")) is int
                and result[f"{state}_count"] >= 0
                and isinstance(result.get(f"{state}_tests"), list)
                and result[f"{state}_count"] == len(result[f"{state}_tests"])
                for state in ("failed", "passed", "skipped")
            ),
            "partial test execution status differs",
        )
        test_observation_count += sum(
            result[f"{state}_count"] for state in ("failed", "passed", "skipped")
        )
    _require(test_observation_count > 0, "partial test execution status is empty")

    container_exit_raw = selected[PARTIAL_CONTAINER_EXIT]
    _require(bool(container_exit_raw), "partial container exit status is empty")
    container_exit = strict_object(
        container_exit_raw, label="partial container exit status"
    )
    _require(
        container_exit.get("schema") == "trimem/multi-swe-container-exit-status/1.0"
        and container_exit.get("status_code") == 1
        and container_exit.get("executed_image") == container_exit.get("expected_image")
        and any(
            row.get("image") == container_exit.get("executed_image")
            for row in image_evidence
        )
        and container_exit.get("submitted_patch_bytes")
        == materialized_patch.get("bytes")
        and container_exit.get("submitted_patch_sha256")
        == materialized_patch.get("sha256"),
        "partial container exit/identity evidence differs",
    )
    forensic_evidence_counts = dict(formal_evidence_counts)
    for key in (
        "patch_applied",
        "tests_executed",
        "digest_match",
        "submitted_patch_identity",
    ):
        forensic_evidence_counts[key] += 1
    forensic_evidence_counts["host_prepare_sh_access_count"] += int(
        execution_contract["host_prepare_script_reads"]
    )
    forensic_evidence_counts["source_image_build_count"] += int(
        execution_contract["source_image_build_calls"]
    )
    _require(
        forensic_evidence_counts == EVIDENCE_COUNTS["forensic_executed_outcomes"],
        "forensic execution evidence counts differ",
    )

    lifecycle = strict_object(
        selected["image-materialization/image-lifecycle-report.json"],
        label="image lifecycle",
    )
    _require(
        lifecycle.get("schema") == "trimem/grader-smoke-image-lifecycle/1.0"
        and lifecycle.get("git_head") == EXPECTED_HEAD
        and lifecycle.get("phase") == "GRADER_SMOKE"
        and lifecycle.get("status") == "FAILED"
        and lifecycle.get("actual")
        == {
            "exact_image_removals": 4,
            "max_resident_support_images": 1,
            "max_resident_target_images": 1,
            "resident_support_images": 0,
            "resident_target_images": 0,
            "support_image_pulls": 1,
            "target_image_pulls": 3,
        }
        and lifecycle.get("failure")
        == {
            "error": "official grader private-input identity set differs",
            "error_type": "BenchmarkExecutionError",
        },
        "image lifecycle failure projection differs",
    )
    cleanup = strict_object(
        selected["workflow-image-cleanup/workflow-image-cleanup-report.json"],
        label="workflow image cleanup",
    )
    _require(
        cleanup.get("status") == "PASS"
        and cleanup.get("exact_reference_count") == 14
        and cleanup.get("already_absent_reference_count") == 14
        and cleanup.get("removed_reference_count") == 0,
        "workflow image cleanup projection differs",
    )
    forbidden_results = {
        "aggregate.json",
        "public-results.json",
        "attestation-subject.json",
        "results/smoke-execution-summary.json",
    }
    _require(
        not (forbidden_results & set(inventory_rows)),
        "failed run unexpectedly contains PASS/aggregate material",
    )
    result_paths = {
        path
        for path in inventory_rows
        if re.fullmatch(r"results/[0-9]{3}-[^/]+/[^/]+\.result\.json", path)
    }
    expected_paths = {
        f"results/{row['order_index']:03d}-{row['target_id']}/{row['target_id']}.result.json"
        for row in EXPECTED_DIAGNOSTIC_ROWS
    }
    _require(result_paths == expected_paths, "formal result row exact set differs")


def build_failure_evidence(source_dir: Path) -> tuple[dict[str, Any], bytes]:
    source_dir = source_dir.resolve(strict=True)
    _require(source_dir.is_dir() and not source_dir.is_symlink(), "source directory is invalid")
    source_raw = {
        name: _verified_source(source_dir, name) for name in SOURCE_FILES
    }
    run = strict_object(source_raw["run-attempt.json"], label="workflow run API")
    jobs = strict_object(source_raw["jobs.json"], label="workflow jobs API")
    artifacts = strict_object(source_raw["artifacts.json"], label="workflow artifacts API")
    inventory_artifact = strict_object(
        source_raw["inventory-artifact.json"], label="inventory artifact API"
    )
    restricted_artifact = strict_object(
        source_raw["restricted-artifact.json"], label="restricted artifact API"
    )
    _validate_run_and_jobs(run, jobs)

    artifact_rows = artifacts.get("artifacts")
    _require(
        artifacts.get("total_count") == 2
        and isinstance(artifact_rows, list)
        and len(artifact_rows) == 2,
        "workflow artifact set differs",
    )
    indexed_artifacts = {
        row.get("id"): row for row in artifact_rows if isinstance(row, Mapping)
    }
    _require(
        set(indexed_artifacts)
        == {EXPECTED_INVENTORY_ARTIFACT_ID, EXPECTED_RESTRICTED_ARTIFACT_ID},
        "workflow artifact IDs differ",
    )
    inventory_projection = _validate_artifact(
        inventory_artifact,
        artifact_id=EXPECTED_INVENTORY_ARTIFACT_ID,
        name="trimem-grader-smoke-evidence-inventory",
        digest=SOURCE_FILES["inventory-artifact.zip"][1],
        size=SOURCE_FILES["inventory-artifact.zip"][0],
    )
    restricted_projection = _validate_artifact(
        restricted_artifact,
        artifact_id=EXPECTED_RESTRICTED_ARTIFACT_ID,
        name="trimem-grader-smoke-restricted-encrypted",
        digest=SOURCE_FILES["restricted-artifact.zip"][1],
        size=SOURCE_FILES["restricted-artifact.zip"][0],
    )
    _require(
        _artifact_projection(indexed_artifacts[EXPECTED_INVENTORY_ARTIFACT_ID])
        == inventory_projection
        and _artifact_projection(indexed_artifacts[EXPECTED_RESTRICTED_ARTIFACT_ID])
        == restricted_projection,
        "artifact list/detail projections differ",
    )

    inventory_raw = _single_zip_member(
        source_raw["inventory-artifact.zip"],
        expected_name=INVENTORY_MEMBER_NAME,
        label="inventory artifact archive",
    )
    inventory, inventory_rows = _validate_inventory(inventory_raw)
    encrypted_raw = _single_zip_member(
        source_raw["restricted-artifact.zip"],
        expected_name=RESTRICTED_MEMBER_NAME,
        label="restricted artifact archive",
    )
    _require(
        encrypted_raw == source_raw[RESTRICTED_MEMBER_NAME],
        "downloaded encrypted member differs from artifact archive",
    )
    selected = _audit_tar(
        source_dir / RESTRICTED_TAR_NAME,
        inventory_raw=inventory_raw,
        inventory_rows=inventory_rows,
    )
    _validate_restricted_semantics(selected, inventory_rows)
    _require(
        inventory["total_files"] == EXPECTED_INVENTORY_FILE_COUNT,
        "inventory validation did not close",
    )
    receipt = _seal_payload(_expected_payload())
    validate_receipt_document(canonical_bytes(receipt, pretty=True))
    return receipt, inventory_raw


def _repository_output(root: Path, relative: str) -> Path:
    root = root.resolve(strict=True)
    target = (root / relative).resolve()
    _require(root in target.parents, "failure evidence output escapes repository")
    _require(not target.is_symlink(), "failure evidence output is a symlink")
    return target


def _write_exclusive(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise FailureEvidenceError(f"refusing to overwrite failure evidence: {path.name}") from exc


def write_failure_evidence(source_dir: Path, root: Path) -> dict[str, Any]:
    receipt_path = _repository_output(root, FAILURE_RECEIPT_PATH)
    inventory_path = _repository_output(root, EVIDENCE_INVENTORY_PATH)
    _require(
        not receipt_path.exists()
        and not receipt_path.is_symlink()
        and not inventory_path.exists()
        and not inventory_path.is_symlink(),
        "refusing to overwrite existing failure evidence",
    )
    receipt, inventory_raw = build_failure_evidence(source_dir)
    receipt_raw = canonical_bytes(receipt, pretty=True)
    _write_exclusive(inventory_path, inventory_raw)
    _write_exclusive(receipt_path, receipt_raw)
    return {
        "evidence_inventory_bytes": len(inventory_raw),
        "evidence_inventory_raw_sha256": _sha256(inventory_raw),
        "failure_receipt_bytes": len(receipt_raw),
        "failure_receipt_raw_sha256": _sha256(receipt_raw),
        "receipt_payload_sha256": receipt["receipt_payload_sha256"],
    }


def validate_committed_failure_evidence(root: Path) -> dict[str, Any]:
    receipt_path = _repository_output(root, FAILURE_RECEIPT_PATH)
    inventory_path = _repository_output(root, EVIDENCE_INVENTORY_PATH)
    _require(
        receipt_path.is_file()
        and not receipt_path.is_symlink()
        and inventory_path.is_file()
        and not inventory_path.is_symlink(),
        "committed failure evidence pair is missing",
    )
    inventory_raw = inventory_path.read_bytes()
    _validate_inventory(inventory_raw)
    receipt = validate_receipt_document(receipt_path.read_bytes())
    inventory_binding = receipt["artifacts"]["evidence_inventory"]
    _require(
        inventory_binding["member_bytes"] == len(inventory_raw)
        and inventory_binding["member_raw_sha256"]
        == "sha256:" + _sha256(inventory_raw),
        "committed receipt/inventory raw binding differs",
    )
    return receipt


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--repository", type=Path, default=repository_root())
    args = parser.parse_args()
    try:
        if args.write:
            _require(args.source_dir is not None, "--write requires --source-dir")
            summary = write_failure_evidence(args.source_dir, args.repository)
        else:
            _require(args.source_dir is None, "--check does not accept --source-dir")
            receipt = validate_committed_failure_evidence(args.repository)
            receipt_path = _repository_output(args.repository, FAILURE_RECEIPT_PATH)
            inventory_path = _repository_output(args.repository, EVIDENCE_INVENTORY_PATH)
            summary = {
                "evidence_inventory_bytes": inventory_path.stat().st_size,
                "evidence_inventory_raw_sha256": _sha256(inventory_path.read_bytes()),
                "failure_receipt_bytes": receipt_path.stat().st_size,
                "failure_receipt_raw_sha256": _sha256(receipt_path.read_bytes()),
                "receipt_payload_sha256": receipt["receipt_payload_sha256"],
            }
        print(json.dumps({**summary, "status": "PASS"}, sort_keys=True))
        return 0
    except (OSError, FailureEvidenceError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL_CLOSED"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
