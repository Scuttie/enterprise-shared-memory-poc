"""Fail-closed TriMem V1 readiness and external EXEC gate verifier.

``benchmark-approval`` is deliberately pre-EXEC: official smoke, development
selection/checkpoint and approvals remain pending. ``benchmark-exec`` is a
later phase gate and validates a protected approval outside the repository.
"""
from __future__ import annotations

import argparse
import ast
import base64
from collections import Counter
from datetime import datetime
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from enterprise_memory.trimem.agent_runtime import TriMemAgentRuntime  # noqa: E402
from enterprise_memory.trimem.benchmark_seed import seed_benchmark_identities  # noqa: E402
from enterprise_memory.trimem.git_workspace import DockerSandboxCommandRunner, GitCheckoutWorkspaceFactory  # noqa: E402
from enterprise_memory.trimem.arms import CurrentV03MemoryController  # noqa: E402
from enterprise_memory.trimem.postgres_retrieval import production_v03_controller_factory  # noqa: E402
from enterprise_memory.trimem.production_runtime import BenchmarkArmSession, open_benchmark_arm  # noqa: E402
from enterprise_memory.trimem.production_v03_lifecycle import (  # noqa: E402
    LIVE_V03_IMPLEMENTATION_HASH,
    LIVE_V03_IMPLEMENTATION_MANIFEST,
    LiveV03Runtime,
    PostgresV03ExperienceLifecycle,
    production_v03_lifecycle_factory,
)
from enterprise_memory.trimem.runtime_lock import RuntimeLock  # noqa: E402
from trimem_benchmark_run import (  # noqa: E402
    AtomicBudgetLedger, BudgetedModelGateway, JournaledGraderGateway,
    JournaledModelGateway, validate_exec_approval,
)
from trimem_freeze import (  # noqa: E402
    FROZEN_PATHS,
    OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH,
    OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH,
    OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
    OFFICIAL_SMOKE_PUBLIC_RESULT_PATH,
    check_freeze,
)
from trimem_grader_smoke_protocol import (  # noqa: E402
    NOOP_BASELINE_CONTENT,
    NOOP_BASELINE_LOCK,
    NOOP_BASELINE_PATH,
)
from trimem_grader_smoke_trigger_preflight import (  # noqa: E402
    BASELINE_CREDENTIAL_FREE_BUNDLE_SHA256,
    BASELINE_FROZEN_REQUEST_SHA256,
    BASELINE_IMAGE_LOCK_SHA256,
    BASELINE_PROTOCOL_SHA256,
    BASELINE_TARGET_SET_SHA256,
    CREDENTIAL_FREE_BUNDLE_PATH as GRADER_SMOKE_CREDENTIAL_BUNDLE_PATH,
    EXECUTION_CONTROL_AMENDMENT,
    FROZEN_REQUEST_PATH as GRADER_SMOKE_FROZEN_REQUEST_PATH,
    HISTORICAL_SENTINELS,
    IMAGE_LOCK_PATH as GRADER_SMOKE_IMAGE_LOCK_PATH,
    PROTOCOL_PATH as GRADER_SMOKE_PROTOCOL_PATH,
    REQUEST_ID as GRADER_SMOKE_REQUEST_ID,
    REQUEST_SCHEMA as GRADER_SMOKE_REQUEST_SCHEMA,
    SENTINEL_PATH as GRADER_SMOKE_SENTINEL_PATH,
    TriggerPreflightError,
    validate_request_document,
)
from trimem_harness_lock import (  # noqa: E402
    HASH_BASIS as HARNESS_DEPENDENCY_HASH_BASIS,
    validate_harness_lock_configuration,
)
from trimem_smoke_attestation import (  # noqa: E402
    EXPECTED_REPOSITORY as SMOKE_ATTESTATION_REPOSITORY,
    HOSTED_RUNNER as SMOKE_ATTESTATION_RUNNER,
    SCHEMA as SMOKE_ATTESTATION_SCHEMA,
    SIGNER_WORKFLOW_PATH as SMOKE_ATTESTATION_WORKFLOW,
    SOURCE_REF_BY_EVENT as SMOKE_ATTESTATION_SOURCE_REF_BY_EVENT,
)
from trimem_m2_candidates import CANDIDATE_IDS, load_bundle, validate_selected_m2  # noqa: E402
from trimem_verify_credential_free import verify_bundle  # noqa: E402


CONFIG = ROOT / "configs/trimem_v1"
ARTIFACT = ROOT / "artifacts/trimem_v1"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DIGEST_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")
POSITIVE_INTEGER = re.compile(r"^[1-9][0-9]*$")

SMOKE_RESULT_COMMON_FIELDS = {
    "schema", "status", "trimem_system_implementation", "grader_exec_package",
    "official_grader_viability", "performance", "expected_unique_instances",
    "expected_target_count", "expected_condition_rows", "actual_execution",
}
SMOKE_AGGREGATE_BODY_FIELDS = {
    "actual_accounting", "approval_binding", "digest_match_count",
    "empty_patch_ids", "evidence_counts", "expected_target_count",
    "image_lifecycle", "infrastructure_failure_count", "manifest",
    "observed_target_count", "outcomes", "patch_applied_count",
    "probe_counts", "resolved_counts", "status", "tests_executed_count",
    "unresolved_counts",
}
SMOKE_PUBLIC_ONLY_FIELDS = {
    "dataset_rows_or_gold_test_payloads", "restricted_evidence", "stream_totals",
    "verified_aggregate_sha256",
}
SMOKE_APPROVAL_FIELDS = {
    "approval_artifact_sha256", "approved_request_sha256",
    "approved_workflow_run_id", "approved_workflow_run_attempt", "freeze_sha256",
    "git_head", "phase",
}
SMOKE_EVIDENCE_FIELDS = {
    "public_result_path", "public_result_raw_sha256",
    "evidence_inventory_path", "evidence_inventory_raw_sha256",
    "verified_aggregate_sha256", "aggregate_raw_sha256", "approval_binding",
    "attestation_subject_path", "attestation_subject_raw_sha256",
    "attestation_bundle_path", "attestation_bundle_raw_sha256",
}
SMOKE_ATTESTATION_POLICY_PATH = "configs/trimem_v1/smoke_attestation_policy.json"
SMOKE_TRUSTED_ROOT_PATH = "configs/trimem_v1/sigstore_trusted_root.jsonl"
SMOKE_ATTESTATION_ACTION = (
    "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6"
)
SMOKE_PROTECTED_ENVIRONMENT_OID = "1.3.6.1.4.1.57264.1.23"
SMOKE_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
SMOKE_GH_VERSION_LINE = "gh version 2.97.0 (2026-07-31)"
SMOKE_GITHUB_API_ACCEPT = "application/vnd.github+json"
SMOKE_GITHUB_API_VERSION = "2022-11-28"
SMOKE_RUN_API_ROUTE_TEMPLATE = (
    "repos/{repository}/actions/runs/{run_id}/attempts/{run_attempt}"
)
SMOKE_RUN_API_JSON_PROJECTION = (
    "{id,run_attempt,event,status,conclusion,head_sha,head_branch,path,"
    "workflow_id,repository_full_name:.repository.full_name}"
)


def _smoke_cert_identity(source_ref: str) -> str:
    return (
        f"https://github.com/{SMOKE_ATTESTATION_REPOSITORY}/"
        f"{SMOKE_ATTESTATION_WORKFLOW}@{source_ref}"
    )


class ReadinessError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=strict_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"invalid UTF-8 JSON: {path.relative_to(ROOT).as_posix()}") from exc
    if not isinstance(value, dict):
        raise ReadinessError(f"JSON root is not an object: {path.relative_to(ROOT).as_posix()}")
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReadinessError(message)


