"""Fail-closed closure for the one-time sanitized Vue image-probe evidence.

The probe result contains only the allowlisted image facts.  A separate
receipt binds those bytes to the marker commit and GitHub Actions
run/job/artifact provenance.  The receipt cannot contain its own eventual Git
commit hash, so the subsequent evidence commit is proven from Git ancestry and
its exact three-path diff when this module validates the committed closure.

This module performs no network, Docker, grader, or model operation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping
import zipfile

import trimem_multi_swe_probe_request as probe_request
from trimem_multi_swe_image_probe import (
    EXPECTED_BASE_COMMIT,
    EXPECTED_IMAGE,
    REPOSITORY_PATH,
    REQUIRED_PATHS,
)


PROBE_REQUEST_PATH = probe_request.REQUEST_PATH
PROBE_RESULT_PATH = (
    "artifacts/trimem_v1/probe_evidence/"
    "MULTI_SWE_VUE_IMAGE_PROBE_RESULT_001.json"
)
PROBE_RECEIPT_PATH = (
    "artifacts/trimem_v1/probe_evidence/"
    "MULTI_SWE_VUE_IMAGE_PROBE_RECEIPT_001.json"
)
FREEZE_PATH = probe_request.FREEZE_PATH
EXPECTED_REPOSITORY = probe_request.EXPECTED_REPOSITORY
EXPECTED_REF = probe_request.EXPECTED_REF
EXPECTED_BRANCH = EXPECTED_REF.removeprefix("refs/heads/")
EXPECTED_PHASE = probe_request.EXPECTED_PHASE
WORKFLOW_PATH = probe_request.WORKFLOW_PATH
WORKFLOW_NAME = "TriMem Multi-SWE prebuilt contract"
PROBE_JOB_NAME = "One-time marker-bound exact Vue image contract probe"
ARTIFACT_NAME = "trimem-multi-swe-vue-image-probe"
ARTIFACT_MEMBER = "multi_swe_vue_image_probe.json"
REQUIRED_JOB_STEPS = (
    "Checkout exact probe source",
    "Set up exact Python",
    "Classify checked-out Git push and validate an exact marker request",
    "Preserve sanitized probe-gate evidence",
    "Pull, observe, inspect metadata, and remove the exact Vue image",
    "Preserve only the sanitized probe result on pass or failure",
    "Fail closed if an exact request did not reach the image probe",
)
EXPECTED_DIGEST = EXPECTED_IMAGE.rsplit("@", 1)[1]
RESULT_SCHEMA = "trimem/multi-swe-prebuilt-image-contract-probe/1.0"
RECEIPT_SCHEMA = "trimem/multi-swe-vue-image-probe-receipt/1.0"
BINDING_SCHEMA = "trimem/multi-swe-vue-image-probe-evidence-binding/1.0"
ACCOUNTING = {
    "api_calls": 0,
    "grader_containers": 0,
    "grader_executions": 0,
    "image_contract_probe_containers": 1,
    "image_pulls": 1,
    "input_tokens": 0,
    "model_calls": 0,
    "official_tests": 0,
    "output_tokens": 0,
    "paid_model_calls": 0,
    "patch_applications": 0,
    "task_arm_runs": 0,
    "total_usd": 0.0,
}
HEX40 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


class ProbeEvidenceError(ValueError):
    """The sanitized result, provenance receipt, or Git closure differed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProbeEvidenceError(message)


def _reject_constant(value: str) -> None:
    raise ProbeEvidenceError(f"non-finite JSON number is forbidden: {value}")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise ProbeEvidenceError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def strict_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeEvidenceError(f"{label} is not strict UTF-8 JSON") from exc
    _require(isinstance(value, dict), f"{label} root is not an object")
    return value


