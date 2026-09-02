"""Fail closed before a branch-local grader-smoke trigger reaches its environment.

The sentinel is deliberately *not* an execution approval.  It creates one
GitHub run on the frozen TriMem branch so that a later external approval can be
bound to that run ID and attempt.  The only accepted push is one non-merge
commit that adds the fixed sentinel for the first time and changes nothing
else.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from trimem_grader_smoke_protocol import (
    MATRIX_KIND as EXPECTED_MATRIX_KIND,
    NOOP_BASELINE_LOCK,
    NOOP_BASELINE_PATCH,
    NOOP_BASELINE_PATCH_SHA256,
    SmokeProtocolError,
    validate_serial_targets,
)
from trimem_multi_swe_probe_evidence import (
    PROBE_REQUEST_PATH,
    PROBE_RECEIPT_PATH,
    PROBE_RESULT_PATH,
    ProbeEvidenceError,
    validate_committed_evidence,
)


EXPECTED_EVENT = "push"
EXPECTED_REF = "refs/heads/codex/trimem-coder-v1"
HISTORICAL_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST.json"
)
HISTORICAL_SENTINEL_SHA256 = (
    "03207843e241bef409d64d0181596f4cec4c83fe157dfc22670d429bc14f91f0"
)
HISTORICAL_SENTINEL_002_PATH = (
    "artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST_002.json"
)
HISTORICAL_SENTINEL_002_SHA256 = (
    "258900694f1584fcb0f04cde485c33ad4f4d4691154f5dfe598883ecdb03f48c"
)
HISTORICAL_SENTINEL_003_PATH = (
    "artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST_003.json"
)
HISTORICAL_SENTINEL_003_SHA256 = (
    "90bae24a2fba5e9ed88882fb06a47c8bb0113e1ffe6c2c121db990934bad0603"
)
HISTORICAL_SENTINELS = (
    (HISTORICAL_SENTINEL_PATH, HISTORICAL_SENTINEL_SHA256),
    (HISTORICAL_SENTINEL_002_PATH, HISTORICAL_SENTINEL_002_SHA256),
    (HISTORICAL_SENTINEL_003_PATH, HISTORICAL_SENTINEL_003_SHA256),
)
SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST_004.json"
)
FROZEN_REQUEST_PATH = "configs/trimem_v1/benchmark_exec_request.json"
WORKFLOW_PATH = ".github/workflows/trimem-grader-smoke.yml"
FREEZE_PATH = "artifacts/trimem_v1/freeze.json"
MANIFEST_PATH = "configs/trimem_v1/grader_smoke_manifest.json"
IMAGE_LOCK_PATH = "artifacts/trimem_v1/grader_image_lock.json"
CREDENTIAL_FREE_BUNDLE_PATH = (
    "artifacts/trimem_v1/credential_free_e2e/credential_free_e2e_bundle.json"
)
PREFLIGHT_PATH = "scripts/trimem_grader_smoke_trigger_preflight.py"
INVENTORY_PATH = "scripts/trimem_evidence_inventory.py"
PROTOCOL_PATH = "scripts/trimem_grader_smoke_protocol.py"
OFFICIAL_GRADER_PATH = "scripts/trimem_official_grader.py"
MULTI_SWE_ENTRYPOINT_PATH = "scripts/trimem_multi_swe_entrypoint.py"
MULTI_SWE_PROBE_EVIDENCE_PATH = "scripts/trimem_multi_swe_probe_evidence.py"
MULTI_SWE_EVALUATION_CONTRACT_LOCK_PATH = (
    "artifacts/trimem_v1/multi_swe_evaluation_contract_lock.json"
)
REQUEST_ID = "TRIMEM_V1_GRADER_SMOKE_EXEC_004"
REQUEST_SCHEMA = "trimem/grader-smoke-branch-trigger/1.5"
EXPECTED_PHASE = "GRADER_SMOKE"
AUTHORIZATION_SEMANTICS = "The sentinel alone does not authorize execution."
BASELINE_FROZEN_REQUEST_SHA256 = (
    "05e19aeec6630f2362c481a86eb66d0e630041794866a638c3ebbf07e5ccbba4"
)
BASELINE_SCIENTIFIC_MANIFEST_PROJECTION_SHA256 = (
    "d9882fbf694c1fba6cfab5953360b3264b284b2dee685c07a73e0c55ec5aa088"
)
BASELINE_TARGET_SET_SHA256 = (
    "01f9e41f1ce3f285c651c3bc857a1f7422ed7e0f9ccfb451b42aedf9a4aef52e"
)
BASELINE_IMAGE_LOCK_SHA256 = (
    "12a90bcc8e9bf46a9e65ed7e606aeee44b9c50b68c311a01180dc5080e41adeb"
)
BASELINE_CREDENTIAL_FREE_BUNDLE_SHA256 = (
    "e03e96f26b56fffb2e911504b526b6986a9148b4db620aa9b58bb5e100083e4c"
)
BASELINE_PROTOCOL_SHA256 = (
    "f73d7da715b3cc6a2d15e3bc39c355cfeccf585ab2014a1834c9b275839fc7b8"
)
EXECUTION_CONTROL_AMENDMENT = {
    "benchmark_result_existed_when_amended": False,
    "classification": "NON_SEMANTIC_EXECUTION_CONTROL_FIX",
    "previous_failed_run": {
        "head": "71edef406f0bc5202244ae1ad4f84419662e7126",
        "run_attempt": 1,
        "run_id": 33470431940,
        "scientific_or_evaluator_execution": False,
    },
    "reason": (
        "GitHub Actions push-event payload contract correction; "
        "no benchmark result existed when amended."
    ),
    "scientific_inputs_changed": False,
}
MULTI_SWE_PREBUILT_EVALUATION_CONTRACT_AMENDMENT = {
    "classification": "NON_SEMANTIC_MULTI_SWE_PREBUILT_EVALUATION_CONTRACT_FIX",
    "completed_cells_authoritative": False,
    "completed_cells_diagnostic_only": 4,
    "previous_failed_run": {
        "head": "a0f8cf2bbc3e13690c583b86054aaae562dfe3fd",
        "run_attempt": 1,
        "run_id": 33594270929,
        "scientific_or_evaluator_execution": True,
    },
    "reason": (
        "Correct the Multi-SWE digest-pinned prebuilt-image evaluation mode "
        "and submitted-patch mount contract; the four completed SWE-bench "
        "cells from the interrupted mixed-adapter campaign remain diagnostic only."
    ),
    "scientific_inputs_changed": False,
}
EXPECTED_UNIQUE_INSTANCES = 6
EXPECTED_MATRIX_ROWS = 12
HARD_CAPS = {
    "api_calls": 0,
    "grader_containers": 12,
    "grader_executions": 12,
    "input_tokens": 0,
    "model_calls": 0,
    "output_tokens": 0,
    "paid_model_calls": 0,
    "task_arm_runs": 0,
    "total_usd": 0.0,
}
REQUEST_FIELDS = frozenset(
    {
        "actual_execution_authorized",
        "adapter_sha256",
        "authorization_semantics",
        "branch_ref",
        "credential_free_bundle_sha256",
        "freeze_sha256",
        "frozen_request_sha256",
        "frozen_request_path",
        "grader_image_lock_sha256",
        "grader_smoke_manifest_sha256",
        "hard_caps",
        "matrix_kind",
        "matrix_order",
        "matrix_rows",
        "model_secret_required",
        "multi_swe_entrypoint_sha256",
        "multi_swe_evaluation_contract_lock_sha256",
        "multi_swe_probe_evidence",
        "multi_swe_probe_evidence_verifier_sha256",
        "noop_baseline_patch_sha256",
        "phase",
        "request_id",
        "request_path",
        "request_sha256",
        "requires_external_approval",
        "schema",
        "source_head",
        "target_set_sha256",
        "unique_instances",
        "workflow_path",
    }
)
ALLOWED_WORKFLOW_SECRETS = frozenset(
    {"TRIMEM_EVIDENCE_PASSPHRASE", "TRIMEM_EXEC_APPROVAL_B64"}
)
FORBIDDEN_EXECUTION_SECRETS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "GOOGLE_API_KEY",
        "MODEL_API_KEY",
        "OPENAI_API_KEY",
        "RUN_APPROVED",
        "UPSTAGE_API_KEY",
    }
)
HEX40 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


class TriggerPreflightError(ValueError):
    """The branch-local trigger did not match the frozen one-time contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TriggerPreflightError(message)