def _pretty_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _strict_json_bytes(raw: bytes, *, label: str) -> dict[str, Any]:
    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReadinessError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=strict_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ReadinessError(f"non-finite JSON number in {label}: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"invalid UTF-8 JSON: {label}") from exc
    require(isinstance(value, dict), f"JSON root is not an object: {label}")
    return value


def _historical_git_file(commit: str, relative: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    require(
        completed.returncode == 0,
        f"official smoke execution commit lacks {relative}",
    )
    return completed.stdout


def _execution_head_is_ancestor(commit: str) -> bool:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


def _validate_historical_smoke_request(
    execution_head: str, raw: bytes
) -> dict[str, Any]:
    request = _strict_json_bytes(raw, label="historical grader-smoke request")
    source_head = request.get("source_head")
    require(
        isinstance(source_head, str) and HEX40.fullmatch(source_head) is not None,
        "historical grader-smoke request source_head is invalid",
    )
    try:
        return validate_request_document(
            ROOT,
            raw,
            expected_source_head=source_head,
            material_commit=execution_head,
        )
    except (OSError, TriggerPreflightError) as exc:
        raise ReadinessError(
            f"historical grader-smoke sentinel validation failed: {exc}"
        ) from None


def _inventory_rows(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    require(
        set(inventory)
        == {"schema", "root", "files", "total_bytes", "total_files", "inventory_sha256"},
        "official smoke evidence inventory field set differs",
    )
    files = inventory.get("files")
    require(isinstance(files, list) and bool(files), "official smoke evidence inventory is empty")
    rows: dict[str, dict[str, Any]] = {}
    for row in files:
        require(
            isinstance(row, dict)
            and set(row) == {"path", "sha256", "bytes"}
            and isinstance(row.get("path"), str)
            and bool(row["path"])
            and not Path(row["path"]).is_absolute()
            and ".." not in Path(row["path"]).parts
            and isinstance(row.get("sha256"), str)
            and HEX64.fullmatch(row["sha256"]) is not None
            and type(row.get("bytes")) is int
            and row["bytes"] >= 0,
            "official smoke evidence inventory row is malformed",
        )
        require(row["path"] not in rows, "official smoke evidence inventory has duplicate paths")
        rows[row["path"]] = row
    require(
        list(rows) == sorted(rows),
        "official smoke evidence inventory path order differs",
    )
    payload = {
        "files": files,
        "root": inventory.get("root"),
        "schema": inventory.get("schema"),
        "total_bytes": inventory.get("total_bytes"),
        "total_files": inventory.get("total_files"),
    }
    require(
        inventory.get("schema") == "trimem/restricted-evidence-inventory/1.0"
        and inventory.get("root") == "grader_smoke_exec"
        and type(inventory.get("total_files")) is int
        and inventory["total_files"] == len(files)
        and type(inventory.get("total_bytes")) is int
        and inventory["total_bytes"] == sum(row["bytes"] for row in files)
        and inventory.get("inventory_sha256")
        == hashlib.sha256(canonical(payload)).hexdigest(),
        "official smoke evidence inventory seal/counts differ",
    )
    return rows


def _require_inventory_raw(
    rows: Mapping[str, Mapping[str, Any]], path: str, raw: bytes, *, label: str
) -> None:
    row = rows.get(path)
    require(
        isinstance(row, Mapping)
        and row.get("sha256") == hashlib.sha256(raw).hexdigest()
        and row.get("bytes") == len(raw),
        f"official smoke inventory {label} raw binding differs",
    )


def validate_smoke_attestation_policy() -> dict[str, Any]:
    """Validate the pre-execution trust root and verification policy bytes."""

    policy = read_json(ROOT / SMOKE_ATTESTATION_POLICY_PATH)
    require(
        set(policy)
        == {
            "attestation_action", "certificate_policy", "expected_repository",
            "schema", "signer_workflow", "source_ref_by_event", "trusted_root",
            "verification",
        },
        "smoke attestation policy field set differs",
    )
    require(
        policy.get("schema") == "trimem/smoke-attestation-policy/1.0"
        and policy.get("expected_repository") == SMOKE_ATTESTATION_REPOSITORY
        and policy.get("source_ref_by_event") == SMOKE_ATTESTATION_SOURCE_REF_BY_EVENT
        and policy.get("signer_workflow") == SMOKE_ATTESTATION_WORKFLOW
        and policy.get("attestation_action")
        == {
            "exact_uses": SMOKE_ATTESTATION_ACTION,
            "inputs": {
                "create-storage-record": False,
                "push-to-registry": False,
                "subject-path": "${{ runner.temp }}/attestation-subject.json",
            },
        },
        "smoke attestation identity/action policy differs",
    )
    certificate_policy = policy.get("certificate_policy")
    require(
        certificate_policy
        == {
            "oidc_issuer": SMOKE_OIDC_ISSUER,
            "protected_environment": "trimem-grader-smoke-exec",
            "protected_environment_oid": SMOKE_PROTECTED_ENVIRONMENT_OID,
            "runner_environment": SMOKE_ATTESTATION_RUNNER,
            "runner_invocation_uri_template": (
                "https://github.com/Scuttie/enterprise-shared-memory-poc/"
                "actions/runs/{run_id}/attempts/{run_attempt}"
            ),
        },
        "smoke attestation certificate policy differs",
    )
    verification = policy.get("verification")
    required_flags = [
        "--bundle", "--cert-identity", "--cert-oidc-issuer",
        "--custom-trusted-root", "--digest-alg=sha256",
        "--deny-self-hosted-runners", "--format=json",
        "--predicate-type=https://slsa.dev/provenance/v1", "--repo",
        "--signer-digest", "--source-digest", "--source-ref",
    ]
    require(
        isinstance(verification, dict)
        and set(verification)
        == {
            "cryptographic_gate_phases", "gh_cli_tcb", "live_run_attempt",
            "required_cli_flags", "static_scope", "trusted_root_mutation_after_smoke",
        }
        and verification.get("cryptographic_gate_phases")
        == ["DEVELOPMENT_TUNING", "HELDOUT_BENCHMARK"]
        and verification.get("gh_cli_tcb")
        == {
            "exact_version_first_line": SMOKE_GH_VERSION_LINE,
            "trust_boundary": (
                "trusted host/runner installation plus exact version; executable "
                "bytes are neither vendored nor byte-pinned"
            ),
        }
        and verification.get("live_run_attempt")
        == {
            "accept": SMOKE_GITHUB_API_ACCEPT,
            "api_version": SMOKE_GITHUB_API_VERSION,
            "api_route_template": SMOKE_RUN_API_ROUTE_TEMPLATE,
            "authentication": (
                "GH_TOKEN from github.token scoped to the benchmark EXEC gate step only"
            ),
            "exact_conclusion": "success",
            "exact_status": "completed",
            "json_projection": SMOKE_RUN_API_JSON_PROJECTION,
            "transport": "gh api --hostname github.com",
        }
        and verification.get("required_cli_flags") == required_flags
        and verification.get("trusted_root_mutation_after_smoke") == "PROHIBITED"
        and isinstance(verification.get("static_scope"), str)
        and "no cryptographic viability claim" in verification["static_scope"],
        "smoke attestation verification policy differs",
    )

    trusted = policy.get("trusted_root")
    trusted_path = ROOT / SMOKE_TRUSTED_ROOT_PATH
    trusted_raw = trusted_path.read_bytes()
    require(
        isinstance(trusted, dict)
        and set(trusted)
        == {
            "bytes", "generated_at_utc", "generated_by", "generator", "line_count",
            "path", "raw_sha256", "source",
        }
        and trusted.get("path") == SMOKE_TRUSTED_ROOT_PATH
        and trusted.get("generated_by") == "gh attestation trusted-root"
        and trusted.get("generator") == "gh version 2.97.0 (2026-07-31)"
        and trusted.get("source")
        == "https://cli.github.com/manual/gh_attestation_trusted-root"
        and trusted.get("bytes") == len(trusted_raw)
        and trusted.get("raw_sha256") == hashlib.sha256(trusted_raw).hexdigest()
        and trusted.get("line_count") == 2
        and isinstance(trusted.get("generated_at_utc"), str)
        and trusted["generated_at_utc"].endswith("Z"),
        "pre-frozen Sigstore trusted-root provenance/hash differs",
    )
    require(
        trusted_raw.endswith(b"\n") and b"\r" not in trusted_raw,
        "pre-frozen Sigstore trusted-root is not exact LF JSONL",
    )
    lines = trusted_raw.splitlines()
    require(len(lines) == 2 and all(lines), "Sigstore trusted-root line set differs")
    for index, raw in enumerate(lines):
        root = _strict_json_bytes(raw, label=f"{SMOKE_TRUSTED_ROOT_PATH}:{index + 1}")
        require(
            root.get("mediaType")
            == "application/vnd.dev.sigstore.trustedroot+json;version=0.1"
            and isinstance(root.get("certificateAuthorities"), list)
            and bool(root["certificateAuthorities"]),
            f"Sigstore trusted-root line {index + 1} is malformed",
        )
    return policy


def _decode_utf8_extension(raw: bytes, *, oid: str) -> str:
    """Decode Fulcio's DER UTF8String extension (legacy raw UTF-8 is rejected)."""

    require(len(raw) >= 2 and raw[0] == 0x0C, f"certificate OID {oid} is not DER UTF8String")
    first_length = raw[1]
    if first_length < 0x80:
        length, offset = first_length, 2
    elif first_length == 0x81:
        require(
            len(raw) >= 3 and raw[2] >= 0x80,
            f"certificate OID {oid} DER length is nonminimal",
        )
        length, offset = raw[2], 3
    elif first_length == 0x82:
        require(
            len(raw) >= 4 and raw[2] != 0,
            f"certificate OID {oid} DER length is nonminimal",
        )
        length = int.from_bytes(raw[2:4], "big")
        require(length >= 0x100, f"certificate OID {oid} DER length is nonminimal")
        offset = 4
    else:
        raise ReadinessError(f"certificate OID {oid} DER length form is invalid")
    require(
        offset + length == len(raw),
        f"certificate OID {oid} DER payload length differs",
    )
    try:
        return raw[offset:].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReadinessError(f"certificate OID {oid} is not UTF-8") from exc


def _bundle_statement(bundle: Mapping[str, Any]) -> dict[str, Any]:
    envelope = bundle.get("dsseEnvelope")
    require(
        isinstance(envelope, Mapping)
        and set(envelope) == {"payload", "payloadType", "signatures"}
        and envelope.get("payloadType") == "application/vnd.in-toto+json"
        and isinstance(envelope.get("signatures"), list)
        and len(envelope["signatures"]) == 1
        and isinstance(envelope["signatures"][0], Mapping)
        and isinstance(envelope["signatures"][0].get("sig"), str)
        and bool(envelope["signatures"][0]["sig"]),
        "official smoke attestation DSSE envelope differs",
    )
    try:
        payload = base64.b64decode(str(envelope.get("payload", "")), validate=True)
    except ValueError as exc:
        raise ReadinessError("official smoke attestation DSSE payload is invalid base64") from exc
    return _strict_json_bytes(payload, label="official smoke attestation DSSE statement")


def _bundle_certificate_bindings(bundle: Mapping[str, Any]) -> dict[str, str]:
    try:
        from cryptography import x509
        from cryptography.x509.oid import ExtensionOID, ObjectIdentifier
    except ImportError as exc:
        raise ReadinessError("cryptography is required to inspect the attestation certificate") from exc

    verification = bundle.get("verificationMaterial")
    require(isinstance(verification, Mapping), "attestation verification material is missing")
    certificate = verification.get("certificate")
    require(
        isinstance(certificate, Mapping)
        and set(certificate) == {"rawBytes"}
        and isinstance(certificate.get("rawBytes"), str),
        "attestation leaf certificate field set differs",
    )
    try:
        der = base64.b64decode(certificate["rawBytes"], validate=True)
        leaf = x509.load_der_x509_certificate(der)
    except (ValueError, TypeError) as exc:
        raise ReadinessError("attestation leaf certificate is invalid DER/base64") from exc
    try:
        names = leaf.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        ).value.get_values_for_type(x509.UniformResourceIdentifier)
    except x509.ExtensionNotFound as exc:
        raise ReadinessError("attestation certificate lacks URI SAN") from exc
    require(
        len(names) == 1 and isinstance(names[0], str) and bool(names[0]),
        "attestation certificate URI SAN cardinality differs",
    )

    oid_names = {
        "issuer": "1.3.6.1.4.1.57264.1.8",
        "buildSignerURI": "1.3.6.1.4.1.57264.1.9",
        "buildSignerDigest": "1.3.6.1.4.1.57264.1.10",
        "runnerEnvironment": "1.3.6.1.4.1.57264.1.11",
        "sourceRepositoryURI": "1.3.6.1.4.1.57264.1.12",
        "sourceRepositoryDigest": "1.3.6.1.4.1.57264.1.13",
        "sourceRepositoryRef": "1.3.6.1.4.1.57264.1.14",
        "buildConfigURI": "1.3.6.1.4.1.57264.1.18",
        "buildConfigDigest": "1.3.6.1.4.1.57264.1.19",
        "buildTrigger": "1.3.6.1.4.1.57264.1.20",
        "runInvocationURI": "1.3.6.1.4.1.57264.1.21",
        "sourceRepositoryVisibilityAtSigning": "1.3.6.1.4.1.57264.1.22",
        "protectedEnvironment": SMOKE_PROTECTED_ENVIRONMENT_OID,
    }
    result = {"subjectAlternativeName": names[0]}
    for name, oid in oid_names.items():
        try:
            value = leaf.extensions.get_extension_for_oid(
                ObjectIdentifier(oid)
            ).value.value
        except x509.ExtensionNotFound as exc:
            raise ReadinessError(f"attestation certificate lacks required OID {oid}") from exc
        require(isinstance(value, bytes), f"attestation certificate OID {oid} has invalid value")
        result[name] = _decode_utf8_extension(value, oid=oid)
    return result


def _expected_certificate_bindings(subject: Mapping[str, Any]) -> dict[str, str]:
    execution = subject["execution"]
    cert_identity = _smoke_cert_identity(execution["source_ref"])
    run_uri = (
        f"https://github.com/{SMOKE_ATTESTATION_REPOSITORY}/actions/runs/"
        f"{execution['workflow_run_id']}/attempts/{execution['workflow_run_attempt']}"
    )
    return {
        "subjectAlternativeName": cert_identity,
        "issuer": SMOKE_OIDC_ISSUER,
        "buildSignerURI": cert_identity,
        "buildSignerDigest": execution["source_digest"],
        "runnerEnvironment": SMOKE_ATTESTATION_RUNNER,
        "sourceRepositoryURI": f"https://github.com/{SMOKE_ATTESTATION_REPOSITORY}",
        "sourceRepositoryDigest": execution["source_digest"],
        "sourceRepositoryRef": execution["source_ref"],
        "buildConfigURI": cert_identity,
        "buildConfigDigest": execution["source_digest"],
        "buildTrigger": execution["event_name"],
        "runInvocationURI": run_uri,
        "sourceRepositoryVisibilityAtSigning": "public",
        "protectedEnvironment": "trimem-grader-smoke-exec",
    }


def _validate_attestation_artifacts(
    *,
    subject_raw: bytes,
    bundle_raw: bytes,
    public_raw: bytes,
    inventory_raw: bytes,
    approval: Mapping[str, Any],
) -> dict[str, Any]:
    subject = _strict_json_bytes(
        subject_raw, label=OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH
    )
    require(
        set(subject) == {"approval_binding", "artifacts", "execution", "schema"}
        and subject.get("schema") == SMOKE_ATTESTATION_SCHEMA
        and subject_raw == _pretty_json(subject)
        and subject.get("approval_binding") == approval,
        "official smoke deterministic attestation subject differs",
    )
    execution = subject.get("execution")
    require(
        isinstance(execution, dict)
        and set(execution)
        == {
            "event_name", "repository", "runner_environment", "signer_workflow",
            "source_digest", "source_ref", "workflow_run_attempt", "workflow_run_id",
        }
        and execution.get("repository") == SMOKE_ATTESTATION_REPOSITORY
        and execution.get("runner_environment") == SMOKE_ATTESTATION_RUNNER
        and execution.get("signer_workflow") == SMOKE_ATTESTATION_WORKFLOW
        and execution.get("source_digest") == approval.get("git_head")
        and SMOKE_ATTESTATION_SOURCE_REF_BY_EVENT.get(execution.get("event_name"))
        == execution.get("source_ref")
        and execution.get("workflow_run_id")
        == approval.get("approved_workflow_run_id")
        and execution.get("workflow_run_attempt")
        == approval.get("approved_workflow_run_attempt"),
        "official smoke attestation execution/approval identity differs",
    )
    artifacts = subject.get("artifacts")
    require(
        isinstance(artifacts, dict)
        and set(artifacts)
        == {
            "encrypted_restricted_evidence", "evidence_inventory", "public_results",
        },
        "official smoke attestation artifact set differs",
    )
    expected_artifacts = {
        "public_results": ("public-results.json", public_raw),
        "evidence_inventory": ("evidence-inventory.json", inventory_raw),
    }
    for key, (name, raw) in expected_artifacts.items():
        require(
            artifacts.get(key)
            == {
                "bytes": len(raw),
                "name": name,
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
            f"official smoke attestation {key} exact bytes/hash differs",
        )
    encrypted = artifacts.get("encrypted_restricted_evidence")
    require(
        isinstance(encrypted, dict)
        and set(encrypted) == {"bytes", "name", "sha256"}
        and encrypted.get("name") == "trimem-grader-smoke-restricted.tar.enc"
        and type(encrypted.get("bytes")) is int
        and encrypted["bytes"] > 0
        and isinstance(encrypted.get("sha256"), str)
        and HEX64.fullmatch(encrypted["sha256"]) is not None,
        "official smoke encrypted evidence subject binding differs",
    )

    bundle = _strict_json_bytes(
        bundle_raw, label=OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH
    )
    require(
        set(bundle) == {"dsseEnvelope", "mediaType", "verificationMaterial"}
        and bundle.get("mediaType")
        == "application/vnd.dev.sigstore.bundle.v0.3+json",
        "official smoke attestation bundle field/media type differs",
    )
    statement = _bundle_statement(bundle)
    require(
        statement.get("_type") == "https://in-toto.io/Statement/v1"
        and statement.get("predicateType") == "https://slsa.dev/provenance/v1"
        and statement.get("subject")
        == [{
            "name": "attestation-subject.json",
            "digest": {"sha256": hashlib.sha256(subject_raw).hexdigest()},
        }],
        "official smoke attestation statement subject/predicate differs",
    )
    certificate = _bundle_certificate_bindings(bundle)
    require(
        certificate == _expected_certificate_bindings(subject),
        "official smoke attestation certificate identity/run/environment differs",
    )
    return subject


def _strict_json_array(raw: bytes, *, label: str) -> list[Any]:
    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise ReadinessError(f"duplicate JSON key in {label}: {key}")
            value[key] = child
        return value
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"invalid JSON output from {label}") from exc
    require(isinstance(value, list), f"{label} root is not an array")
    return value


def _validate_gh_attestation_output(
    raw: bytes, subject: Mapping[str, Any], bundle: Mapping[str, Any]
) -> None:
    results = _strict_json_array(raw, label="gh attestation verify")
    cert_identity = _smoke_cert_identity(subject["execution"]["source_ref"])
    require(len(results) == 1 and isinstance(results[0], dict), "gh verified attestation count differs")
    row = results[0]
    require(
        set(row) == {"attestation", "verificationResult"},
        "gh attestation result field set differs",
    )
    attestation = row.get("attestation")
    require(
        attestation
        == {"bundle": bundle, "bundle_url": "", "initiator": ""},
        "gh verified attestation bundle bytes/field set differs",
    )
    verified_bundle = attestation["bundle"]
    require(
        _bundle_certificate_bindings(verified_bundle)
        == _expected_certificate_bindings(subject),
        "gh verified bundle leaf certificate binding differs",
    )
    result = row.get("verificationResult")
    require(
        isinstance(result, dict)
        and set(result)
        == {
            "mediaType", "signature", "statement", "verifiedIdentity",
            "verifiedTimestamps",
        }
        and result.get("mediaType")
        == "application/vnd.dev.sigstore.verificationresult+json;version=0.1"
        and isinstance(result.get("verifiedTimestamps"), list)
        and bool(result["verifiedTimestamps"]),
        "gh attestation cryptographic verification result differs",
    )
    require(
        result.get("verifiedIdentity")
        == {
            "issuer": {"issuer": "", "regexp": ".*"},
            "runnerEnvironment": SMOKE_ATTESTATION_RUNNER,
            "subjectAlternativeName": {
                "subjectAlternativeName": cert_identity,
            },
        },
        "gh verified identity policy differs",
    )
    signature = result.get("signature")
    certificate = signature.get("certificate") if isinstance(signature, dict) else None
    expected = _expected_certificate_bindings(subject)
    require(isinstance(certificate, dict), "gh verified certificate summary is missing")
    for field, value in expected.items():
        if field == "protectedEnvironment":
            continue
        require(
            certificate.get(field) == value,
            f"gh verified certificate {field} differs",
        )
    statement = result.get("statement")
    require(
        isinstance(statement, dict)
        and statement.get("_type") == "https://in-toto.io/Statement/v1"
        and statement.get("predicateType") == "https://slsa.dev/provenance/v1"
        and statement.get("subject")
        == [{
            "name": "attestation-subject.json",
            "digest": {"sha256": hashlib.sha256(_pretty_json(dict(subject))).hexdigest()},
        }],
        "gh verified statement subject differs",
    )


def _validate_live_workflow_run_attempt(
    raw: bytes, subject: Mapping[str, Any]
) -> None:
    """Bind the signature to the completed, successful GitHub run attempt.

    A Sigstore attestation can already exist when a later artifact upload or
    cleanup step makes its workflow run fail.  The exact attempt endpoint is
    therefore part of the paid-phase gate rather than an informational check.
    """

    execution = subject["execution"]
    row = _strict_json_bytes(raw, label="GitHub workflow run-attempt API")
    require(
        set(row)
        == {
            "conclusion", "event", "head_branch", "head_sha", "id", "path",
            "repository_full_name", "run_attempt", "status", "workflow_id",
        },
        "GitHub workflow run-attempt field set differs",
    )
    run_id = execution.get("workflow_run_id")
    run_attempt = execution.get("workflow_run_attempt")
    source_ref = execution.get("source_ref")
    require(
        isinstance(run_id, str)
        and POSITIVE_INTEGER.fullmatch(run_id) is not None
        and isinstance(run_attempt, str)
        and POSITIVE_INTEGER.fullmatch(run_attempt) is not None
        and isinstance(source_ref, str)
        and source_ref.startswith("refs/heads/")
        and len(source_ref) > len("refs/heads/"),
        "official smoke subject has invalid live run identity",
    )
    require(
        type(row.get("id")) is int
        and row["id"] == int(run_id)
        and type(row.get("run_attempt")) is int
        and row["run_attempt"] == int(run_attempt)
        and row.get("event") == execution.get("event_name")
        and row.get("status") == "completed"
        and row.get("conclusion") == "success"
        and row.get("head_sha") == execution.get("source_digest")
        and row.get("head_branch") == source_ref.removeprefix("refs/heads/")
        and row.get("path") == SMOKE_ATTESTATION_WORKFLOW
        and type(row.get("workflow_id")) is int
        and row["workflow_id"] > 0
        and row.get("repository_full_name") == SMOKE_ATTESTATION_REPOSITORY,
        "official smoke live run attempt is not the exact completed successful execution",
    )


def verify_official_smoke_attestation_cryptographically() -> None:
    """Cryptographically enforce the official-smoke trust anchor before paid phases."""

    smoke = read_json(ARTIFACT / "grader_smoke_result.json")
    evidence = smoke.get("official_execution_evidence")
    require(isinstance(evidence, dict), "official smoke execution evidence is missing")
    subject_path = ROOT / OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH
    bundle_path = ROOT / OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH
    subject_raw, bundle_raw = subject_path.read_bytes(), bundle_path.read_bytes()
    subject = _strict_json_bytes(
        subject_raw, label=OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH
    )
    certificate = _bundle_certificate_bindings(
        _strict_json_bytes(bundle_raw, label=OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH)
    )
    require(
        certificate == _expected_certificate_bindings(subject),
        "official smoke bundle certificate binding differs before gh verification",
    )
    gh = shutil.which("gh")
    require(gh is not None, "gh CLI is required for cryptographic smoke attestation verification")
    require(
        bool(os.environ.get("GH_TOKEN")),
        "GH_TOKEN is required for exact official smoke run-attempt verification",
    )
    version = subprocess.run(
        [gh, "--version"], cwd=ROOT, capture_output=True, check=False
    )
    require(
        version.returncode == 0
        and version.stdout.splitlines()
        and version.stdout.splitlines()[0]
        == SMOKE_GH_VERSION_LINE.encode("ascii"),
        "gh CLI version differs from the pre-frozen attestation verifier",
    )
    execution = subject["execution"]
    cert_identity = _smoke_cert_identity(execution["source_ref"])
    command = [
        gh, "attestation", "verify", str(subject_path),
        "--bundle", str(bundle_path),
        "--custom-trusted-root", str(ROOT / SMOKE_TRUSTED_ROOT_PATH),
        "--repo", SMOKE_ATTESTATION_REPOSITORY,
        "--cert-identity", cert_identity,
        "--cert-oidc-issuer", SMOKE_OIDC_ISSUER,
        "--deny-self-hosted-runners",
        "--signer-digest", execution["source_digest"],
        "--source-digest", execution["source_digest"],
        "--source-ref", execution["source_ref"],
        "--predicate-type=https://slsa.dev/provenance/v1",
        "--digest-alg=sha256",
        "--format=json",
    ]
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, check=False
    )
    require(
        completed.returncode == 0,
        "gh cryptographic smoke attestation verification failed",
    )
    bundle = _strict_json_bytes(
        bundle_raw, label=OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH
    )
    _validate_gh_attestation_output(completed.stdout, subject, bundle)
    route = SMOKE_RUN_API_ROUTE_TEMPLATE.format(
        repository=SMOKE_ATTESTATION_REPOSITORY,
        run_id=execution["workflow_run_id"],
        run_attempt=execution["workflow_run_attempt"],
    )
    live_command = [
        gh, "api", "--hostname", "github.com", route,
        "--method", "GET",
        "-H", f"Accept: {SMOKE_GITHUB_API_ACCEPT}",
        "-H", f"X-GitHub-Api-Version: {SMOKE_GITHUB_API_VERSION}",
        "--jq", SMOKE_RUN_API_JSON_PROJECTION,
    ]
    live = subprocess.run(
        live_command, cwd=ROOT, capture_output=True, check=False
    )
    require(
        live.returncode == 0,
        "GitHub official smoke run-attempt verification failed",
    )
    _validate_live_workflow_run_attempt(live.stdout, subject)


def _validate_official_smoke_pass(
    smoke: dict[str, Any], *, public_raw: bytes, inventory_raw: bytes,
    subject_raw: bytes, bundle_raw: bytes,
) -> None:
    evidence = smoke.get("official_execution_evidence")
    require(
        isinstance(evidence, dict) and set(evidence) == SMOKE_EVIDENCE_FIELDS,
        "passed grader smoke official evidence field set differs",
    )
    require(
        evidence.get("public_result_path") == OFFICIAL_SMOKE_PUBLIC_RESULT_PATH
        and evidence.get("evidence_inventory_path")
        == OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
        "passed grader smoke official evidence paths differ",
    )
    require(
        evidence.get("attestation_subject_path")
        == OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH
        and evidence.get("attestation_bundle_path")
        == OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH,
        "passed grader smoke attestation evidence paths differ",
    )
    for field, raw in (
        ("public_result_raw_sha256", public_raw),
        ("evidence_inventory_raw_sha256", inventory_raw),
        ("attestation_subject_raw_sha256", subject_raw),
        ("attestation_bundle_raw_sha256", bundle_raw),
    ):
        require(
            isinstance(evidence.get(field), str)
            and HEX64.fullmatch(evidence[field]) is not None
            and evidence[field] == hashlib.sha256(raw).hexdigest(),
            f"passed grader smoke {field} differs from committed bytes",
        )

    public = _strict_json_bytes(public_raw, label=OFFICIAL_SMOKE_PUBLIC_RESULT_PATH)
    inventory = _strict_json_bytes(
        inventory_raw, label=OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH
    )
    expected_public_fields = {
        "schema", *SMOKE_AGGREGATE_BODY_FIELDS, *SMOKE_PUBLIC_ONLY_FIELDS,
    }
    require(set(public) == expected_public_fields, "official public smoke field set differs")
    require(
        public.get("schema") == "trimem/public-benchmark-artifact/1.0"
        and public.get("status") == "PASS"
        and public.get("manifest") == "grader-smoke"
        and public.get("stream_totals") == []
        and public.get("restricted_evidence")
        == "ENCRYPTED_SEPARATE_ARTIFACT_NOT_PUBLIC"
        and public.get("dataset_rows_or_gold_test_payloads")
        == "EXCLUDED_AND_EPHEMERAL_INPUTS_PURGED",
        "official public smoke identity/privacy contract differs",
    )

    actual_accounting = {
        "grader_calls": 12,
        "grader_containers": 12,
        "model_gateway_calls": 0,
        "official_grader_runs": 12,
        "paid_model_calls": 0,
    }
    evidence_counts = {
        name: 12
        for name in (
            "patch", "tests", "container", "evaluator", "report", "digest",
            "applied_patch", "test_output", "official_test_status",
        )
    }
    lifecycle_actual = {
        "target_image_pulls": 6,
        "support_image_pulls": 1,
        "exact_image_removals": 7,
        "max_resident_target_images": 1,
        "max_resident_support_images": 1,
        "resident_target_images": 0,
        "resident_support_images": 0,
    }
    lifecycle = public.get("image_lifecycle")
    require(
        public.get("actual_accounting") == actual_accounting
        and public.get("probe_counts") == {"GOLD": 6, "NOOP_BASELINE": 6}
        and public.get("resolved_counts") == {"GOLD": 6, "NOOP_BASELINE": 0}
        and public.get("unresolved_counts") == {"GOLD": 0, "NOOP_BASELINE": 6}
        and public.get("evidence_counts") == evidence_counts
        and public.get("empty_patch_ids") == []
        and type(public.get("expected_target_count")) is int
        and public["expected_target_count"] == 12
        and type(public.get("observed_target_count")) is int
        and public["observed_target_count"] == 12
        and type(public.get("patch_applied_count")) is int
        and public["patch_applied_count"] == 12
        and type(public.get("tests_executed_count")) is int
        and public["tests_executed_count"] == 12
        and type(public.get("digest_match_count")) is int
        and public["digest_match_count"] == 12
        and type(public.get("infrastructure_failure_count")) is int
        and public["infrastructure_failure_count"] == 0
        and isinstance(lifecycle, dict)
        and set(lifecycle)
        == {"actual", "event_count", "report_bytes", "report_sha256", "status"}
        and lifecycle.get("actual") == lifecycle_actual
        and type(lifecycle.get("event_count")) is int
        and lifecycle["event_count"] == 14
        and type(lifecycle.get("report_bytes")) is int
        and lifecycle["report_bytes"] > 0
        and isinstance(lifecycle.get("report_sha256"), str)
        and HEX64.fullmatch(lifecycle["report_sha256"]) is not None
        and lifecycle.get("status") == "PASS",
        "official public smoke scientific/lifecycle counters differ",
    )

    manifest = read_json(CONFIG / "grader_smoke_manifest.json")
    targets = manifest.get("targets")
    outcomes = public.get("outcomes")
    require(
        isinstance(targets, list)
        and isinstance(outcomes, list)
        and len(targets) == len(outcomes) == 12,
        "official public smoke outcome coverage differs",
    )
    outcome_fields = {
        "benchmark_id", "order_index", "probe", "resolved", "target_id",
        "applied_patch_sha256", "official_test_output_sha256",
        "official_test_status_sha256",
    }
    for index, (target, outcome) in enumerate(zip(targets, outcomes)):
        require(
            isinstance(target, dict)
            and isinstance(outcome, dict)
            and set(outcome) == outcome_fields
            and outcome.get("target_id") == target.get("target_id")
            and outcome.get("benchmark_id") == target.get("benchmark_id")
            and type(outcome.get("order_index")) is int
            and outcome["order_index"] == index == target.get("order_index")
            and outcome.get("probe") == target.get("probe")
            and type(outcome.get("resolved")) is bool
            and outcome["resolved"] is target.get("expected_resolved")
            and all(
                isinstance(outcome.get(field), str)
                and HEX64.fullmatch(outcome[field]) is not None
                for field in (
                    "applied_patch_sha256", "official_test_output_sha256",
                    "official_test_status_sha256",
                )
            ),
            f"official public smoke outcome {index} differs from frozen target",
        )

    approval = public.get("approval_binding")
    require(
        isinstance(approval, dict)
        and set(approval) == SMOKE_APPROVAL_FIELDS
        and approval.get("phase") == "GRADER_SMOKE"
        and isinstance(approval.get("git_head"), str)
        and HEX40.fullmatch(approval["git_head"]) is not None
        and all(
            isinstance(approval.get(field), str)
            and HEX64.fullmatch(approval[field]) is not None
            for field in (
                "approval_artifact_sha256", "approved_request_sha256", "freeze_sha256"
            )
        )
        and all(
            isinstance(approval.get(field), str)
            and POSITIVE_INTEGER.fullmatch(approval[field]) is not None
            for field in ("approved_workflow_run_id", "approved_workflow_run_attempt")
        ),
        "official public smoke approval binding differs",
    )
    require(
        evidence.get("approval_binding") == approval,
        "grader smoke result/public approval binding differs",
    )
    _validate_attestation_artifacts(
        subject_raw=subject_raw,
        bundle_raw=bundle_raw,
        public_raw=public_raw,
        inventory_raw=inventory_raw,
        approval=approval,
    )
    execution_head = approval["git_head"]
    require(
        _execution_head_is_ancestor(execution_head),
        "official smoke execution HEAD is not an ancestor of the result commit",
    )
    historical_freeze = _historical_git_file(
        execution_head, "artifacts/trimem_v1/freeze.json"
    )
    historical_request = _historical_git_file(
        execution_head,
        GRADER_SMOKE_SENTINEL_PATH,
    )
    request = _validate_historical_smoke_request(execution_head, historical_request)
    require(
        hashlib.sha256(historical_freeze).hexdigest() == approval["freeze_sha256"]
        and hashlib.sha256(historical_request).hexdigest()
        == approval["approved_request_sha256"]
        and request.get("schema") == GRADER_SMOKE_REQUEST_SCHEMA
        and request.get("phase") == "GRADER_SMOKE"
        and request.get("actual_execution_authorized") is False
        and request.get("requires_external_approval") is True
        and request.get("freeze_sha256") == "sha256:" + approval["freeze_sha256"],
        "official smoke historical HEAD/freeze/request binding differs",
    )
    historical_freeze_value = _strict_json_bytes(
        historical_freeze, label="historical official-smoke freeze"
    )
    historical_files = historical_freeze_value.get("files")
    require(isinstance(historical_files, dict), "historical smoke freeze file inventory is missing")
    for relative in (SMOKE_TRUSTED_ROOT_PATH, SMOKE_ATTESTATION_POLICY_PATH):
        historical_raw = _historical_git_file(execution_head, relative)
        current_raw = (ROOT / relative).read_bytes()
        require(
            historical_raw == current_raw,
            f"post-smoke mutation of pre-frozen trust anchor is prohibited: {relative}",
        )
        require(
            historical_files.get(relative)
            == {
                "bytes": len(historical_raw),
                "sha256": hashlib.sha256(historical_raw).hexdigest(),
            },
            f"historical smoke freeze does not seal trust anchor: {relative}",
        )

    aggregate_body = {
        field: public[field] for field in SMOKE_AGGREGATE_BODY_FIELDS
    }
    aggregate_body["schema"] = "trimem/verified-aggregate/1.0"
    aggregate_sha = hashlib.sha256(canonical(aggregate_body)).hexdigest()
    require(
        public.get("verified_aggregate_sha256") == aggregate_sha
        and evidence.get("verified_aggregate_sha256") == aggregate_sha,
        "official public smoke does not reproduce its verified aggregate seal",
    )
    aggregate_raw = _pretty_json({**aggregate_body, "aggregate_sha256": aggregate_sha})
    require(
        isinstance(evidence.get("aggregate_raw_sha256"), str)
        and HEX64.fullmatch(evidence["aggregate_raw_sha256"]) is not None
        and evidence["aggregate_raw_sha256"]
        == hashlib.sha256(aggregate_raw).hexdigest(),
        "grader smoke result aggregate raw SHA differs",
    )
    rows = _inventory_rows(inventory)
    _require_inventory_raw(rows, "aggregate.json", aggregate_raw, label="aggregate")
    _require_inventory_raw(rows, "public-results.json", public_raw, label="public result")
    public_approval_raw = _pretty_json(approval)
    _require_inventory_raw(
        rows,
        "results/external-approval-evidence.json",
        public_approval_raw,
        label="public approval subset",
    )
    restricted_approval = rows.get("results/restricted-external-approval.json")
    require(
        isinstance(restricted_approval, Mapping)
        and restricted_approval.get("sha256") == approval["approval_artifact_sha256"]
        and type(restricted_approval.get("bytes")) is int
        and restricted_approval["bytes"] > 0,
        "official smoke restricted approval inventory binding differs",
    )
    lifecycle_row = rows.get("image-materialization/image-lifecycle-report.json")
    require(
        isinstance(lifecycle_row, Mapping)
        and lifecycle_row.get("sha256") == lifecycle["report_sha256"]
        and lifecycle_row.get("bytes") == lifecycle["report_bytes"],
        "official smoke lifecycle report inventory binding differs",
    )
    summary = {
        "schema": "trimem/grader-smoke-execution/1.0",
        "expected_target_count": 12,
        "observed_target_count": 12,
        "probe_counts": {"GOLD": 6, "NOOP_BASELINE": 6},
        "empty_patch_ids": [],
        "failures": [],
        "grader_containers": 12,
        "official_grader_runs": 12,
        "patch_applied_count": 12,
        "tests_executed_count": 12,
        "digest_match_count": 12,
        "infrastructure_failure_count": 0,
        "model_gateway_calls": 0,
        "paid_model_calls": 0,
        "status": "PASS",
    }
    _require_inventory_raw(
        rows,
        "results/smoke-execution-summary.json",
        _pretty_json(summary),
        label="execution summary",
    )
    expected_result_paths = set()
    for index, target in enumerate(targets):
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(target["target_id"]))
        expected_result_paths.add(f"results/{index:03d}-{safe}/{safe}.result.json")
    observed_result_paths = {
        path for path in rows
        if re.fullmatch(r"results/[0-9]{3}-[^/]+/[^/]+\.result\.json", path)
    }
    require(
        observed_result_paths == expected_result_paths,
        "official smoke inventory task-result exact set differs",
    )


