"""Verify successful- or failed-campaign GitHub artifact custody fail closed."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Mapping, Sequence


SUCCESS_MARKER = "TRIMEM_EXTERNAL_ARTIFACT_CUSTODY_PASS"
FAILURE_MARKER = "TRIMEM_FAILURE_EVIDENCE_CUSTODY_PASS"
SCHEMA = "trimem/remote-artifact-custody/1.0"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
POSITIVE_INTEGER = re.compile(r"^[1-9][0-9]*$")


class RemoteCustodyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArtifactBinding:
    label: str
    name: str
    artifact_id: str
    digest: str


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv), capture_output=True, check=False, text=True
    )


def verify_artifact(
    binding: ArtifactBinding,
    *,
    repository: str,
    workflow_run_id: int,
    runner: Runner = _default_runner,
) -> dict[str, Any]:
    if not POSITIVE_INTEGER.fullmatch(binding.artifact_id):
        raise RemoteCustodyError(f"{binding.label} artifact-id is not canonical")
    if not SHA256.fullmatch(binding.digest):
        raise RemoteCustodyError(
            f"{binding.label} artifact-digest is not a SHA-256 hex digest"
        )
    completed = runner(
        [
            "gh",
            "api",
            "--method",
            "GET",
            f"repos/{repository}/actions/artifacts/{binding.artifact_id}",
        ]
    )
    if completed.returncode != 0:
        raise RemoteCustodyError(
            f"{binding.label} artifact is not remotely retrievable"
        )
    try:
        remote = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RemoteCustodyError(
            f"{binding.label} artifact metadata is invalid JSON"
        ) from exc
    workflow_run = remote.get("workflow_run") if isinstance(remote, Mapping) else None
    if (
        not isinstance(remote, Mapping)
        or remote.get("id") != int(binding.artifact_id)
        or remote.get("name") != binding.name
        or remote.get("expired") is not False
        or type(remote.get("size_in_bytes")) is not int
        or remote["size_in_bytes"] <= 0
        or remote.get("digest") != "sha256:" + binding.digest
        or not isinstance(workflow_run, Mapping)
        or workflow_run.get("id") != workflow_run_id
    ):
        raise RemoteCustodyError(f"{binding.label} remote artifact custody differs")
    return {
        **asdict(binding),
        "size_in_bytes": remote["size_in_bytes"],
        "workflow_run_id": workflow_run_id,
        "status": "VERIFIED",
    }


def verify_remote_custody(
    *,
    repository: str,
    workflow_run_id: int,
    public_upload_outcome: str,
    public: ArtifactBinding | None,
    restricted: ArtifactBinding,
    inventory: ArtifactBinding,
    runner: Runner = _default_runner,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise RemoteCustodyError("repository identity is invalid")
    if type(workflow_run_id) is not int or workflow_run_id <= 0:
        raise RemoteCustodyError("workflow run ID is invalid")
    if public_upload_outcome not in {"success", "skipped"}:
        raise RemoteCustodyError("public upload outcome is neither success nor skipped")
    if public_upload_outcome == "success" and public is None:
        raise RemoteCustodyError("successful public upload lacks an artifact binding")
    if public_upload_outcome == "skipped" and public is not None:
        raise RemoteCustodyError("failed campaign unexpectedly supplied a public artifact")

    verified = [
        verify_artifact(
            restricted,
            repository=repository,
            workflow_run_id=workflow_run_id,
            runner=runner,
        ),
        verify_artifact(
            inventory,
            repository=repository,
            workflow_run_id=workflow_run_id,
            runner=runner,
        ),
    ]
    if public is not None:
        verified.insert(
            0,
            verify_artifact(
                public,
                repository=repository,
                workflow_run_id=workflow_run_id,
                runner=runner,
            ),
        )
    failure_path = public_upload_outcome == "skipped"
    return {
        "schema": SCHEMA,
        "status": FAILURE_MARKER if failure_path else SUCCESS_MARKER,
        "campaign_result_available": not failure_path,
        "public_artifact": "ABSENT_EXPECTED" if failure_path else "VERIFIED",
        "encrypted_restricted_artifact": "VERIFIED",
        "inventory_artifact": "VERIFIED",
        "workflow_run_id": workflow_run_id,
        "repository": repository,
        "verified_artifacts": verified,
    }


def _binding(
    label: str, name: str, artifact_id: str | None, digest: str | None
) -> ArtifactBinding | None:
    if artifact_id in {None, ""} and digest in {None, ""}:
        return None
    return ArtifactBinding(
        label=label,
        name=name,
        artifact_id=artifact_id or "",
        digest=digest or "",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow-run-id", type=int, required=True)
    parser.add_argument(
        "--public-upload-outcome", choices=("success", "skipped"), required=True
    )
    parser.add_argument("--public-artifact-id")
    parser.add_argument("--public-artifact-digest")
    parser.add_argument("--restricted-artifact-id", required=True)
    parser.add_argument("--restricted-artifact-digest", required=True)
    parser.add_argument("--inventory-artifact-id", required=True)
    parser.add_argument("--inventory-artifact-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_remote_custody(
            repository=args.repository,
            workflow_run_id=args.workflow_run_id,
            public_upload_outcome=args.public_upload_outcome,
            public=_binding(
                "PUBLIC",
                "trimem-benchmark-public",
                args.public_artifact_id,
                args.public_artifact_digest,
            ),
            restricted=ArtifactBinding(
                "RESTRICTED",
                "trimem-benchmark-restricted-encrypted",
                args.restricted_artifact_id,
                args.restricted_artifact_digest,
            ),
            inventory=ArtifactBinding(
                "INVENTORY",
                "trimem-benchmark-evidence-inventories",
                args.inventory_artifact_id,
                args.inventory_artifact_digest,
            ),
        )
    except RemoteCustodyError as exc:
        result = {"schema": SCHEMA, "status": "FAIL", "error": str(exc)}
        args.output.write_bytes(canonical_bytes(result) + b"\n")
        print(json.dumps(result, sort_keys=True))
        return 1
    args.output.write_bytes(canonical_bytes(result) + b"\n")
    print(json.dumps(result, sort_keys=True))
    print(result["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