def canonical_bytes(value: Any, *, pretty: bool) -> bytes:
    try:
        if pretty:
            text = json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
        else:
            text = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
    except (TypeError, ValueError) as exc:
        raise ProbeEvidenceError("probe evidence is not canonical JSON") from exc
    return text.encode("utf-8") + (b"\n" if pretty else b"")


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def expected_probe_result() -> dict[str, Any]:
    return {
        "expected_digest": EXPECTED_DIGEST,
        "observed_digests": [EXPECTED_DIGEST],
        "removal_evidence": {
            "digest_reference_absent": True,
            "removal_established": True,
            "removed_reference_count": 2,
            "tag_reference_absent": True,
        },
        "repository": {
            "base_commit": EXPECTED_BASE_COMMIT,
            "checkout_present": True,
            "head": EXPECTED_BASE_COMMIT,
            "path": REPOSITORY_PATH,
        },
        "required_paths_present": {path: True for path in REQUIRED_PATHS},
        "schema": RESULT_SCHEMA,
        "status": "PASS",
    }


def validate_probe_result(raw: bytes) -> dict[str, Any]:
    value = strict_object(raw, label="Vue image probe result")
    expected = expected_probe_result()
    _require(value == expected, "Vue image probe PASS result differs")
    _require(
        raw == canonical_bytes(expected, pretty=True),
        "Vue image probe result bytes are not canonical pretty JSON",
    )
    return value


def _git(
    repository: Path, *args: str, text: bool = True, check: bool = True
) -> str | bytes | subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=repository,
            capture_output=True,
            text=text,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProbeEvidenceError("probe evidence Git verification could not complete") from exc
    if check and result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
        raise ProbeEvidenceError("probe evidence Git verification failed: " + stderr.strip())
    if not check:
        return result
    return result.stdout


def _commit_bytes(repository: Path, commit: str, path: str) -> bytes:
    value = _git(repository, "show", f"{commit}:{path}", text=False)
    assert isinstance(value, bytes)
    return value


def _path_exists(repository: Path, commit: str, path: str) -> bool:
    result = _git(
        repository, "cat-file", "-e", f"{commit}:{path}", check=False
    )
    assert isinstance(result, subprocess.CompletedProcess)
    return result.returncode == 0


def _regular_blob(repository: Path, commit: str, path: str) -> None:
    value = str(_git(repository, "ls-tree", commit, "--", path)).strip()
    _require(
        re.fullmatch(rf"100644 blob [0-9a-f]{{40}}\t{re.escape(path)}", value)
        is not None,
        f"probe evidence path is not one regular Git blob: {path}",
    )


def _one_parent(repository: Path, commit: str, expected_parent: str) -> None:
    kind = str(_git(repository, "cat-file", "-t", commit)).strip()
    _require(kind == "commit", f"not a Git commit: {commit}")
    parents = str(
        _git(repository, "rev-list", "--parents", "-n", "1", commit)
    ).strip().split()
    _require(parents == [commit, expected_parent], f"commit parent differs: {commit}")


def _changed_paths(repository: Path, commit: str) -> dict[str, str]:
    lines = str(
        _git(
            repository,
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "--no-renames",
            commit,
        )
    ).splitlines()
    result: dict[str, str] = {}
    for line in lines:
        parts = line.split("\t")
        _require(len(parts) == 2 and parts[1] not in result, "malformed Git path diff")
        result[parts[1]] = parts[0]
    return result


def _validate_marker_chain(
    repository: Path, *, correction_head: str, marker_head: str
) -> tuple[bytes, dict[str, Any]]:
    _require(
        HEX40.fullmatch(correction_head) is not None
        and HEX40.fullmatch(marker_head) is not None,
        "probe correction/marker commit identity is invalid",
    )
    _one_parent(repository, marker_head, correction_head)
    _require(
        _changed_paths(repository, marker_head) == {PROBE_REQUEST_PATH: "A"},
        "probe marker commit is not marker-only",
    )
    _require(
        not _path_exists(repository, correction_head, PROBE_REQUEST_PATH),
        "probe request existed before the marker commit",
    )
    _regular_blob(repository, marker_head, PROBE_REQUEST_PATH)
    marker_raw = _commit_bytes(repository, marker_head, PROBE_REQUEST_PATH)
    try:
        marker = probe_request.validate_request_document(
            repository,
            marker_raw,
            expected_correction_head=correction_head,
        )
    except probe_request.ProbeRequestError as exc:
        raise ProbeEvidenceError(f"probe marker request differs: {exc}") from exc
    return marker_raw, marker


def _positive_int(value: Any, label: str) -> int:
    _require(type(value) is int and value > 0, f"{label} is not a positive integer")
    return value