def validate_grader_smoke_result(smoke: dict[str, Any]) -> dict[str, int]:
    pending = smoke.get("status") == "CORRECTION_IN_PROGRESS"
    expected_fields = SMOKE_RESULT_COMMON_FIELDS if pending else {
        *SMOKE_RESULT_COMMON_FIELDS, "official_execution_evidence",
    }
    require(set(smoke) == expected_fields, "grader smoke result field set differs")
    require(
        smoke.get("schema") == "trimem/grader-smoke-result/1.0"
        and smoke.get("trimem_system_implementation") == "CREDENTIAL_FREE_GREEN"
        and smoke.get("performance") == "NOT_MEASURED"
        and smoke.get("expected_unique_instances") == 6
        and smoke.get("expected_target_count") == 12
        and smoke.get("expected_condition_rows")
        == {"GOLD": 6, "NOOP_BASELINE": 6},
        "grader smoke result static contract differs",
    )
    pre_smoke_actual = {
        "docker_pulls": 0,
        "grader_containers": 0,
        "input_tokens": 0,
        "model_calls": 0,
        "official_grader_runs": 0,
        "output_tokens": 0,
        "paid_model_calls": 0,
        "total_usd": 0,
    }
    passed_smoke_actual = {
        **pre_smoke_actual,
        "docker_pulls": 7,
        "grader_containers": 12,
        "official_grader_runs": 12,
    }
    actual = smoke.get("actual_execution")
    require(
        isinstance(actual, dict) and all(type(value) is int for value in actual.values()),
        "grader smoke execution counter types differ",
    )
    state = (
        smoke.get("status"), smoke.get("grader_exec_package"),
        smoke.get("official_grader_viability"),
    )
    if pending:
        require(
            state
            == (
                "CORRECTION_IN_PROGRESS", "CORRECTION_IN_PROGRESS",
                "NOT_YET_ESTABLISHED",
            )
            and actual == pre_smoke_actual,
            "pre-exec grader smoke state/counter contract is invalid",
        )
    else:
        require(
            state == ("PASS", "PASS", "ESTABLISHED")
            and actual == passed_smoke_actual,
            "passed grader smoke state/counter contract is invalid",
        )
        public_raw = (ROOT / OFFICIAL_SMOKE_PUBLIC_RESULT_PATH).read_bytes()
        inventory_raw = (ROOT / OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH).read_bytes()
        subject_raw = (ROOT / OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH).read_bytes()
        bundle_raw = (ROOT / OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH).read_bytes()
        _validate_official_smoke_pass(
            smoke, public_raw=public_raw, inventory_raw=inventory_raw,
            subject_raw=subject_raw, bundle_raw=bundle_raw,
        )
    return actual


