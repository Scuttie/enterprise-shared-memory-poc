"""Build the deterministic subject for the protected official smoke attestation.

The subject is intentionally small and public.  It binds the exact public
result, non-sensitive evidence inventory, encrypted restricted evidence, and
the immutable external approval/run/source identity.  Signing is delegated to
GitHub's pinned ``actions/attest`` action; this module never creates or accepts
an unsigned success claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from trimem_benchmark_run import validate_exec_approval


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "trimem/grader-smoke-attestation-subject/1.0"
EXPECTED_REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
SIGNER_WORKFLOW_PATH = ".github/workflows/trimem-grader-smoke.yml"
HOSTED_RUNNER = "github-hosted"
SOURCE_REF_BY_EVENT = {
    "push": "refs/heads/codex/trimem-coder-v1",
    "workflow_dispatch": "refs/heads/main",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
POSITIVE_INTEGER = re.compile(r"^[1-9][0-9]*$")
APPROVAL_FIELDS = {
    "approval_artifact_sha256",
    "approved_request_sha256",
    "approved_workflow_run_id",
    "approved_workflow_run_attempt",
    "freeze_sha256",
    "git_head",
    "phase",
}


class AttestationSubjectError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AttestationSubjectError(message)


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise AttestationSubjectError(f"duplicate JSON key in {path.name}: {key}")
            value[key] = child
        return value

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AttestationSubjectError(f"invalid UTF-8 JSON: {path}") from exc
    _require(isinstance(value, dict), f"JSON root is not an object: {path}")
    return value


def _artifact(path: Path, *, name: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AttestationSubjectError(f"required attestation input is missing: {name}") from exc
    _require(bool(raw), f"required attestation input is empty: {name}")
    return {
        "bytes": len(raw),
        "name": name,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _approval_binding(validated: dict[str, Any]) -> dict[str, str]:
    value = {
        "approval_artifact_sha256": validated["approval_artifact_sha256"],
        "approved_request_sha256": validated["approved_request_sha256"],
        "approved_workflow_run_id": validated["approved_workflow_run_id"],
        "approved_workflow_run_attempt": validated["approved_workflow_run_attempt"],
        "freeze_sha256": validated["freeze_sha256"],
        "git_head": validated["git_head"],
        "phase": validated["phase"],
    }
    _require(set(value) == APPROVAL_FIELDS, "approval binding field set differs")
    return value


def build_subject(
    *,
    public_result: Path,
    evidence_inventory: Path,
    encrypted_evidence: Path,
    approval_file: Path,
    repository: str,
    source_ref: str,
    event_name: str,
    source_digest: str,
    run_id: str,
    run_attempt: str,
    runner_environment: str,
) -> dict[str, Any]:
    _require(repository == EXPECTED_REPOSITORY, "attestation repository differs")
    _require(
        SOURCE_REF_BY_EVENT.get(event_name) == source_ref,
        "attestation event/source ref route differs",
    )
    _require(HEX40.fullmatch(source_digest) is not None, "attestation source digest is invalid")
    _require(POSITIVE_INTEGER.fullmatch(run_id) is not None, "attestation run ID is invalid")
    _require(
        POSITIVE_INTEGER.fullmatch(run_attempt) is not None,
        "attestation run attempt is invalid",
    )
    _require(runner_environment == HOSTED_RUNNER, "smoke attestation requires a GitHub-hosted runner")

    validated = validate_exec_approval("grader-smoke", approval_file)
    approval = _approval_binding(validated)
    _require(approval["git_head"] == source_digest, "approval/source digest differs")
    _require(approval["approved_workflow_run_id"] == run_id, "approval/run ID differs")
    _require(
        approval["approved_workflow_run_attempt"] == run_attempt,
        "approval/run attempt differs",
    )
    public = _strict_json(public_result)
    _require(public.get("status") == "PASS", "only a passed public smoke result may be attested")
    _require(public.get("approval_binding") == approval, "public/attestation approval differs")

    return {
        "approval_binding": approval,
        "artifacts": {
            "encrypted_restricted_evidence": _artifact(
                encrypted_evidence,
                name="trimem-grader-smoke-restricted.tar.enc",
            ),
            "evidence_inventory": _artifact(
                evidence_inventory,
                name="evidence-inventory.json",
            ),
            "public_results": _artifact(
                public_result,
                name="public-results.json",
            ),
        },
        "execution": {
            "event_name": event_name,
            "repository": repository,
            "runner_environment": runner_environment,
            "signer_workflow": SIGNER_WORKFLOW_PATH,
            "source_digest": source_digest,
            "source_ref": source_ref,
            "workflow_run_attempt": run_attempt,
            "workflow_run_id": run_id,
        },
        "schema": SCHEMA,
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-result", type=Path, required=True)
    parser.add_argument("--evidence-inventory", type=Path, required=True)
    parser.add_argument("--encrypted-evidence", type=Path, required=True)
    parser.add_argument("--approval-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--source-ref", default=os.environ.get("GITHUB_REF", ""))
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    parser.add_argument("--source-digest", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--run-attempt", default=os.environ.get("GITHUB_RUN_ATTEMPT", ""))
    parser.add_argument(
        "--runner-environment", default=os.environ.get("RUNNER_ENVIRONMENT", "")
    )
    args = parser.parse_args()
    try:
        subject = build_subject(
            public_result=args.public_result.resolve(),
            evidence_inventory=args.evidence_inventory.resolve(),
            encrypted_evidence=args.encrypted_evidence.resolve(),
            approval_file=args.approval_file.resolve(),
            repository=args.repository,
            source_ref=args.source_ref,
            event_name=args.event_name,
            source_digest=args.source_digest,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            runner_environment=args.runner_environment,
        )
        _write_json(args.output.resolve(), subject)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