def _utc_timestamp(value: Any) -> str:
    _require(isinstance(value, str) and value.endswith("Z"), "receipt timestamp is not UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ProbeEvidenceError("receipt timestamp is invalid") from exc
    _require(parsed.tzinfo == timezone.utc, "receipt timestamp is not UTC")
    return value


def _raw_source(raw: bytes) -> dict[str, Any]:
    return {"bytes": len(raw), "raw_sha256": _sha256(raw)}


def _validate_provenance_inputs(
    *,
    marker_head: str,
    result_raw: bytes,
    workflow_run_raw: bytes,
    workflow_jobs_raw: bytes,
    artifact_raw: bytes,
    artifact_archive_raw: bytes,
) -> dict[str, Any]:
    run = strict_object(workflow_run_raw, label="workflow run-attempt API response")
    jobs_document = strict_object(workflow_jobs_raw, label="workflow jobs API response")
    artifact = strict_object(artifact_raw, label="workflow artifact API response")
    api_root = f"https://api.github.com/repos/{EXPECTED_REPOSITORY}"

    run_id = _positive_int(run.get("id"), "workflow run ID")
    _require(
        type(run.get("run_attempt")) is int and run["run_attempt"] == 1,
        "workflow run attempt is not exactly one",
    )
    _require(run.get("event") == "push", "workflow run event is not push")
    _require(
        run.get("status") == "completed" and run.get("conclusion") == "success",
        "workflow run is not completed/success",
    )
    _require(
        run.get("head_sha") == marker_head
        and run.get("head_branch") == EXPECTED_BRANCH,
        "workflow run marker identity differs",
    )
    _require(
        run.get("name") == WORKFLOW_NAME and run.get("path") == WORKFLOW_PATH,
        "workflow run identity differs",
    )
    _require(
        run.get("url") == f"{api_root}/actions/runs/{run_id}"
        and run.get("html_url")
        == f"https://github.com/{EXPECTED_REPOSITORY}/actions/runs/{run_id}",
        "workflow run URLs differ",
    )

    jobs = jobs_document.get("jobs")
    _require(isinstance(jobs, list), "workflow jobs API response has no jobs list")
    _require(
        type(jobs_document.get("total_count")) is int
        and jobs_document["total_count"] == len(jobs),
        "workflow jobs response count differs",
    )
    matching_jobs = [
        job for job in jobs if isinstance(job, dict) and job.get("name") == PROBE_JOB_NAME
    ]
    _require(len(matching_jobs) == 1, "exact probe job is missing or duplicated")
    job = matching_jobs[0]
    job_id = _positive_int(job.get("id"), "workflow job ID")
    _require(
        type(job.get("run_id")) is int and job["run_id"] == run_id,
        "workflow job run ID differs",
    )
    _require(
        job.get("head_sha") == marker_head
        and job.get("head_branch") == EXPECTED_BRANCH,
        "workflow job marker identity differs",
    )
    _require(
        job.get("status") == "completed" and job.get("conclusion") == "success",
        "workflow job is not completed/success",
    )
    steps = job.get("steps")
    _require(isinstance(steps, list), "workflow probe job has no step evidence")
    step_projection: list[dict[str, str]] = []
    for name in REQUIRED_JOB_STEPS:
        matches = [
            step
            for step in steps
            if isinstance(step, dict) and step.get("name") == name
        ]
        _require(len(matches) == 1, f"required workflow step is missing or duplicated: {name}")
        step = matches[0]
        _require(
            step.get("status") == "completed" and step.get("conclusion") == "success",
            f"required workflow step is not completed/success: {name}",
        )
        step_projection.append(
            {"conclusion": "success", "name": name, "status": "completed"}
        )

    artifact_id = _positive_int(artifact.get("id"), "artifact ID")
    artifact_size = _positive_int(artifact.get("size_in_bytes"), "artifact size")
    artifact_digest = artifact.get("digest")
    _require(
        isinstance(artifact_digest, str)
        and SHA256.fullmatch(artifact_digest) is not None,
        "artifact digest is invalid",
    )
    _require(artifact.get("name") == ARTIFACT_NAME, "artifact name differs")
    _require(artifact.get("expired") is False, "probe artifact is expired")
    _require(
        artifact.get("url") == f"{api_root}/actions/artifacts/{artifact_id}"
        and artifact.get("archive_download_url")
        == f"{api_root}/actions/artifacts/{artifact_id}/zip",
        "artifact URLs differ",
    )
    created_at = _utc_timestamp(artifact.get("created_at"))
    expires_at = _utc_timestamp(artifact.get("expires_at"))
    artifact_run = artifact.get("workflow_run")
    _require(isinstance(artifact_run, dict), "artifact workflow_run binding is missing")
    _require(
        type(artifact_run.get("id")) is int
        and artifact_run["id"] == run_id
        and artifact_run.get("head_sha") == marker_head
        and artifact_run.get("head_branch") == EXPECTED_BRANCH,
        "artifact workflow-run marker binding differs",
    )
    _require(
        _sha256(artifact_archive_raw) == artifact_digest,
        "downloaded artifact archive digest differs from the API digest",
    )
    _require(
        len(artifact_archive_raw) == artifact_size,
        "downloaded artifact archive size differs from the API size",
    )
    try:
        with zipfile.ZipFile(io.BytesIO(artifact_archive_raw), "r") as archive:
            entries = archive.infolist()
            _require(len(entries) == 1, "probe artifact ZIP must contain exactly one entry")
            entry = entries[0]
            _require(
                entry.filename == ARTIFACT_MEMBER and not entry.is_dir(),
                "probe artifact ZIP member differs",
            )
            _require(not (entry.flag_bits & 0x1), "encrypted probe artifact is forbidden")
            unix_mode = (entry.external_attr >> 16) & 0o170000
            _require(
                unix_mode in (0, 0o100000),
                "probe artifact ZIP member is not a regular file",
            )
            archived_result = archive.read(entry)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ProbeEvidenceError("probe artifact archive is not a valid ZIP") from exc
    _require(
        archived_result == result_raw,
        "probe artifact member bytes differ from the committed result",
    )

    return {
        "artifact": {
            "api_url": f"{api_root}/actions/artifacts/{artifact_id}",
            "archive_download_url": f"{api_root}/actions/artifacts/{artifact_id}/zip",
            "created_at": created_at,
            "digest": artifact_digest,
            "expired": False,
            "expires_at": expires_at,
            "id": artifact_id,
            "name": ARTIFACT_NAME,
            "result_member": ARTIFACT_MEMBER,
            "result_member_bytes": len(result_raw),
            "result_member_raw_sha256": _sha256(result_raw),
            "size_in_bytes": artifact_size,
        },
        "sources": {
            "artifact_api": {
                **_raw_source(artifact_raw),
                "url": f"{api_root}/actions/artifacts/{artifact_id}",
            },
            "artifact_archive": {
                **_raw_source(artifact_archive_raw),
                "url": f"{api_root}/actions/artifacts/{artifact_id}/zip",
            },
            "workflow_jobs_api": {
                **_raw_source(workflow_jobs_raw),
                "url": (
                    f"{api_root}/actions/runs/{run_id}/attempts/1/jobs"
                    "?filter=all&per_page=100"
                ),
            },
            "workflow_run_attempt_api": {
                **_raw_source(workflow_run_raw),
                "url": f"{api_root}/actions/runs/{run_id}/attempts/1",
            },
        },
        "workflow_job": {
            "api_url": f"{api_root}/actions/jobs/{job_id}",
            "conclusion": "success",
            "head_branch": EXPECTED_BRANCH,
            "head_sha": marker_head,
            "id": job_id,
            "name": PROBE_JOB_NAME,
            "run_id": run_id,
            "status": "completed",
            "steps": step_projection,
        },
        "workflow_run": {
            "api_url": f"{api_root}/actions/runs/{run_id}/attempts/1",
            "attempt": 1,
            "conclusion": "success",
            "event": "push",
            "head_branch": EXPECTED_BRANCH,
            "head_sha": marker_head,
            "html_url": f"https://github.com/{EXPECTED_REPOSITORY}/actions/runs/{run_id}",
            "id": run_id,
            "name": WORKFLOW_NAME,
            "path": WORKFLOW_PATH,
            "status": "completed",
        },
    }


def build_receipt_document(
    repository: Path,
    *,
    correction_head: str,
    marker_head: str,
    result_raw: bytes,
    workflow_run_raw: bytes,
    workflow_jobs_raw: bytes,
    artifact_raw: bytes,
    artifact_archive_raw: bytes,
    observed_at_utc: str,
) -> dict[str, Any]:
    repository = repository.resolve(strict=True)
    validate_probe_result(result_raw)
    marker_raw, marker = _validate_marker_chain(
        repository, correction_head=correction_head, marker_head=marker_head
    )
    observed_at = _utc_timestamp(observed_at_utc)
    provenance = _validate_provenance_inputs(
        marker_head=marker_head,
        result_raw=result_raw,
        workflow_run_raw=workflow_run_raw,
        workflow_jobs_raw=workflow_jobs_raw,
        artifact_raw=artifact_raw,
        artifact_archive_raw=artifact_archive_raw,
    )
    payload: dict[str, Any] = {
        "accounting": dict(ACCOUNTING),
        "artifact": provenance["artifact"],
        "correction_head": correction_head,
        "marker_head": marker_head,
        "observed_at_utc": observed_at,
        "phase": EXPECTED_PHASE,
        "probe_request": {
            "bytes": len(marker_raw),
            "document_sha256": marker["request_sha256"],
            "path": PROBE_REQUEST_PATH,
            "raw_sha256": _sha256(marker_raw),
        },
        "probe_result": {
            "bytes": len(result_raw),
            "path": PROBE_RESULT_PATH,
            "raw_sha256": _sha256(result_raw),
            "schema": RESULT_SCHEMA,
            "status": "PASS",
        },
        "repository": EXPECTED_REPOSITORY,
        "schema": RECEIPT_SCHEMA,
        "source_documents": provenance["sources"],
        "status": "PASS",
        "workflow_job": provenance["workflow_job"],
        "workflow_run": provenance["workflow_run"],
    }
    return {
        **payload,
        "receipt_payload_sha256": _sha256(canonical_bytes(payload, pretty=False)),
    }


def validate_receipt_document(
    repository: Path,
    raw: bytes,
    *,
    result_raw: bytes,
) -> dict[str, Any]:
    value = strict_object(raw, label="Vue image probe receipt")
    required = {
        "accounting",
        "artifact",
        "correction_head",
        "marker_head",
        "observed_at_utc",
        "phase",
        "probe_request",
        "probe_result",
        "receipt_payload_sha256",
        "repository",
        "schema",
        "source_documents",
        "status",
        "workflow_job",
        "workflow_run",
    }
    _require(set(value) == required, "probe receipt field set differs")
    _require(
        value.get("schema") == RECEIPT_SCHEMA and value.get("status") == "PASS",
        "probe receipt is not an exact PASS receipt",
    )
    _require(value.get("repository") == EXPECTED_REPOSITORY, "receipt repository differs")
    _require(value.get("phase") == EXPECTED_PHASE, "receipt phase differs")
    _utc_timestamp(value.get("observed_at_utc"))
    _require(
        value.get("accounting") == ACCOUNTING
        and all(
            type(value["accounting"].get(field)) is type(expected)
            for field, expected in ACCOUNTING.items()
        ),
        "probe receipt accounting differs",
    )
    run = value.get("workflow_run")
    job = value.get("workflow_job")
    artifact = value.get("artifact")
    sources = value.get("source_documents")
    request = value.get("probe_request")
    result = value.get("probe_result")
    _require(
        all(
            isinstance(item, dict)
            for item in (run, job, artifact, sources, request, result)
        ),
        "probe receipt objects are missing",
    )
    marker_raw, marker = _validate_marker_chain(
        repository,
        correction_head=str(value.get("correction_head", "")),
        marker_head=str(value.get("marker_head", "")),
    )
    _require(
        set(request) == {"bytes", "document_sha256", "path", "raw_sha256"}
        and request
        == {
            "bytes": len(marker_raw),
            "document_sha256": marker["request_sha256"],
            "path": PROBE_REQUEST_PATH,
            "raw_sha256": _sha256(marker_raw),
        },
        "probe receipt request binding differs",
    )
    _require(
        set(result) == {"bytes", "path", "raw_sha256", "schema", "status"}
        and result
        == {
            "bytes": len(result_raw),
            "path": PROBE_RESULT_PATH,
            "raw_sha256": _sha256(result_raw),
            "schema": RESULT_SCHEMA,
            "status": "PASS",
        },
        "probe receipt result binding differs",
    )
    run_id = _positive_int(run.get("id"), "workflow run ID")
    job_id = _positive_int(job.get("id"), "workflow job ID")
    artifact_id = _positive_int(artifact.get("id"), "artifact ID")
    api_root = f"https://api.github.com/repos/{EXPECTED_REPOSITORY}"
    _require(
        type(run.get("attempt")) is int and run["attempt"] == 1,
        "probe receipt run attempt is not integer one",
    )
    expected_run = {
        "api_url": f"{api_root}/actions/runs/{run_id}/attempts/1",
        "attempt": 1,
        "conclusion": "success",
        "event": "push",
        "head_branch": EXPECTED_BRANCH,
        "head_sha": value["marker_head"],
        "html_url": f"https://github.com/{EXPECTED_REPOSITORY}/actions/runs/{run_id}",
        "id": run_id,
        "name": WORKFLOW_NAME,
        "path": WORKFLOW_PATH,
        "status": "completed",
    }
    _require(run == expected_run, "probe receipt workflow-run projection differs")
    expected_steps = [
        {"conclusion": "success", "name": name, "status": "completed"}
        for name in REQUIRED_JOB_STEPS
    ]
    expected_job = {
        "api_url": f"{api_root}/actions/jobs/{job_id}",
        "conclusion": "success",
        "head_branch": EXPECTED_BRANCH,
        "head_sha": value["marker_head"],
        "id": job_id,
        "name": PROBE_JOB_NAME,
        "run_id": run_id,
        "status": "completed",
        "steps": expected_steps,
    }
    _require(job == expected_job, "probe receipt workflow-job projection differs")
    _require(
        set(artifact)
        == {
            "api_url",
            "archive_download_url",
            "created_at",
            "digest",
            "expired",
            "expires_at",
            "id",
            "name",
            "result_member",
            "result_member_bytes",
            "result_member_raw_sha256",
            "size_in_bytes",
        },
        "probe receipt artifact field set differs",
    )
    _require(
        artifact.get("api_url") == f"{api_root}/actions/artifacts/{artifact_id}"
        and artifact.get("archive_download_url")
        == f"{api_root}/actions/artifacts/{artifact_id}/zip"
        and artifact.get("name") == ARTIFACT_NAME
        and artifact.get("expired") is False
        and artifact.get("result_member") == ARTIFACT_MEMBER
        and artifact.get("result_member_bytes") == len(result_raw)
        and artifact.get("result_member_raw_sha256") == _sha256(result_raw)
        and type(artifact.get("size_in_bytes")) is int
        and artifact["size_in_bytes"] > 0
        and isinstance(artifact.get("digest"), str)
        and SHA256.fullmatch(artifact["digest"]) is not None,
        "probe receipt artifact projection differs",
    )
    _utc_timestamp(artifact.get("created_at"))
    _utc_timestamp(artifact.get("expires_at"))
    expected_source_urls = {
        "artifact_api": f"{api_root}/actions/artifacts/{artifact_id}",
        "artifact_archive": f"{api_root}/actions/artifacts/{artifact_id}/zip",
        "workflow_jobs_api": (
            f"{api_root}/actions/runs/{run_id}/attempts/1/jobs"
            "?filter=all&per_page=100"
        ),
        "workflow_run_attempt_api": f"{api_root}/actions/runs/{run_id}/attempts/1",
    }
    _require(set(sources) == set(expected_source_urls), "receipt source set differs")
    for label, url in expected_source_urls.items():
        descriptor = sources.get(label)
        _require(
            isinstance(descriptor, dict)
            and set(descriptor) == {"bytes", "raw_sha256", "url"}
            and type(descriptor.get("bytes")) is int
            and descriptor["bytes"] > 0
            and isinstance(descriptor.get("raw_sha256"), str)
            and SHA256.fullmatch(descriptor["raw_sha256"]) is not None
            and descriptor.get("url") == url,
            f"receipt provenance source differs: {label}",
        )
    _require(
        sources["artifact_archive"]["raw_sha256"] == artifact["digest"],
        "receipt archive source hash differs from artifact digest",
    )
    payload = {key: child for key, child in value.items() if key != "receipt_payload_sha256"}
    _require(
        value.get("receipt_payload_sha256")
        == _sha256(canonical_bytes(payload, pretty=False)),
        "probe receipt payload hash differs",
    )
    _require(
        raw == canonical_bytes(value, pretty=True),
        "probe receipt bytes are not canonical pretty JSON",
    )
    return value


def validate_committed_evidence(
    repository: Path, *, evidence_head: str
) -> dict[str, Any]:
    repository = repository.resolve(strict=True)
    _require(HEX40.fullmatch(evidence_head) is not None, "probe evidence HEAD is invalid")
    current_head = str(_git(repository, "rev-parse", "HEAD")).strip()
    ancestor = _git(
        repository,
        "merge-base",
        "--is-ancestor",
        evidence_head,
        current_head,
        check=False,
    )
    assert isinstance(ancestor, subprocess.CompletedProcess)
    _require(
        ancestor.returncode == 0,
        "probe evidence HEAD is not an ancestor of the checked-out HEAD",
    )
    for path in (PROBE_RESULT_PATH, PROBE_RECEIPT_PATH):
        introductions = str(
            _git(
                repository,
                "log",
                "--format=%H",
                "--diff-filter=A",
                current_head,
                "--",
                path,
            )
        ).splitlines()
        _require(
            introductions == [evidence_head],
            f"probe evidence path has no unique introduction commit: {path}",
        )
    receipt_raw = _commit_bytes(repository, evidence_head, PROBE_RECEIPT_PATH)
    receipt_hint = strict_object(receipt_raw, label="Vue image probe receipt")
    correction_head = str(receipt_hint.get("correction_head", ""))
    marker_head = str(receipt_hint.get("marker_head", ""))
    _one_parent(repository, evidence_head, marker_head)
    _require(
        _changed_paths(repository, evidence_head)
        == {
            FREEZE_PATH: "M",
            PROBE_RECEIPT_PATH: "A",
            PROBE_RESULT_PATH: "A",
        },
        "probe evidence commit must add result/receipt and modify only freeze",
    )
    _require(
        not _path_exists(repository, marker_head, PROBE_RESULT_PATH)
        and not _path_exists(repository, marker_head, PROBE_RECEIPT_PATH),
        "probe result or receipt existed before the evidence commit",
    )
    for path in (PROBE_REQUEST_PATH, PROBE_RESULT_PATH, PROBE_RECEIPT_PATH, FREEZE_PATH):
        _regular_blob(repository, evidence_head, path)
    result_raw = _commit_bytes(repository, evidence_head, PROBE_RESULT_PATH)
    receipt = validate_receipt_document(
        repository, receipt_raw, result_raw=result_raw
    )
    marker_raw, _marker = _validate_marker_chain(
        repository,
        correction_head=correction_head,
        marker_head=marker_head,
    )
    _require(
        _commit_bytes(repository, evidence_head, PROBE_REQUEST_PATH) == marker_raw,
        "probe request bytes changed after the marker commit",
    )

    freeze_raw = _commit_bytes(repository, evidence_head, FREEZE_PATH)
    freeze = strict_object(freeze_raw, label="post-probe freeze")
    files = freeze.get("files")
    _require(
        freeze.get("schema") == "trimem/freeze/1.0" and isinstance(files, dict),
        "post-probe freeze is malformed",
    )
    for path, payload in (
        (PROBE_REQUEST_PATH, marker_raw),
        (PROBE_RESULT_PATH, result_raw),
        (PROBE_RECEIPT_PATH, receipt_raw),
    ):
        _require(
            files.get(path)
            == {
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            },
            f"post-probe freeze does not bind {path}",
        )

    return {
        "accounting": dict(ACCOUNTING),
        "artifact": receipt["artifact"],
        "correction_head": correction_head,
        "evidence_head": evidence_head,
        "files": {
            "probe_receipt": {
                "bytes": len(receipt_raw),
                "path": PROBE_RECEIPT_PATH,
                "raw_sha256": _sha256(receipt_raw),
            },
            "probe_request": {
                "bytes": len(marker_raw),
                "path": PROBE_REQUEST_PATH,
                "raw_sha256": _sha256(marker_raw),
            },
            "probe_result": {
                "bytes": len(result_raw),
                "path": PROBE_RESULT_PATH,
                "raw_sha256": _sha256(result_raw),
            },
        },
        "marker_head": marker_head,
        "schema": BINDING_SCHEMA,
        "source_documents": receipt["source_documents"],
        "status": "PASS",
        "workflow_job": receipt["workflow_job"],
        "workflow_run": receipt["workflow_run"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--evidence-head")
    mode.add_argument("--write-receipt", action="store_true")
    parser.add_argument("--correction-head")
    parser.add_argument("--marker-head")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--workflow-run-json", type=Path)
    parser.add_argument("--workflow-jobs-json", type=Path)
    parser.add_argument("--artifact-json", type=Path)
    parser.add_argument("--artifact-zip", type=Path)
    parser.add_argument("--observed-at-utc")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        repository = args.repository.resolve(strict=True)
        if args.write_receipt:
            required = {
                "artifact JSON": args.artifact_json,
                "artifact ZIP": args.artifact_zip,
                "correction HEAD": args.correction_head,
                "marker HEAD": args.marker_head,
                "observed UTC timestamp": args.observed_at_utc,
                "output": args.output,
                "result": args.result,
                "workflow jobs JSON": args.workflow_jobs_json,
                "workflow run JSON": args.workflow_run_json,
            }
            _require(
                all(value is not None for value in required.values()),
                "receipt writer is missing inputs: "
                + ", ".join(label for label, value in required.items() if value is None),
            )
            assert args.marker_head is not None
            assert args.correction_head is not None
            assert args.observed_at_utc is not None
            assert args.result is not None
            assert args.workflow_run_json is not None
            assert args.workflow_jobs_json is not None
            assert args.artifact_json is not None
            assert args.artifact_zip is not None
            assert args.output is not None
            expected_result = (repository / PROBE_RESULT_PATH).resolve()
            expected_output = (repository / PROBE_RECEIPT_PATH).resolve()
            _require(
                args.result.resolve(strict=True) == expected_result,
                "receipt writer requires the canonical committed-result path",
            )
            _require(
                args.output.resolve() == expected_output,
                "receipt writer requires the canonical receipt output path",
            )
            _require(
                not args.output.exists() and not args.output.is_symlink(),
                "receipt output already exists",
            )
            head = str(_git(repository, "rev-parse", "HEAD")).strip()
            _require(head == args.marker_head, "receipt must be rendered at marker HEAD")
            status = str(
                _git(
                    repository,
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                )
            ).splitlines()
            expected_status = f"?? {PROBE_RESULT_PATH}"
            _require(
                status == [expected_status],
                "receipt rendering requires only the canonical result to be untracked",
            )
            result_raw = args.result.read_bytes()
            document = build_receipt_document(
                repository,
                correction_head=args.correction_head,
                marker_head=args.marker_head,
                result_raw=result_raw,
                workflow_run_raw=args.workflow_run_json.resolve(strict=True).read_bytes(),
                workflow_jobs_raw=args.workflow_jobs_json.resolve(strict=True).read_bytes(),
                artifact_raw=args.artifact_json.resolve(strict=True).read_bytes(),
                artifact_archive_raw=args.artifact_zip.resolve(strict=True).read_bytes(),
                observed_at_utc=args.observed_at_utc,
            )
            receipt_raw = canonical_bytes(document, pretty=True)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            try:
                with args.output.open("xb") as stream:
                    stream.write(receipt_raw)
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError as exc:
                raise ProbeEvidenceError("refusing to overwrite the probe receipt") from exc
            report = {
                "bytes": len(receipt_raw),
                "path": PROBE_RECEIPT_PATH,
                "raw_sha256": _sha256(receipt_raw),
                "receipt_payload_sha256": document["receipt_payload_sha256"],
                "status": "WROTE_PROBE_RECEIPT",
            }
        else:
            assert args.evidence_head is not None
            report = validate_committed_evidence(
                repository, evidence_head=args.evidence_head
            )
        print(json.dumps(report, sort_keys=True))
        return 0
    except (OSError, ProbeEvidenceError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL_CLOSED"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