def exact_hash(value: Any, message: str, length: int = 64) -> str:
    pattern = HEX64 if length == 64 else HEX40
    require(isinstance(value, str) and pattern.fullmatch(value) is not None, message)
    require(len(set(value)) > 2, message + " (placeholder-like)")
    return value


def strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


def validate_sources() -> None:
    audit = read_json(ARTIFACT / "upstream_source_audit.json")
    require(audit.get("official_primary_sources_only") is True, "source audit is not official-primary-only")
    expected = {
        "swebench_verified": ("78f471bf655a3137b2e8a75af1501690ec009ec3", "030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25"),
        "multi_swe_bench_mini": ("d0fab3ccc7dff232fcaac234cf8af9a2efeaccf6", "6644b9c9ebaf5e5b37cb9d81c4dce688c101f07436aed9d50fc55c85b164c3b2"),
        "multi_swe_bench_flash": ("b0485dbebaf8a1317ebf140e80e6fc6c02d3502b", "48d6d02cc976a71a06b494cc60581d92e82c06c2793c0d412c52c63e6956bebe"),
    }
    rows = {row.get("benchmark_id"): row for row in audit.get("benchmarks", ()) if isinstance(row, Mapping)}
    require(set(rows) == set(expected), "official benchmark source set mismatch")
    for name, (revision, data_hash) in expected.items():
        dataset, harness = rows[name].get("dataset", {}), rows[name].get("harness", {})
        require(dataset.get("revision") == revision, f"dataset revision drift: {name}")
        require(dataset.get("data_file", {}).get("lfs_oid_sha256") == data_hash, f"dataset file digest drift: {name}")
        exact_hash(harness.get("revision"), f"harness revision is not exact: {name}", 40)
    grader = read_json(CONFIG / "grader_lock.json")
    terms = grader.get("dataset_terms_boundary", {})
    require(terms.get("no_dataset_redistribution") is True, "dataset no-redistribution boundary is missing")
    require("DATASET_LICENSE_NOT_DECLARED" in str(terms.get("swebench_verified")), "SWE license absence is overstated")
    require("not legal clearance" in str(terms.get("execution_approval_requirement")), "legal approval boundary is missing")