def _reject_constant(value: str) -> None:
    raise TriggerPreflightError(f"non-finite JSON number is forbidden: {value}")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise TriggerPreflightError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def strict_json_object(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TriggerPreflightError("trigger request is not strict UTF-8 JSON") from exc
    _require(isinstance(value, dict), "trigger request must be a JSON object")
    return value


def canonical_bytes(value: Any, *, trailing_lf: bool = False) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TriggerPreflightError("trigger request is not canonical JSON") from exc
    return encoded + (b"\n" if trailing_lf else b"")


def sha256_prefixed(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _run_git(repository: Path, *args: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=repository,
        capture_output=True,
        text=text,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
        raise TriggerPreflightError(
            "git verification failed: %s" % stderr.strip()
        )
    return result.stdout


def _commit_bytes(repository: Path, commit: str, path: str) -> bytes:
    value = _run_git(repository, "show", f"{commit}:{path}", text=False)
    assert isinstance(value, bytes)
    return value


def _strict_artifact(raw: bytes, path: str) -> dict[str, Any]:
    try:
        return strict_json_object(raw)
    except TriggerPreflightError as exc:
        raise TriggerPreflightError(f"invalid committed JSON at {path}: {exc}") from exc


def _raw_material(repository: Path, commit: str) -> dict[str, bytes]:
    paths = (
        *(path for path, _ in HISTORICAL_SENTINELS),
        FROZEN_REQUEST_PATH,
        FREEZE_PATH,
        MANIFEST_PATH,
        IMAGE_LOCK_PATH,
        CREDENTIAL_FREE_BUNDLE_PATH,
        OFFICIAL_GRADER_PATH,
        MULTI_SWE_ENTRYPOINT_PATH,
        MULTI_SWE_PROBE_EVIDENCE_PATH,
        MULTI_SWE_EVALUATION_CONTRACT_LOCK_PATH,
    )
    return {path: _commit_bytes(repository, commit, path) for path in paths}


def _validate_frozen_material(
    repository: Path, commit: str
) -> tuple[dict[str, bytes], dict[str, Any], list[str]]:
    """Validate and return every committed byte string bound by the sentinel."""

    raw = _raw_material(repository, commit)
    for path, expected_sha256 in HISTORICAL_SENTINELS:
        _require(
            hashlib.sha256(raw[path]).hexdigest() == expected_sha256,
            f"historical failed-trigger sentinel bytes changed: {path}",
        )
    for path, expected_sha256, label in (
        (
            FROZEN_REQUEST_PATH,
            BASELINE_FROZEN_REQUEST_SHA256,
            "frozen benchmark request",
        ),
        (IMAGE_LOCK_PATH, BASELINE_IMAGE_LOCK_SHA256, "grader image lock"),
        (
            CREDENTIAL_FREE_BUNDLE_PATH,
            BASELINE_CREDENTIAL_FREE_BUNDLE_SHA256,
            "credential-free bundle",
        ),
    ):
        _require(
            hashlib.sha256(raw[path]).hexdigest() == expected_sha256,
            f"P0.1.1 changed the {label} bytes",
        )
    _require(
        hashlib.sha256(_commit_bytes(repository, commit, PROTOCOL_PATH)).hexdigest()
        == BASELINE_PROTOCOL_SHA256,
        "P0.1.1 changed the frozen GOLD/NOOP protocol bytes",
    )
    frozen_request = _strict_artifact(raw[FROZEN_REQUEST_PATH], FROZEN_REQUEST_PATH)
    _require(
        frozen_request.get("schema") == "trimem/benchmark-exec-request/1.1",
        "frozen benchmark request schema mismatch",
    )
    _require(
        frozen_request.get("approval_state") == "PENDING_EXEC_APPROVAL",
        "frozen benchmark request is not pending external approval",
    )
    phases = {
        row.get("phase"): row
        for row in frozen_request.get("phases", ())
        if isinstance(row, dict)
    }
    _require(
        phases.get(EXPECTED_PHASE)
        == {
            "phase": EXPECTED_PHASE,
            "status": "PENDING_EXEC_APPROVAL",
            "workflow": WORKFLOW_PATH,
        },
        "frozen benchmark request has no exact pending grader-smoke phase",
    )

    freeze = _strict_artifact(raw[FREEZE_PATH], FREEZE_PATH)
    _require(freeze.get("schema") == "trimem/freeze/1.0", "freeze schema mismatch")
    freeze_files = freeze.get("files")
    _require(isinstance(freeze_files, dict), "freeze file inventory is missing")
    closure_paths = (
        *(path for path, _ in HISTORICAL_SENTINELS),
        WORKFLOW_PATH,
        FROZEN_REQUEST_PATH,
        MANIFEST_PATH,
        IMAGE_LOCK_PATH,
        CREDENTIAL_FREE_BUNDLE_PATH,
        OFFICIAL_GRADER_PATH,
        MULTI_SWE_ENTRYPOINT_PATH,
        MULTI_SWE_PROBE_EVIDENCE_PATH,
        MULTI_SWE_EVALUATION_CONTRACT_LOCK_PATH,
        PREFLIGHT_PATH,
        INVENTORY_PATH,
        PROTOCOL_PATH,
    )
    for path in closure_paths:
        committed = _commit_bytes(repository, commit, path)
        expected_entry = {
            "bytes": len(committed),
            "sha256": hashlib.sha256(committed).hexdigest(),
        }
        _require(
            freeze_files.get(path) == expected_entry,
            f"freeze closure mismatch for {path}",
        )

    manifest = _strict_artifact(raw[MANIFEST_PATH], MANIFEST_PATH)
    _require(
        manifest.get("schema") == "trimem/grader-smoke-manifest/1.0",
        "grader-smoke manifest schema mismatch",
    )
    amendment = manifest.get("execution_control_amendment")
    _require(
        amendment == EXECUTION_CONTROL_AMENDMENT,
        "P0.1.1 execution-control amendment is not exact",
    )
    _require(
        manifest.get("multi_swe_prebuilt_evaluation_contract_amendment")
        == MULTI_SWE_PREBUILT_EVALUATION_CONTRACT_AMENDMENT,
        "P0.1.4 Multi-SWE prebuilt-evaluation amendment is not exact",
    )
    _require(
        manifest.get("status") == "FROZEN_TARGET_SET_EXECUTION_PENDING"
        and manifest.get("execution_status") == "PENDING_EXEC_APPROVAL",
        "grader-smoke manifest is not frozen and pending approval",
    )
    _require(
        manifest.get("matrix_kind") == EXPECTED_MATRIX_KIND,
        "grader-smoke matrix kind mismatch",
    )
    _require(
        manifest.get("noop_baseline") == NOOP_BASELINE_LOCK,
        "grader-smoke NOOP_BASELINE patch lock mismatch",
    )
    selection = manifest.get("selection")
    _require(isinstance(selection, dict), "grader-smoke selection metadata is missing")
    _require(
        selection.get("frozen_before_results") is True
        and selection.get("selected_instances") == EXPECTED_UNIQUE_INSTANCES
        and selection.get("target_count") == EXPECTED_MATRIX_ROWS,
        "grader-smoke selection counts or freeze state mismatch",
    )
    targets = manifest.get("targets")
    _require(
        isinstance(targets, list) and len(targets) == EXPECTED_MATRIX_ROWS,
        "grader-smoke matrix must contain exactly 12 rows",
    )
    try:
        validate_serial_targets(
            matrix_kind=manifest.get("matrix_kind"),
            noop_baseline=manifest.get("noop_baseline"),
            targets=targets,
        )
    except SmokeProtocolError as exc:
        raise TriggerPreflightError(str(exc)) from exc
    target_digest = hashlib.sha256(canonical_bytes(targets)).hexdigest()
    _require(
        manifest.get("target_set_sha256")
        == target_digest
        == BASELINE_TARGET_SET_SHA256,
        "grader-smoke canonical target-set hash mismatch",
    )
    scientific_projection = {
        field: manifest[field]
        for field in (
            "matrix_kind",
            "noop_baseline",
            "selection",
            "target_set_sha256",
            "targets",
        )
    }
    _require(
        hashlib.sha256(canonical_bytes(scientific_projection)).hexdigest()
        == BASELINE_SCIENTIFIC_MANIFEST_PROJECTION_SHA256,
        "P0.1.1 changed the frozen grader-smoke scientific projection",
    )
    matrix_order: list[str] = []
    identities: list[tuple[str, str]] = []
    for index, target in enumerate(targets):
        _require(isinstance(target, dict), f"grader-smoke target {index} is not an object")
        target_id = target.get("target_id")
        benchmark_id = target.get("benchmark_id")
        instance_id = target.get("instance_id")
        probe = target.get("probe")
        _require(
            isinstance(target_id, str)
            and target_id
            and isinstance(benchmark_id, str)
            and benchmark_id
            and isinstance(instance_id, str)
            and instance_id,
            f"grader-smoke target {index} identity is malformed",
        )
        expected_probe = "GOLD" if index % 2 == 0 else "NOOP_BASELINE"
        _require(probe == expected_probe, f"grader-smoke target {index} probe order mismatch")
        _require(
            target.get("order_index") == index,
            f"grader-smoke target {index} order_index mismatch",
        )
        _require(
            target.get("expected_resolved") is (probe == "GOLD"),
            f"grader-smoke target {index} expected result mismatch",
        )
        matrix_order.append(target_id)
        identities.append((benchmark_id, instance_id))
    _require(
        len(set(matrix_order)) == EXPECTED_MATRIX_ROWS,
        "grader-smoke target IDs are not unique",
    )
    _require(
        len(set(identities)) == EXPECTED_UNIQUE_INSTANCES,
        "grader-smoke unique instance count mismatch",
    )
    for index in range(0, EXPECTED_MATRIX_ROWS, 2):
        _require(
            identities[index] == identities[index + 1],
            f"grader-smoke GOLD/NOOP_BASELINE pair mismatch at rows {index}/{index + 1}",
        )
    expected_target_ids = {
        identities[index]: [matrix_order[index], matrix_order[index + 1]]
        for index in range(0, EXPECTED_MATRIX_ROWS, 2)
    }

    image_lock = _strict_artifact(raw[IMAGE_LOCK_PATH], IMAGE_LOCK_PATH)
    _require(
        image_lock.get("schema") == "trimem/grader-image-lock/1.2"
        and image_lock.get("status") == "FROZEN"
        and image_lock.get("smoke_status") == "FROZEN"
        and image_lock.get("official_grader_execution") == "PENDING_EXEC_APPROVAL",
        "grader image lock is not the frozen pre-EXEC lock",
    )
    locked_targets = image_lock.get("targets")
    _require(isinstance(locked_targets, list), "grader image-lock smoke targets are missing")
    locked_identities: set[tuple[str, str]] = set()
    for row in locked_targets:
        _require(isinstance(row, dict), "grader image-lock target is malformed")
        benchmark_id = row.get("benchmark_id")
        instance_id = row.get("instance_id")
        _require(
            isinstance(benchmark_id, str)
            and benchmark_id
            and isinstance(instance_id, str)
            and instance_id,
            "grader image-lock target identity is malformed",
        )
        target_ids = row.get("target_ids")
        _require(
            isinstance(target_ids, list)
            and target_ids == expected_target_ids.get((benchmark_id, instance_id)),
            "grader image-lock target IDs differ from the manifest pair",
        )
        locked_identities.add((benchmark_id, instance_id))
    _require(
        len(locked_targets) == EXPECTED_UNIQUE_INSTANCES
        and locked_identities == set(identities),
        "grader image lock does not cover the exact smoke instance set",
    )

    bundle = _strict_artifact(raw[CREDENTIAL_FREE_BUNDLE_PATH], CREDENTIAL_FREE_BUNDLE_PATH)
    _require(
        bundle.get("schema") == "trimem/credential-free-e2e/1.0"
        and bundle.get("status") == "PASS"
        and bundle.get("official_grader_execution") is False
        and bundle.get("paid_model_calls") == 0,
        "credential-free bundle is not an exact zero-paid pre-EXEC PASS",
    )
    return raw, manifest, matrix_order


def _resolve_probe_evidence_head(repository: Path, *, source_head: str) -> str:
    """Resolve one immutable probe-evidence introduction on full Git history."""

    _require(
        HEX40.fullmatch(source_head) is not None,
        "source_head is not a commit SHA",
    )
    shallow = str(
        _run_git(repository, "rev-parse", "--is-shallow-repository")
    ).strip()
    _require(
        shallow == "false",
        "probe evidence resolution requires complete Git history",
    )
    introduction_heads: list[str] = []
    for path in (PROBE_RESULT_PATH, PROBE_RECEIPT_PATH):
        introductions = str(
            _run_git(
                repository,
                "log",
                "--format=%H",
                "--diff-filter=A",
                source_head,
                "--",
                path,
            )
        ).splitlines()
        _require(
            len(introductions) == 1
            and HEX40.fullmatch(introductions[0]) is not None,
            f"probe evidence path must have one introduction commit: {path}",
        )
        introduction_heads.append(introductions[0])
    _require(
        introduction_heads[0] == introduction_heads[1],
        "probe result and receipt were introduced by different commits",
    )
    evidence_head = introduction_heads[0]
    later_touches = str(
        _run_git(
            repository,
            "log",
            "--format=%H",
            f"{evidence_head}..{source_head}",
            "--",
            PROBE_REQUEST_PATH,
            PROBE_RESULT_PATH,
            PROBE_RECEIPT_PATH,
        )
    ).splitlines()
    _require(
        not later_touches,
        "probe request, result, or receipt was touched after the evidence commit",
    )
    return evidence_head


def build_request_document(
    repository: Path, *, source_head: str, commit: str | None = None
) -> dict[str, Any]:
    """Return the sole sentinel for a source with closed ancestor probe evidence."""

    _require(HEX40.fullmatch(source_head) is not None, "source_head is not a commit SHA")
    material_commit = source_head if commit is None else commit
    _require(
        HEX40.fullmatch(material_commit) is not None,
        "material commit is not a commit SHA",
    )
    raw, manifest, matrix_order = _validate_frozen_material(
        repository, material_commit
    )
    try:
        evidence_head = _resolve_probe_evidence_head(
            repository, source_head=source_head
        )
        probe_evidence = validate_committed_evidence(
            repository, evidence_head=evidence_head
        )
    except (ProbeEvidenceError, TriggerPreflightError) as exc:
        raise TriggerPreflightError(
            f"Multi-SWE image-probe evidence is not closed: {exc}"
        ) from exc
    payload: dict[str, Any] = {
        "actual_execution_authorized": False,
        "adapter_sha256": sha256_prefixed(raw[OFFICIAL_GRADER_PATH]),
        "authorization_semantics": AUTHORIZATION_SEMANTICS,
        "branch_ref": EXPECTED_REF,
        "credential_free_bundle_sha256": sha256_prefixed(
            raw[CREDENTIAL_FREE_BUNDLE_PATH]
        ),
        "freeze_sha256": sha256_prefixed(raw[FREEZE_PATH]),
        "frozen_request_path": FROZEN_REQUEST_PATH,
        "frozen_request_sha256": sha256_prefixed(raw[FROZEN_REQUEST_PATH]),
        "grader_image_lock_sha256": sha256_prefixed(raw[IMAGE_LOCK_PATH]),
        "grader_smoke_manifest_sha256": sha256_prefixed(raw[MANIFEST_PATH]),
        "hard_caps": dict(HARD_CAPS),
        "matrix_kind": EXPECTED_MATRIX_KIND,
        "matrix_order": matrix_order,
        "matrix_rows": EXPECTED_MATRIX_ROWS,
        "model_secret_required": False,
        "multi_swe_entrypoint_sha256": sha256_prefixed(
            raw[MULTI_SWE_ENTRYPOINT_PATH]
        ),
        "multi_swe_evaluation_contract_lock_sha256": sha256_prefixed(
            raw[MULTI_SWE_EVALUATION_CONTRACT_LOCK_PATH]
        ),
        "multi_swe_probe_evidence": probe_evidence,
        "multi_swe_probe_evidence_verifier_sha256": sha256_prefixed(
            raw[MULTI_SWE_PROBE_EVIDENCE_PATH]
        ),
        "noop_baseline_patch_sha256": NOOP_BASELINE_PATCH_SHA256,
        "phase": EXPECTED_PHASE,
        "request_id": REQUEST_ID,
        "request_path": SENTINEL_PATH,
        "requires_external_approval": True,
        "schema": REQUEST_SCHEMA,
        "source_head": source_head,
        "target_set_sha256": manifest["target_set_sha256"],
        "unique_instances": EXPECTED_UNIQUE_INSTANCES,
        "workflow_path": WORKFLOW_PATH,
    }
    return {
        **payload,
        "request_sha256": sha256_prefixed(canonical_bytes(payload)),
    }


def _validate_event_shape(event: Mapping[str, Any], environ: Mapping[str, str]) -> tuple[str, str]:
    _require(environ.get("GITHUB_EVENT_NAME") == EXPECTED_EVENT, "event is not push")
    _require(
        environ.get("GITHUB_RUN_ATTEMPT") == "1",
        "one-time recovery trigger forbids a rerun attempt",
    )
    _require(environ.get("GITHUB_REF") == EXPECTED_REF, "GITHUB_REF is not the frozen branch")
    _require(event.get("ref") == EXPECTED_REF, "push ref is not the frozen branch")
    _require(event.get("deleted") is False, "branch-deletion pushes are forbidden")
    _require(event.get("forced") is False, "forced pushes are forbidden")
    before, after = event.get("before"), event.get("after")
    _require(isinstance(before, str) and HEX40.fullmatch(before) is not None, "push before SHA is invalid")
    _require(isinstance(after, str) and HEX40.fullmatch(after) is not None, "push after SHA is invalid")
    _require(environ.get("GITHUB_SHA") == after, "GITHUB_SHA differs from push after SHA")
    _require(before != after, "push before and after SHAs must differ")
    return before, after


def _validate_one_time_commit(repository: Path, before: str, after: str) -> bytes:
    top = str(_run_git(repository, "rev-parse", "--show-toplevel")).strip()
    _require(Path(top).resolve() == repository.resolve(), "repository path is not the git top level")
    head = str(_run_git(repository, "rev-parse", "HEAD")).strip()
    _require(head == after, "checked-out HEAD differs from trigger commit")
    parents = str(_run_git(repository, "rev-list", "--parents", "-n", "1", after)).strip().split()
    _require(parents == [after, before], "trigger must be one non-merge commit on push before")
    changes = str(
        _run_git(
            repository,
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "--no-renames",
            after,
        )
    ).splitlines()
    _require(changes == [f"A\t{SENTINEL_PATH}"], "trigger commit must add exactly the sentinel path")
    history = str(
        _run_git(repository, "log", "--format=%H", before, "--", SENTINEL_PATH)
    ).strip()
    _require(not history, "sentinel path already exists in branch history")
    tree = str(_run_git(repository, "ls-tree", after, "--", SENTINEL_PATH)).strip()
    _require(
        re.fullmatch(rf"100644 blob [0-9a-f]{{40}}\t{re.escape(SENTINEL_PATH)}", tree)
        is not None,
        "sentinel must be one regular non-executable git blob",
    )
    return _commit_bytes(repository, after, SENTINEL_PATH)


def _validate_no_model_secret(
    repository: Path, after: str, environ: Mapping[str, str]
) -> None:
    exposed = sorted(name for name in FORBIDDEN_EXECUTION_SECRETS if name in environ)
    _require(not exposed, f"forbidden execution secret is exposed to preflight: {exposed}")
    workflow = _commit_bytes(repository, after, WORKFLOW_PATH).decode("utf-8")
    referenced = set(re.findall(r"\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)", workflow))
    unexpected = sorted(referenced - ALLOWED_WORKFLOW_SECRETS)
    _require(not unexpected, f"grader-smoke workflow references a non-control secret: {unexpected}")
    forbidden_names = sorted(
        name for name in FORBIDDEN_EXECUTION_SECRETS if name in workflow
    )
    _require(
        not forbidden_names,
        f"grader-smoke workflow contains a forbidden secret name: {forbidden_names}",
    )


def validate_request_document(
    repository: Path,
    raw: bytes,
    *,
    expected_source_head: str,
    material_commit: str | None = None,
) -> dict[str, Any]:
    """Validate all sentinel bytes without depending on a GitHub event payload.

    Execution gates use this same validator at the trigger commit.  Push
    preflight additionally proves that ``expected_source_head`` is the sole
    parent and that the trigger commit added only the sentinel.
    """

    repository = repository.resolve(strict=True)
    _require(
        HEX40.fullmatch(expected_source_head) is not None,
        "expected source_head is not a commit SHA",
    )
    if material_commit is None:
        material_commit = str(_run_git(repository, "rev-parse", "HEAD")).strip()
    _require(
        HEX40.fullmatch(material_commit) is not None,
        "material commit is not a commit SHA",
    )
    value = strict_json_object(raw)
    _require(set(value) == REQUEST_FIELDS, "trigger request field set is not exact")
    _require(value.get("schema") == REQUEST_SCHEMA, "trigger request schema mismatch")
    _require(value.get("request_id") == REQUEST_ID, "trigger request identity mismatch")
    _require(value.get("request_path") == SENTINEL_PATH, "trigger request path mismatch")
    _require(
        value.get("frozen_request_path") == FROZEN_REQUEST_PATH,
        "frozen benchmark request path mismatch",
    )
    _require(value.get("phase") == EXPECTED_PHASE, "trigger request phase is not GRADER_SMOKE")
    _require(value.get("branch_ref") == EXPECTED_REF, "trigger request branch mismatch")
    _require(value.get("workflow_path") == WORKFLOW_PATH, "trigger workflow path mismatch")
    _require(
        value.get("source_head") == expected_source_head,
        "trigger source_head differs from expected probe-evidence HEAD",
    )
    _require(
        value.get("requires_external_approval") is True,
        "sentinel must require external approval",
    )
    _require(
        value.get("actual_execution_authorized") is False,
        "sentinel alone must not authorize execution",
    )
    _require(
        value.get("authorization_semantics") == AUTHORIZATION_SEMANTICS,
        "sentinel authorization semantics mismatch",
    )
    _require(value.get("model_secret_required") is False, "sentinel must not require a model secret")
    caps = value.get("hard_caps")
    _require(
        isinstance(caps, dict) and set(caps) == set(HARD_CAPS),
        "grader-smoke hard-cap field set is not exact",
    )
    for field in (
        "api_calls",
        "input_tokens",
        "model_calls",
        "output_tokens",
        "paid_model_calls",
    ):
        _require(type(caps.get(field)) is int and caps[field] == 0, f"{field} must be integer zero")
    _require(
        type(caps.get("task_arm_runs")) is int and caps["task_arm_runs"] == 0,
        "task_arm_runs must be integer zero",
    )
    _require(
        type(caps.get("grader_containers")) is int
        and caps["grader_containers"] == EXPECTED_MATRIX_ROWS,
        "grader_containers must equal the 12-row smoke matrix",
    )
    _require(
        type(caps.get("grader_executions")) is int
        and caps["grader_executions"] == EXPECTED_MATRIX_ROWS,
        "grader_executions must equal the 12-row smoke matrix",
    )
    _require(type(caps.get("total_usd")) is float and caps["total_usd"] == 0.0, "total_usd must be float zero")
    expected = build_request_document(
        repository,
        source_head=expected_source_head,
        commit=material_commit,
    )
    for field, label in (
        ("frozen_request_sha256", "frozen request hash"),
        ("freeze_sha256", "freeze hash"),
        ("grader_smoke_manifest_sha256", "grader-smoke manifest raw hash"),
        ("target_set_sha256", "grader-smoke target-set hash"),
        ("noop_baseline_patch_sha256", "NOOP_BASELINE patch hash"),
        ("grader_image_lock_sha256", "grader image-lock raw hash"),
        ("credential_free_bundle_sha256", "credential-free bundle raw hash"),
        ("adapter_sha256", "official grader adapter raw hash"),
        ("multi_swe_entrypoint_sha256", "Multi-SWE entrypoint raw hash"),
        (
            "multi_swe_evaluation_contract_lock_sha256",
            "Multi-SWE evaluation contract-lock raw hash",
        ),
        ("multi_swe_probe_evidence", "Multi-SWE image-probe evidence binding"),
        (
            "multi_swe_probe_evidence_verifier_sha256",
            "Multi-SWE image-probe evidence verifier raw hash",
        ),
        ("matrix_kind", "grader-smoke matrix kind"),
        ("matrix_order", "grader-smoke matrix order"),
        ("unique_instances", "grader-smoke unique instance count"),
        ("matrix_rows", "grader-smoke matrix row count"),
    ):
        _require(value.get(field) == expected[field], f"{label} mismatch")
    _require(isinstance(value.get("request_sha256"), str) and SHA256.fullmatch(value["request_sha256"]) is not None, "trigger request hash is invalid")
    _require(value.get("request_sha256") == expected["request_sha256"], "trigger request content hash mismatch")
    _require(value == expected, "trigger request content is not exact")
    _require(raw == canonical_bytes(value, trailing_lf=True), "trigger request bytes are not canonical LF JSON")
    return value


def _validate_request(
    repository: Path, *, before: str, after: str, raw: bytes
) -> dict[str, Any]:
    return validate_request_document(
        repository,
        raw,
        expected_source_head=before,
        material_commit=after,
    )


def validate_branch_trigger(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    repository = repository.resolve(strict=True)
    event_raw = event_path.resolve(strict=True).read_bytes()
    event = strict_json_object(event_raw)
    environment = os.environ if environ is None else environ
    before, after = _validate_event_shape(event, environment)
    request_raw = _validate_one_time_commit(repository, before, after)
    _validate_no_model_secret(repository, after, environment)
    request = _validate_request(
        repository,
        before=before,
        after=after,
        raw=request_raw,
    )
    return {
        "actual_execution_authorized": False,
        "freeze_sha256": request["freeze_sha256"],
        "grader_containers": EXPECTED_MATRIX_ROWS,
        "grader_executions": EXPECTED_MATRIX_ROWS,
        "api_calls": 0,
        "model_calls": 0,
        "paid_model_calls": 0,
        "phase": EXPECTED_PHASE,
        "request_id": REQUEST_ID,
        "request_sha256": request["request_sha256"],
        "requires_external_approval": True,
        "source_head": before,
        "multi_swe_probe_evidence": request["multi_swe_probe_evidence"],
        "status": "PASS",
        "trigger_commit": after,
    }


def write_request(repository: Path) -> dict[str, Any]:
    """Exclusively create the fixed sentinel from one clean correction HEAD."""

    repository = repository.resolve(strict=True)
    top = str(_run_git(repository, "rev-parse", "--show-toplevel")).strip()
    _require(Path(top).resolve() == repository, "repository path is not the git top level")
    ref = str(_run_git(repository, "symbolic-ref", "--quiet", "HEAD")).strip()
    _require(ref == EXPECTED_REF, "request may be written only on the frozen branch")
    head = str(_run_git(repository, "rev-parse", "HEAD")).strip()
    _require(HEX40.fullmatch(head) is not None, "repository HEAD is not an exact commit SHA")
    status = str(
        _run_git(
            repository,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        )
    )
    _require(not status, "request rendering requires a clean worktree")
    history = str(
        _run_git(repository, "log", "--format=%H", "HEAD", "--", SENTINEL_PATH)
    ).strip()
    _require(not history, "sentinel path already exists in branch history")
    target = repository / SENTINEL_PATH
    _require(not target.exists() and not target.is_symlink(), "sentinel path already exists")
    document = build_request_document(repository, source_head=head)
    raw = canonical_bytes(document, trailing_lf=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise TriggerPreflightError("refusing to overwrite the sentinel request") from exc
    return {
        "bytes": len(raw),
        "path": SENTINEL_PATH,
        "payload_sha256": document["request_sha256"],
        "request_id": REQUEST_ID,
        "sentinel_bytes_sha256": sha256_prefixed(raw),
        "source_head": head,
        "status": "WROTE_ZERO_AUTHORITY_SENTINEL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--event-path", type=Path)
    mode.add_argument("--write-request", action="store_true")
    args = parser.parse_args()
    try:
        if args.write_request:
            report = write_request(args.repository)
        else:
            assert args.event_path is not None
            report = validate_branch_trigger(args.repository, args.event_path)
    except (OSError, TriggerPreflightError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL_CLOSED"}, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