def validate_targets() -> dict[str, list[dict[str, Any]]]:
    plan = read_json(CONFIG / "selection_plan.json")
    require(plan.get("schema") == "trimem/selection-plan/3.0", "selector v3 is not frozen")
    require(plan.get("row_score") == "sha256(seed|trimem-selector-v3|split|benchmark_id|instance_id), ascending lowercase bytes", "selector score is not public-identity-only")
    require(plan.get("source_policy", {}).get("per_slot_nonce_or_override_allowed") is False, "selector permits per-slot override")
    forbidden_text = " ".join(strings(plan)).lower()
    require("salt" not in forbidden_text and "nonce" not in forbidden_text.replace("per_slot_nonce_or_override_allowed", ""), "selector contains a salt/nonce escape hatch")
    manifests = {
        name: read_json(CONFIG / f"{name}_manifest.json")
        for name in ("development", "heldout")
    }
    smoke = read_json(CONFIG / "grader_smoke_manifest.json")
    manifests["grader-smoke"] = smoke
    require(
        "pooled resolved_count" in str(
            manifests["development"].get("tuning_selection_objective", "")
        )
        and "not the held-out primary endpoint" in str(
            manifests["development"].get("tuning_selection_objective", "")
        ),
        "development joint-tuning objective is not separated from held-out primary reporting",
    )
    expected_counts = {"development": 12, "heldout": 27, "grader-smoke": 12}
    result: dict[str, list[dict[str, Any]]] = {}
    for name, manifest in manifests.items():
        targets = manifest.get("targets")
        require(isinstance(targets, list) and len(targets) == expected_counts[name], f"{name} target count mismatch")
        require(manifest.get("status") in {"FROZEN", "FROZEN_TARGET_SET_EXECUTION_PENDING"}, f"{name} target set is not frozen")
        target_ids = [row.get("target_id") for row in targets]
        require(len(set(target_ids)) == len(target_ids), f"{name} target IDs are duplicated")
        require(
            hashlib.sha256(canonical(targets)).hexdigest() == manifest.get("target_set_sha256"),
            f"{name} canonical target-set digest mismatch",
        )
        for index, row in enumerate(targets):
            exact_hash(row.get("dataset_revision"), f"{name} dataset revision missing", 40)
            exact_hash(row.get("source_row_sha256"), f"{name} source row hash missing")
            exact_hash(row.get("base_commit"), f"{name} base commit missing", 40)
            if name != "grader-smoke":
                require(row.get("order_index") == index, f"{name} frozen order mismatch")
        if name != "grader-smoke":
            roles = manifest.get("benchmark_roles")
            require(isinstance(roles, list) and len(roles) == 3, f"{name} benchmark roles are missing")
            role_ids = [row.get("benchmark_id") for row in roles]
            require(len(set(role_ids)) == len(roles), f"{name} benchmark roles are duplicated")
            counts = Counter(row.get("benchmark_id") for row in targets)
            revisions = {
                benchmark_id: {row.get("dataset_revision") for row in targets if row.get("benchmark_id") == benchmark_id}
                for benchmark_id in counts
            }
            for role in roles:
                benchmark_id = role.get("benchmark_id")
                require(
                    set(role) == {"benchmark_id", "dataset_id", "dataset_revision", "role", "target_count"}
                    and counts.get(benchmark_id) == role.get("target_count")
                    and revisions.get(benchmark_id) == {role.get("dataset_revision")}
                    and role.get("role") in {"PRIMARY", "SECONDARY"},
                    f"{name} benchmark role/count/revision drift",
                )
            require(
                [row.get("benchmark_id") for row in roles if row.get("role") == "PRIMARY"]
                == ["swebench_verified"]
                and all(
                    row.get("role") == "SECONDARY"
                    for row in roles
                    if str(row.get("benchmark_id", "")).startswith("multi_swe_bench_")
                ),
                f"{name} primary/secondary endpoint roles drift",
            )
        result[name] = targets
    smoke_manifest = manifests["grader-smoke"]
    require(
        smoke_manifest.get("execution_control_amendment")
        == EXECUTION_CONTROL_AMENDMENT,
        "P0.1.1 non-semantic execution-control amendment differs",
    )
    require(
        smoke_manifest.get("target_set_sha256") == BASELINE_TARGET_SET_SHA256,
        "P0.1.1 changed the frozen grader-smoke target set",
    )
    for relative, expected_sha256 in (
        *HISTORICAL_SENTINELS,
        (GRADER_SMOKE_FROZEN_REQUEST_PATH, BASELINE_FROZEN_REQUEST_SHA256),
        (GRADER_SMOKE_IMAGE_LOCK_PATH, BASELINE_IMAGE_LOCK_SHA256),
        (
            GRADER_SMOKE_CREDENTIAL_BUNDLE_PATH,
            BASELINE_CREDENTIAL_FREE_BUNDLE_SHA256,
        ),
        (GRADER_SMOKE_PROTOCOL_PATH, BASELINE_PROTOCOL_SHA256),
    ):
        require(
            hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            == expected_sha256,
            f"P0.1.1 changed frozen scientific/control material: {relative}",
        )
    require(
        smoke_manifest.get("matrix_kind")
        == "single_serial_six_instance_gold_noop_campaign",
        "smoke manifest does not describe the single serial campaign",
    )
    pairs = Counter(
        (row["benchmark_id"], row["instance_id"])
        for row in result["grader-smoke"]
    )
    require(
        len(pairs) == 6 and set(pairs.values()) == {2},
        "smoke is not six GOLD/NOOP_BASELINE pairs",
    )
    for offset in range(0, len(result["grader-smoke"]), 2):
        gold, noop = result["grader-smoke"][offset : offset + 2]
        require(
            (gold.get("benchmark_id"), gold.get("instance_id"))
            == (noop.get("benchmark_id"), noop.get("instance_id"))
            and [gold.get("probe"), noop.get("probe")]
            == ["GOLD", "NOOP_BASELINE"],
            "smoke execution order is not deterministic GOLD then NOOP_BASELINE",
        )
    smoke_ids = {instance for _, instance in pairs}
    development_ids = {row["instance_id"] for row in result["development"]}
    heldout_ids = {row["instance_id"] for row in result["heldout"]}
    require(not (smoke_ids & development_ids or smoke_ids & heldout_ids or development_ids & heldout_ids), "target set instance overlap is nonzero")
    return result


def validate_images(targets: Mapping[str, list[dict[str, Any]]]) -> None:
    lock = read_json(ARTIFACT / "grader_image_lock.json")
    require(lock.get("status") == lock.get("smoke_status") == "FROZEN", "smoke image digests are not frozen")
    benchmark = lock.get("benchmark_target_images", {})
    require(benchmark.get("status") == "FROZEN" and benchmark.get("target_count") == 39, "all 39 benchmark images are not frozen")
    smoke_rows, benchmark_rows = lock.get("targets"), benchmark.get("targets")
    support_rows = lock.get("support_images")
    require(isinstance(smoke_rows, list) and len(smoke_rows) == 6, "smoke image lock count mismatch")
    require(isinstance(benchmark_rows, list) and len(benchmark_rows) == 39, "benchmark image lock count mismatch")
    require(isinstance(support_rows, list) and len(support_rows) == 1, "support image lock mismatch")
    expected_smoke = {row["instance_id"] for row in targets["grader-smoke"]}
    expected_benchmark = {row["instance_id"] for name in ("development", "heldout") for row in targets[name]}
    require({row.get("instance_id") for row in smoke_rows} == expected_smoke, "smoke image set drift")
    require({row.get("instance_id") for row in benchmark_rows} == expected_benchmark, "benchmark image set drift")
    for row in [*smoke_rows, *benchmark_rows, *support_rows]:
        image = row.get("image")
        require(isinstance(image, str) and DIGEST_IMAGE.fullmatch(image) is not None, "grader image is not digest-pinned")
        require(row.get("expected_digest") == image.rsplit("@", 1)[1], "image expected digest mismatch")
        exact_hash(row.get("registry_response_sha256"), "registry response provenance hash missing")
        require(str(row.get("registry_evidence_url", "")).startswith("https://hub.docker.com/v2/repositories/"), "image provenance is not official registry metadata")
    observation = lock.get("digest_observation", {})
    require(observation.get("docker_pull_or_run_performed") is False, "pre-EXEC image lock claims a Docker pull/run")
    started, completed = observation.get("query_started_at_utc"), observation.get("query_completed_at_utc")
    try:
        started_at = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        completed_at = datetime.fromisoformat(str(completed).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReadinessError("registry query timestamps are not exact") from exc
    require(started_at <= completed_at and "T00:00:00Z" not in str(started), "registry query timestamp is placeholder-like")
    material = "\n".join("|".join(str(row.get(key, "")) for key in (
        "benchmark_id", "instance_id", "registry_evidence_url", "expected_digest",
        "registry_last_updated_utc", "registry_response_sha256",
    )) for row in [*smoke_rows, *benchmark_rows, *support_rows])
    require(hashlib.sha256(material.encode("utf-8")).hexdigest() == observation.get("metadata_snapshot_sha256"), "registry metadata snapshot hash mismatch")


def validate_noop_baseline_audit(
    targets: Mapping[str, list[dict[str, Any]]]
) -> None:
    audit = read_json(ARTIFACT / "noop_baseline_six_commit_audit.json")
    body = {key: value for key, value in audit.items() if key != "audit_sha256"}
    require(
        audit.get("schema") == "trimem/noop-baseline-six-commit-audit/1.0"
        and audit.get("status") == "PASS"
        and audit.get("noop_baseline") == NOOP_BASELINE_LOCK
        and audit.get("manifest_target_set_sha256")
        == hashlib.sha256(canonical(targets["grader-smoke"])).hexdigest()
        and audit.get("audit_sha256")
        == hashlib.sha256(canonical(body)).hexdigest(),
        "NOOP_BASELINE six-base audit seal is invalid",
    )
    expected = {
        (row["repository"], row["instance_id"], row["base_commit"])
        for row in targets["grader-smoke"]
        if row.get("probe") == "GOLD"
    }
    rows = audit.get("rows")
    require(
        isinstance(rows, list) and len(rows) == 6,
        "NOOP_BASELINE audit row count is not six",
    )
    observed = set()
    for row in rows:
        require(isinstance(row, dict), "NOOP_BASELINE audit row is malformed")
        observed.add(
            (row.get("repository"), row.get("instance_id"), row.get("base_commit"))
        )
        require(
            row.get("root_marker_absent_at_base") is True
            and row.get("patch_applies_cached") is True
            and row.get("isolated_temporary_index") is True
            and row.get("changed_paths") == [NOOP_BASELINE_PATH]
            and row.get("forbidden_source_test_build_or_package_paths_touched") == []
            and row.get("staged_marker_sha256")
            == hashlib.sha256(NOOP_BASELINE_CONTENT).hexdigest()
            and isinstance(row.get("base_tree"), str)
            and HEX40.fullmatch(row["base_tree"]) is not None,
            "NOOP_BASELINE audit does not prove one safe new-file-only patch",
        )
    require(
        observed == expected,
        "NOOP_BASELINE audit target set differs from the smoke manifest",
    )


def validate_model_cost_environment() -> None:
    model = read_json(CONFIG / "model_lock.json")
    primary = model.get("primary_model", {})
    require(model.get("status") == "FROZEN_PRE_EXEC_EXECUTION_PENDING_APPROVAL", "model lock status is overstated")
    require(primary.get("model_id") == "gpt-5.4-2026-03-05" and primary.get("status") == "FROZEN", "dated model snapshot is not frozen")
    require((primary.get("input_price_per_million_tokens_usd"), primary.get("cached_input_price_per_million_tokens_usd"), primary.get("output_price_per_million_tokens_usd")) == (2.5, 0.25, 15.0), "official model pricing drift")
    require("gpt-5.6" not in " ".join(strings(model)), "unselected floating performance alternative remains")
    schema = model.get("request_schema")
    require(hashlib.sha256(canonical(schema)).hexdigest() == model.get("request_schema_sha256"), "request schema hash mismatch")
    guard = model.get("long_context_surcharge_guard", {})
    require(guard.get("maximum_reserved_input_tokens_per_call") == 262000 and guard.get("contract") == "NO_LONG_CONTEXT_SURCHARGE", "long-context surcharge guard drift")
    embedder = model.get("retrieval_embedding", {}).get("production", {})
    require((embedder.get("model_id"), embedder.get("revision"), embedder.get("dimension"), embedder.get("license")) == (
        "sentence-transformers/all-MiniLM-L6-v2", "1110a243fdf4706b3f48f1d95db1a4f5529b4d41", 384, "Apache-2.0"
    ), "production embedder lock drift")
    require(model.get("retrieval_embedding", {}).get("credential_free_fixture", {}).get("benchmark_execution_allowed") is False, "hash embedder is allowed in benchmark")
    require(model.get("actual_execution") == {"model_gateway_calls": 0, "paid_model_calls": 0}, "pre-EXEC model counters are nonzero")

    cost = read_json(CONFIG / "cost_plan.json")
    require(cost.get("schema") == "trimem/cost-plan/1.1", "cost plan schema is stale")
    counts = cost.get("run_counts", {})
    require((counts.get("development_physical_task_arm_runs"), counts.get("heldout_physical_task_arm_runs"), counts.get("total_physical_task_arm_runs")) == (72, 81, 153), "physical run counts do not include four-candidate tuning")
    expected, hard = cost.get("expected_cost", {}), cost.get("proposed_hard_cap", {})
    require((expected.get("model_calls"), expected.get("input_tokens"), expected.get("output_tokens"), expected.get("total_usd")) == (2142, 25092000, 918000, 76.5), "expected cost arithmetic drift")
    require((hard.get("model_calls"), hard.get("input_tokens"), hard.get("output_tokens"), hard.get("total_usd")) == (3978, 76500000, 8068608, 320.0), "proposed hard-cap arithmetic drift")
    phases = cost.get("phase_hard_caps", {})
    require(phases.get("DEVELOPMENT_TUNING", {}).get("task_arm_runs") == 72 and phases.get("HELDOUT_BENCHMARK", {}).get("task_arm_runs") == 81 and phases.get("GRADER_SMOKE", {}).get("benchmark_grader_containers") == 12, "phase hard caps are incomplete")
    require(all(value == 0 for value in cost.get("actual_to_date", {}).values()), "pre-EXEC cost counters are nonzero")

    environment = read_json(CONFIG / "benchmark_environment_lock.json")
    dependency = environment.get("dependency_lock", {})
    for field, path in (("input_sha256", CONFIG / "benchmark_environment.in"), ("lock_sha256", CONFIG / "benchmark_environment.lock")):
        require(hashlib.sha256(path.read_bytes()).hexdigest() == dependency.get(field), f"benchmark environment {field} mismatch")
    runner = environment.get("runner", {})
    require(runner.get("benchmark_exec_runner_labels") == ["self-hosted", "linux", "x64", "ubuntu-24.04", "trimem-benchmark"] and runner.get("benchmark_exec_max_job_minutes") == 7200, "long-running protected benchmark runner is not frozen")
    harness_lock = validate_harness_lock_configuration()
    require(
        harness_lock
        == {
            "benchmark_ids": [
                "multi_swe_bench_flash",
                "multi_swe_bench_mini",
                "swebench_verified",
            ],
            "dependency_count": 3,
            "hash_basis": HARNESS_DEPENDENCY_HASH_BASIS,
            "portable_projection_sha256": "042c8cfb2478f5515541a387575c7124312095df7e82d4e30798c7d82926df39",
        },
        "pinned harness Git-blob dependency lock is not exact",
    )
    require(environment.get("embedding_execution", {}).get("benchmark_hash_embedder_allowed") is False, "benchmark environment allows the fixture embedder")


def validate_readiness_plan(targets: Mapping[str, list[dict[str, Any]]]) -> None:
    plan = read_json(ARTIFACT / "readiness_requirements.json")
    require(plan.get("schema") == "trimem/readiness-requirements/1.1", "readiness requirements are stale")
    service_boundary = str(plan.get("credential_free_service_ci_boundary", ""))
    require(
        "ALLOWED_PRE_EXEC" in service_boundary
        and "digest-pinned PostgreSQL and Qdrant support services" in service_boundary
        and "official grader/benchmark target images" in service_boundary,
        "credential-free support-service/official-target execution boundary is absent",
    )
    m1_boundary = str(plan.get("m1_current_v03_boundary", ""))
    require(
        "CONTRACT_CANDIDATE" in m1_boundary
        and "no direct Qdrant write" in m1_boundary
        and "no immediate fresh-solve carryover" in m1_boundary,
        "M1 current-v0.3 atomic-outbox/no-immediate-carryover boundary is absent",
    )
    require(
        any(
            "per-arm/per-benchmark" in str(item)
            and "pooled totals descriptive only" in str(item)
            for item in plan.get("benchmark_approval_requires", ())
        ),
        "primary/secondary per-benchmark aggregation readiness requirement is absent",
    )
    pending = plan.get("explicitly_allowed_pending_at_pre_exec_ready", {})
    require("PENDING_EXEC_APPROVAL" in str(pending.get("official_grader_smoke")), "pre-EXEC smoke pending state is absent")
    require("PRE_DEVELOPMENT" in str(pending.get("selected_m2_checkpoint")), "pre-EXEC checkpoint state is circular")
    counts = plan.get("frozen_counts", {})
    require((counts.get("development_physical_task_arm_runs"), counts.get("heldout_physical_task_arm_runs"), counts.get("total_benchmark_physical_task_arm_runs")) == (72, 81, 153), "readiness physical-run counts drift")
    digests = plan.get("target_set_sha256", {})
    for name, key in (("development", "development"), ("heldout", "heldout"), ("grader-smoke", "grader_smoke")):
        expected = hashlib.sha256(canonical(targets[name])).hexdigest()
        require(digests.get(key) == expected, f"readiness target-set binding drift: {name}")
    require(all(value == 0 for value in plan.get("execution_counters", {}).values()), "readiness execution counters are nonzero")


def validate_runtime_and_candidates() -> None:
    bundle = load_bundle()
    require(bundle.get("candidate_order") == list(CANDIDATE_IDS), "M2 candidate order drift")
    require(bundle.get("development_contract", {}).get("candidate_task_arm_runs") == 48, "M2 candidate run count drift")
    require(bundle.get("development_contract", {}).get("component_ablation_claim") == "PROHIBITED", "candidate runs may be mislabeled ablations")
    selected = validate_selected_m2(require_frozen=False)
    require(selected.get("status") in {"PRE_DEVELOPMENT", "FROZEN_AFTER_DEVELOPMENT"}, "selected M2 state is invalid")
    arms = read_json(CONFIG / "arms.json")
    require(arms.get("development_streams") == ["M2-baseline", "M2-precision", "M2-recall", "M2-balanced", "M0", "M1"], "development stream contract drift")
    require(arms.get("runtime_ceiling") == RuntimeLock().to_manifest()["limits"], "runtime ceiling differs from source")
    m1_rows = [row for row in arms.get("arms", []) if row.get("arm_id") == "M1"]
    require(len(m1_rows) == 1, "M1 arm contract is missing or duplicated")
    m1 = m1_rows[0]
    baseline_commit = LIVE_V03_IMPLEMENTATION_MANIFEST["source_commit"]
    baseline_path = "src/enterprise_memory/service/durable.py"
    baseline_spec = f"{baseline_commit}:{baseline_path}"
    blob_id = subprocess.run(
        ["git", "rev-parse", baseline_spec],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    blob = subprocess.run(
        ["git", "show", baseline_spec],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    require(blob_id.returncode == 0 and blob.returncode == 0, "M1 baseline durable git object is unavailable")
    try:
        baseline_source = blob.stdout.decode("utf-8")
        module = ast.parse(baseline_source)
        finalizer_node = next(
            node for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "finalize_success_atomic"
        )
    except (UnicodeDecodeError, SyntaxError, StopIteration) as exc:
        raise ReadinessError("M1 baseline finalizer source cannot be verified") from exc
    finalizer_source = "".join(
        baseline_source.splitlines(keepends=True)[
            finalizer_node.lineno - 1: finalizer_node.end_lineno
        ]
    ).encode("utf-8")
    require(
        LIVE_V03_IMPLEMENTATION_MANIFEST.get("baseline_durable_git_blob_sha1")
        == blob_id.stdout.strip()
        and LIVE_V03_IMPLEMENTATION_MANIFEST.get("baseline_durable_blob_sha256")
        == hashlib.sha256(blob.stdout).hexdigest()
        and LIVE_V03_IMPLEMENTATION_MANIFEST.get(
            "baseline_finalize_success_atomic_ast_sha256"
        ) == hashlib.sha256(finalizer_source).hexdigest(),
        "M1 baseline durable/finalizer git provenance drift",
    )
    current_finalizer_source = inspect.getsource(
        __import__(
            "enterprise_memory.service.durable", fromlist=["finalize_success_atomic"]
        ).finalize_success_atomic
    )
    require(
        current_finalizer_source.count("persist_private_episode_candidate(") == 1
        and LIVE_V03_IMPLEMENTATION_MANIFEST.get("retention_path")
        == "service.durable.persist_private_episode_candidate(connection)"
        and LIVE_V03_IMPLEMENTATION_MANIFEST.get("fresh_solve_immediate_carryover") is False,
        "M1 behavior-preserving shared-helper/no-immediate-carryover lock drift",
    )
    require(
        m1.get("description") == "CURRENT_V03_MEMORY"
        and m1.get("baseline_git_commit") == LIVE_V03_IMPLEMENTATION_MANIFEST["source_commit"]
        and m1.get("live_implementation_hash") == LIVE_V03_IMPLEMENTATION_HASH
        and m1.get("production_lifecycle_configuration_hash")
        == PostgresV03ExperienceLifecycle.configuration_hash,
        "M1 live-v0.3 implementation/configuration lock drift",
    )
    require(
        m1.get("retained_episode_shape")
        == ["task_id", "repo_id", "commit", "outcome", "injected_memory_ids"]
        and m1.get("fresh_solve_episode_private_view")
        == "NOT_INDEXED_BY_CURRENT_SOLVE_PATH"
        and m1.get("fresh_solve_immediate_carryover") is False
        and m1.get("candidate_outbox_event_type") == "CONTRACT_CANDIDATE"
        and "no direct Qdrant indexing" in str(m1.get("retention_path"))
        and m1.get("extractor_output_changes_retention") is False
        and m1.get("benchmark_grade_changes_retention") is False
        and m1.get("shared_publication") is False,
        "M1 solve-worker retention/private-view fidelity contract drift",
    )
    m1_lifecycle_source = inspect.getsource(production_v03_lifecycle_factory)
    m1_controller_source = inspect.getsource(production_v03_controller_factory)
    require(
        "LiveV03Runtime" in m1_lifecycle_source
        and "CurrentV03MemoryController" in m1_controller_source
        and "runtime.recall_plan" in m1_controller_source
        and all(
            callable(getattr(LiveV03Runtime, name, None))
            for name in (
                "retention_descriptor", "retain_episode", "recall_plan",
                "verify_pending_retention",
            )
        )
        and callable(
            getattr(PostgresV03ExperienceLifecycle, "verify_inflight_external_state", None)
        )
        and CurrentV03MemoryController.__name__ == "CurrentV03MemoryController",
        "M1 live validated-search/injection/recovery route is incomplete",
    )

    tool = read_json(CONFIG / "tool_environment_lock.json")
    require(tool.get("status") == "FROZEN", "tool environment lock is not frozen")
    require(tool.get("runtime_lock_manifest") == RuntimeLock().to_manifest() and tool.get("runtime_lock_content_hash") == RuntimeLock().content_hash, "tool/runtime lock drift")
    for relative, expected in tool.get("source_files", {}).items():
        path = ROOT / relative
        require(path.is_file() and len(path.read_bytes()) == expected.get("bytes") and hashlib.sha256(path.read_bytes()).hexdigest() == expected.get("sha256"), f"tool source lock drift: {relative}")
    docker = tool.get("docker_command_runner", {})
    require((docker.get("container_workspace"), docker.get("pull"), docker.get("network"), docker.get("root_filesystem"), docker.get("host_environment_forwarded_to_container")) == ("/testbed", "never", "none", "read-only", False), "production command sandbox lock drift")
    require(tool.get("benchmark_workspace", {}).get("all_tasks_require_digest_bound_command_runner") is True, "production workspace can omit command runner")

    required_methods = ("after_task_and_checkpoint", "resume_canonical_stream", "finalize_development", "run_coroutine")
    require(all(callable(getattr(BenchmarkArmSession, name, None)) for name in required_methods), "production session lifecycle/resume surface is incomplete")
    require(callable(open_benchmark_arm), "production benchmark factory is missing")
    require(
        DockerSandboxCommandRunner.__name__ == "DockerSandboxCommandRunner"
        and getattr(GitCheckoutWorkspaceFactory, "production_capable", None)
        is not True,
        "workspace factory production capability must be instance-bound to complete runners",
    )
    runtime_source = inspect.getsource(TriMemAgentRuntime.run)
    require(all(state in runtime_source for state in ("PATCH_FINALIZED", "GRADED", "EXTRACTED", "LIFECYCLE_STORED", "LIFECYCLE_CREDITED", "DONE")), "terminal checkpoint phase set is incomplete")
    require(all(item is not None for item in (AtomicBudgetLedger, BudgetedModelGateway, JournaledModelGateway, JournaledGraderGateway)), "budget/journal execution boundary is missing")
    benchmark_source = (ROOT / "scripts/trimem_benchmark_run.py").read_text(encoding="utf-8")
    aggregate_source = (ROOT / "scripts/trimem_benchmark_matrix.py").read_text(encoding="utf-8")
    require(callable(seed_benchmark_identities) and "os.environ.pop(\"TRIMEM_ADMIN_DATABASE_URL\"" in benchmark_source and "identity_seed_evidence=" in benchmark_source, "admin-only deterministic benchmark identity seed boundary is missing")
    require(
        '\"benchmark_id\": target[\"benchmark_id\"]' in benchmark_source
        and "_benchmark_endpoint_totals" in aggregate_source
        and "DESCRIPTIVE_POOLED_ALL_BENCHMARKS" in aggregate_source,
        "per-benchmark primary/secondary endpoint aggregation is not frozen",
    )


def validate_smoke_environment_protection(environment: Mapping[str, Any]) -> None:
    """Require the exact protected-environment snapshot for both smoke routes."""

    push_branch = SMOKE_ATTESTATION_SOURCE_REF_BY_EVENT["push"].removeprefix(
        "refs/heads/"
    )
    dispatch_branch = SMOKE_ATTESTATION_SOURCE_REF_BY_EVENT[
        "workflow_dispatch"
    ].removeprefix("refs/heads/")
    expected = {
        "branch_policies": {
            "branch_policies": [
                {"id": 58766765, "name": push_branch, "type": "branch"},
                {"id": 58775497, "name": dispatch_branch, "type": "branch"},
            ],
            "total_count": 2,
        },
        "configured_before_sentinel": True,
        "deployment_branch_policy": {
            "custom_branch_policies": True,
            "protected_branches": False,
        },
        "environment": {
            "can_admins_bypass": False,
            "id": 20971935382,
            "name": "trimem-grader-smoke-exec",
        },
        "observed_at_utc": "2026-09-01T04:18:06Z",
        "protection_rule": {
            "id": 64238011,
            "prevent_self_review": False,
            "reviewers": [{"id": 95427459, "login": "Scuttie", "type": "User"}],
            "type": "required_reviewers",
        },
        "repository": SMOKE_ATTESTATION_REPOSITORY,
        "schema": "trimem/grader-smoke-environment-protection/1.1",
        "secret_state_before_sentinel": {
            "installed_secret_names": [],
            "required_later": [
                "TRIMEM_EVIDENCE_PASSPHRASE",
                "TRIMEM_EXEC_APPROVAL_B64",
            ],
            "total_count": 0,
        },
        "source_api_paths": [
            (
                "repos/Scuttie/enterprise-shared-memory-poc/environments/"
                "trimem-grader-smoke-exec"
            ),
            (
                "repos/Scuttie/enterprise-shared-memory-poc/environments/"
                "trimem-grader-smoke-exec/deployment-branch-policies"
            ),
            (
                "repos/Scuttie/enterprise-shared-memory-poc/environments/"
                "trimem-grader-smoke-exec/secrets"
            ),
        ],
        "status": "CONFIGURED",
    }
    require(
        dict(environment) == expected,
        "grader-smoke protected environment snapshot/route policy set differs",
    )


def validate_workflows() -> None:
    automatic = [ROOT / ".github/workflows/ci-trimem.yml", ROOT / ".github/workflows/ci-trimem-e2e.yml"]
    portability = ROOT / ".github/workflows/ci-trimem-harness-lock.yml"
    smoke_workflow = ROOT / ".github/workflows/trimem-grader-smoke.yml"
    benchmark_workflow = ROOT / ".github/workflows/trimem-benchmark.yml"
    manual = [smoke_workflow, benchmark_workflow]
    for path in [*automatic, portability, *manual]:
        text = path.read_text(encoding="utf-8")
        for forbidden in ("continue-on-error", "|| true", ":latest"):
            require(forbidden not in text, f"forbidden workflow construct {forbidden}: {path.name}")
        require("inputs:" not in text, f"workflow has free-form inputs: {path.name}")
        for match in re.finditer(r"uses:\s*([^\s]+)", text):
            require(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", match.group(1)) is not None, f"workflow action is not commit-pinned: {path.name}")
    for path in automatic:
        text = path.read_text(encoding="utf-8")
        require("pull_request:" in text and "trimem_pytest_no_skip.py" in text, f"automatic no-skip PR CI missing: {path.name}")
    static = automatic[0].read_text(encoding="utf-8")
    require("tests/unit/test_trimem_*.py" in static and "tests/trimem/e2e/test_full_replay.py" in static, "static CI does not discover all TriMem units/full replay")
    service = automatic[1].read_text(encoding="utf-8")
    require("test_real_services_e2e.py" in service and "postgres@sha256:" in service and "qdrant/qdrant@sha256:" in service, "real PostgreSQL/Qdrant CI is absent")
    require("postgres_bootstrap.py" in service and "TRIMEM_TEST_DATABASE_URL: postgresql+asyncpg://api_service:api_pw@" in service and "TRIMEM_TEST_ADMIN_DATABASE_URL: postgresql+asyncpg://postgres:postgres@" in service, "real-service role/RLS boundary is not wired")
    portable = portability.read_text(encoding="utf-8")
    require(
        "pull_request:" in portable
        and "runner: ubuntu-24.04" in portable
        and "runner: windows-2025" in portable
        and "core_autocrlf: input" in portable
        and 'core_autocrlf: "true"' in portable
        and "rehearsal_arg: --blob-only" in portable
        and "trimem_harness_lock.py" in portable
        and "environment:" not in portable
        and "secrets." not in portable,
        "cross-platform credential-free harness-lock rehearsal differs",
    )
    smoke = smoke_workflow.read_text(encoding="utf-8")
    require("workflow_dispatch:" in smoke and "pull_request:" not in smoke and "schedule:" not in smoke, "smoke workflow has an unauthorized trigger")
    require(
        "push:" in smoke
        and "      - codex/trimem-coder-v1" in smoke
        and f"      - {GRADER_SMOKE_SENTINEL_PATH}" in smoke
        and "      - artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST.json" not in smoke,
        "smoke workflow exact branch-local sentinel trigger is absent",
    )
    require(
        "branch-trigger-preflight:" in smoke
        and "needs: branch-trigger-preflight" in smoke
        and "trimem_grader_smoke_trigger_preflight.py" in smoke,
        "smoke branch trigger is not fail-closed before the protected job",
    )
    require(
        "concurrency:\n  group: trimem-v1-grader-smoke-exec-003\n"
        "  cancel-in-progress: false" in smoke,
        "smoke recovery concurrency contract differs",
    )
    require(
        "environment: trimem-grader-smoke-exec" in smoke,
        "smoke job is not held by the protected environment",
    )
    require(
        "github.ref == 'refs/heads/main'" in smoke
        and smoke.count(SMOKE_ATTESTATION_ACTION) == 1
        and "permissions:\n      attestations: write\n      contents: read\n      id-token: write"
        in smoke
        and "create-storage-record: false" in smoke
        and "push-to-registry: false" in smoke
        and "subject-path: ${{ runner.temp }}/attestation-subject.json"
        in smoke
        and "trimem_smoke_attestation.py" in smoke
        and "trimem-grader-smoke-attestation-bundle.json" in smoke
        and "name: trimem-grader-smoke-attestation-bundle" in smoke,
        "smoke GitHub-hosted attestation action/permissions/artifact path differs",
    )
    upload_public = smoke.find("- name: Upload public smoke result")
    upload_inventory = smoke.find(
        "- name: Upload non-sensitive restricted evidence inventory"
    )
    upload_encrypted = smoke.find("- name: Upload encrypted restricted evidence")
    cleanup_before_signing = smoke.find(
        "- name: Remove plaintext and temporary EXEC material before signing"
    )
    attest = smoke.find(
        "- name: Attest exact uploaded and cleaned official smoke subject"
    )
    upload_bundle = smoke.find("- name: Upload official smoke attestation bundle")
    require(
        -1
        not in {
            upload_public, upload_inventory, upload_encrypted,
            cleanup_before_signing, attest, upload_bundle,
        }
        and upload_public
        < upload_inventory
        < upload_encrypted
        < cleanup_before_signing
        < attest
        < upload_bundle
        and "if: always()" not in smoke[attest:upload_bundle],
        "smoke upload/cleanup/signing order can attest an incomplete or red execution",
    )
    smoke_secrets = set(
        re.findall(r"\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)", smoke)
    )
    require(
        smoke_secrets
        == {"TRIMEM_EXEC_APPROVAL_B64", "TRIMEM_EVIDENCE_PASSPHRASE"},
        "smoke workflow secret surface is not the exact control/evidence pair",
    )
    benchmark_text = benchmark_workflow.read_text(encoding="utf-8")
    require(
        "workflow_dispatch:" in benchmark_text
        and all(
            trigger not in benchmark_text
            for trigger in ("pull_request:", "push:", "schedule:")
        ),
        "benchmark EXEC workflow is not manual-only",
    )
    gate_start = benchmark_text.find("- name: Verify exact phase EXEC gate")
    gate_end = benchmark_text.find("- name: Apply exact migration head")
    require(
        "permissions:\n  actions: read\n  contents: read" in benchmark_text
        and benchmark_text.count("GH_TOKEN: ${{ github.token }}") == 1
        and 0 <= gate_start < gate_end
        and "GH_TOKEN: ${{ github.token }}"
        in benchmark_text[gate_start:gate_end],
        "benchmark live-run gate lacks least-privilege Actions read token scope",
    )
    for path in manual:
        text = path.read_text(encoding="utf-8")
        require("trimem_public_artifact.py" in text and "openssl enc -aes-256-cbc" in text, f"EXEC evidence protection path incomplete: {path.name}")
        require("if: always()" in text and "trimem_cleanup_exec.py" in text, f"EXEC plaintext cleanup path is absent: {path.name}")
    require(
        "bounded-disk exact GOLD and NOOP_BASELINE pairs" in smoke
        and smoke.count(
            "--image-evidence-dir artifacts/trimem_v1/grader_smoke_exec/image-materialization"
        ) == 2
        and "--cleanup-grader-smoke" in smoke
        and "Remove only frozen smoke image references" in smoke,
        "smoke workflow does not use bounded-disk serial image materialization",
    )
    benchmark = manual[1].read_text(encoding="utf-8")
    require("trimem_pull_locked_images.py" in benchmark, "benchmark digest-only image pull is absent")
    require("runs-on: [self-hosted, linux, x64, ubuntu-24.04, trimem-benchmark]" in benchmark and "timeout-minutes: 7200" in benchmark, "long serial benchmark is not on protected 5-day runner")
    require("matrix:" not in benchmark, "online benchmark is incorrectly task/arm sharded")
    require("trimem_run_with_resume.py" in benchmark and "trimem_benchmark_run.py\n" not in benchmark, "same-attempt benchmark recovery wrapper is not the workflow entrypoint")
    require("postgres_bootstrap.py" in benchmark and "TRIMEM_DATABASE_URL: postgresql+asyncpg://api_service:api_pw@" in benchmark and "TRIMEM_ADMIN_DATABASE_URL: postgresql+asyncpg://postgres:postgres@" in benchmark, "benchmark admin/runtime RLS identities are not separated")
    environment = read_json(
        ARTIFACT / "grader_smoke_environment_protection.json"
    )
    validate_smoke_environment_protection(environment)


def validate_eol_policy() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    require("scripts/trimem_*.py text eol=lf" in attributes and "configs/trimem_v1/** text eol=lf" in attributes, "cross-platform LF freeze policy is absent")
    representative = (
        ".gitattributes", ".gitignore", "alembic.ini", "DEPENDENCY_PROVENANCE.json", "requirements.lock",
        "pyproject.toml", "configs/trimem_v1/model_lock.json", "scripts/trimem_freeze.py",
        "scripts/check_migration_head.py", "docs/TRIMEM_V1_SYSTEM.md",
        ".github/workflows/ci-trimem.yml", "migrations/env.py",
        "migrations/sql/0001_up.sql", "migrations/versions/0001_initial_production_schema.py",
        "src/enterprise_memory/providers/openai_responses.py",
        "src/enterprise_memory/providers/base.py",
        "src/enterprise_memory/providers/redaction.py",
        "src/enterprise_memory/indexing/embeddings.py",
        "src/enterprise_memory/indexing/validated_search.py",
        "src/enterprise_memory/service/injection.py",
        "src/enterprise_memory/service/app.py", "src/enterprise_memory/trimem/agent_runtime.py",
        "tests/openai/test_openai_provider.py", "tests/unit/test_release_hygiene.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
    )
    completed = subprocess.run(
        ["git", "check-attr", "eol", "--", *representative],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    require(completed.returncode == 0 and completed.stdout.count("eol: lf") == len(representative), "git LF attributes do not cover frozen text")
    blobs = sorted((ARTIFACT / "credential_free_e2e").glob("*/evidence/blobs/*"))
    require(bool(blobs), "credential-free content-addressed evidence blobs are missing")
    blob_relative = blobs[0].relative_to(ROOT).as_posix()
    blob_attr = subprocess.run(
        ["git", "check-attr", "text", "--", blob_relative], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    require(blob_attr.returncode == 0 and "text: unset" in blob_attr.stdout, "content-addressed evidence blobs are not binary-stable")


def validate_static(require_git_tracked: bool) -> dict[str, Any]:
    check_freeze(ROOT, require_git_tracked=require_git_tracked)
    validate_smoke_attestation_policy()
    validate_eol_policy()
    validate_sources()
    targets = validate_targets()
    validate_readiness_plan(targets)
    validate_images(targets)
    validate_noop_baseline_audit(targets)
    validate_model_cost_environment()
    validate_runtime_and_candidates()
    validate_workflows()
    credential = verify_bundle(ARTIFACT / "credential_free_e2e")
    request = read_json(CONFIG / "benchmark_exec_request.json")
    require(request.get("approval_state") == "PENDING_EXEC_APPROVAL", "committed request must stay pending")
    request_actual = request.get("actual_execution")
    require(
        isinstance(request_actual, dict)
        and all(type(value) is int for value in request_actual.values())
        and request_actual == {
            "benchmark_target_image_pulls": 0,
            "grader_containers": 0,
            "official_grader_runs": 0,
            "paid_model_calls": 0,
            "task_arm_runs": 0,
        },
        "committed preapproval execution counter schema/value differs",
    )
    prohibited = request.get("prohibited_before_approval", [])
    require(
        "official grader/benchmark target image pull or run" in prohibited
        and "Docker image pull or run" not in prohibited,
        "pre-EXEC prohibition incorrectly blocks credential-free support-service CI",
    )
    required = set(request.get("required_approval_fields", ()))
    require({"approved_workflow_run_id", "approved_workflow_run_attempt"} <= required, "single-dispatch EXEC approval binding is absent")
    smoke = read_json(ARTIFACT / "grader_smoke_result.json")
    smoke_actual = validate_grader_smoke_result(smoke)
    return {
        "credential_free_bundle_hash": credential["bundle_hash"],
        "development_physical_runs": 72,
        "heldout_physical_runs": 81,
        "support_image_digests_frozen": 1,
        "target_image_digests_frozen": 45,
        "model_calls": smoke_actual["model_calls"],
        "official_grader_runs": smoke_actual["official_grader_runs"],
        "paid_model_calls": smoke_actual["paid_model_calls"],
        "grader_exec_package": smoke["grader_exec_package"],
        "official_grader_viability": smoke["official_grader_viability"],
        "performance": smoke["performance"],
    }


def preapproval_blockers() -> list[str]:
    blockers = []
    selected = validate_selected_m2(require_frozen=False)
    if selected.get("status") != "PRE_DEVELOPMENT":
        blockers.append("pre-development selection placeholder is not exact")
    smoke = read_json(ARTIFACT / "grader_smoke_result.json")
    try:
        validate_grader_smoke_result(smoke)
    except (OSError, ValueError) as exc:
        blockers.append(f"grader-smoke evidence validation failed: {exc}")
    request = read_json(CONFIG / "benchmark_exec_request.json")
    if request.get("approval_state") != "PENDING_EXEC_APPROVAL":
        blockers.append("committed external approval request is not pending")
    return blockers


def execution_blockers(approval_file: Path) -> tuple[list[str], str | None]:
    try:
        document = read_json(approval_file)
        phase = document.get("approval", {}).get("approved_phase")
        name = {"GRADER_SMOKE": "grader-smoke", "DEVELOPMENT_TUNING": "development", "HELDOUT_BENCHMARK": "heldout"}.get(phase)
        if name is None:
            return ["external approval phase is unknown"], None
        validate_exec_approval(name, approval_file)
    except (OSError, ValueError) as exc:
        return [str(exc)], None
    smoke = read_json(ARTIFACT / "grader_smoke_result.json")
    if name in {"development", "heldout"}:
        try:
            validate_grader_smoke_result(smoke)
        except (OSError, ValueError) as exc:
            return [f"official grader smoke evidence is invalid: {exc}"], name
        if smoke.get("status") != "PASS":
            return ["official GOLD+NOOP_BASELINE smoke PASS is required before benchmark execution"], name
        try:
            verify_official_smoke_attestation_cryptographically()
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return [f"official grader smoke attestation verification failed: {exc}"], name
    selected = validate_selected_m2(require_frozen=False)
    if name == "development" and selected.get("status") != "PRE_DEVELOPMENT":
        return ["development requires the exact PRE_DEVELOPMENT selection state"], name
    if name == "heldout":
        try:
            validate_selected_m2(require_frozen=True)
        except ValueError as exc:
            return [str(exc)], name
    return [], name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", choices=("static", "benchmark-approval", "grader-smoke-exec", "benchmark-exec"), default="static")
    parser.add_argument("--require-git-tracked", action="store_true")
    parser.add_argument("--approval-file", type=Path)
    args = parser.parse_args()
    try:
        # Every approval or execution endpoint must prove that the entire
        # frozen closure is committed.  The flag remains useful for strict
        # local static checks, but cannot weaken an approval-level gate when
        # omitted by a caller.
        require_git_tracked = args.require_git_tracked or args.level != "static"
        evidence = validate_static(require_git_tracked)
        blockers: list[str] = []
        phase = None
        if args.level == "benchmark-approval":
            blockers = preapproval_blockers()
        elif args.level in {"grader-smoke-exec", "benchmark-exec"}:
            if args.approval_file is None:
                blockers = ["external immutable approval file is required"]
            else:
                blockers, phase = execution_blockers(args.approval_file.resolve())
            if args.level == "grader-smoke-exec" and phase not in {None, "grader-smoke"}:
                blockers.append("grader-smoke gate received a non-smoke approval")
            if args.level == "benchmark-exec" and phase not in {None, "development", "heldout"}:
                blockers.append("benchmark gate received a non-benchmark approval")
        committed_package = evidence.get(
            "grader_exec_package", "CORRECTION_IN_PROGRESS"
        )
        committed_viability = evidence.get(
            "official_grader_viability", "NOT_YET_ESTABLISHED"
        )
        report = {
            **evidence,
            "blockers": blockers,
            "level": args.level,
            "approved_phase": phase,
            "git_tracked_freeze_required": require_git_tracked,
            "grader_exec_package": committed_package,
            "official_grader_viability": committed_viability,
            "performance": evidence.get("performance", "NOT_MEASURED"),
            "status": "PASS" if not blockers else "FAIL_CLOSED",
            "trimem_system_implementation": "CREDENTIAL_FREE_GREEN",
        }
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if not blockers else 1
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "level": args.level, "status": "FAIL"}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
