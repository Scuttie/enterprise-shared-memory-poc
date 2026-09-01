"""Approval-gated pull and local observation of committed grader images only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from trimem_benchmark_run import (  # noqa: E402
    BenchmarkExecutionError,
    image_entries,
    read_json,
    sha256_bytes,
    strict_json_loads,
    validate_exec_approval,
    write_json,
)
from trimem_grader_smoke_protocol import (  # noqa: E402
    SmokeProtocolError,
    validate_serial_targets,
)


MANIFESTS = {
    "grader-smoke": ROOT / "configs/trimem_v1/grader_smoke_manifest.json",
    "development": ROOT / "configs/trimem_v1/development_manifest.json",
    "heldout": ROOT / "configs/trimem_v1/heldout_manifest.json",
}


def _stream_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _save_raw(
    root: Path, index: int, stage: str, *, argv: list[str], stdout: str,
    stderr: str, status: str, returncode: int | None,
) -> dict[str, Any]:
    stage_root = root / f"{index:03d}-{stage}"
    stage_root.mkdir(parents=True, exist_ok=True)
    refs = {}
    for name, value in (("stdout", stdout), ("stderr", stderr)):
        path = stage_root / f"{name}.txt"
        path.write_text(value, encoding="utf-8", newline="\n")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        raw = path.read_bytes()
        refs[name] = {"path": path.relative_to(root).as_posix(), "sha256": sha256_bytes(raw), "bytes": len(raw)}
    write_json(stage_root / "stage.json", {
        "argv": argv, "returncode": returncode, "stage": stage, "status": status,
        "stdout": refs["stdout"], "stderr": refs["stderr"],
    })
    return refs


def _run(
    argv: list[str], root: Path, index: int, stage: str
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, check=False, timeout=3600
        )
    except subprocess.TimeoutExpired as exc:
        refs = _save_raw(
            root, index, stage, argv=argv,
            stdout=_stream_text(exc.stdout), stderr=_stream_text(exc.stderr),
            status="TIMEOUT", returncode=None,
        )
        raise BenchmarkExecutionError(f"Docker {stage} timed out after 3600 seconds") from exc
    except OSError as exc:
        refs = _save_raw(
            root, index, stage, argv=argv, stdout="",
            stderr=f"{type(exc).__name__}: {exc}", status="LAUNCH_FAILURE",
            returncode=None,
        )
        raise BenchmarkExecutionError(f"Docker {stage} could not be launched") from exc
    refs = _save_raw(
        root, index, stage, argv=argv, stdout=completed.stdout,
        stderr=completed.stderr, status="PASS" if completed.returncode == 0 else "NONZERO",
        returncode=completed.returncode,
    )
    return completed, refs


def selected_images(phase: str) -> list[str]:
    manifest = read_json(MANIFESTS[phase])
    targets = manifest.get("targets")
    if not isinstance(targets, list) or not targets:
        raise BenchmarkExecutionError("committed image-pull manifest has no targets")
    images, support = image_entries(require_benchmark=phase != "grader-smoke")
    selected = []
    for row in targets:
        instance_id = row.get("instance_id")
        if instance_id not in images:
            raise BenchmarkExecutionError(f"frozen image is missing: {instance_id}")
        selected.append(images[instance_id]["image"])
    if any(row.get("benchmark_id", "").startswith("multi_swe_bench") for row in targets):
        selected.extend(image for image, _ in support)
    unique = list(dict.fromkeys(selected))
    if any("@sha256:" not in image or image.endswith("@sha256:" + "0" * 64) for image in unique):
        raise BenchmarkExecutionError("image pull set contains an unfrozen digest")
    return unique


def pull_and_observe_image(
    image: str, evidence_root: Path, index: int
) -> dict[str, Any]:
    """Materialize one exact digest and preserve its complete pull/inspect streams."""

    if "@sha256:" not in image or image.endswith("@sha256:" + "0" * 64):
        raise BenchmarkExecutionError("image materialization requires one frozen digest")
    expected = image.rsplit("@", 1)[1]
    pulled, pull_refs = _run(
        ["docker", "pull", image], evidence_root, index, "pull"
    )
    if pulled.returncode != 0:
        raise BenchmarkExecutionError(f"digest-only Docker pull failed: {image}")
    inspected, inspect_refs = _run(
        ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image],
        evidence_root,
        index,
        "inspect",
    )
    if inspected.returncode != 0:
        raise BenchmarkExecutionError(f"Docker image inspect failed: {image}")
    try:
        repo_digests = strict_json_loads(inspected.stdout.strip())
    except (json.JSONDecodeError, ValueError) as exc:
        raise BenchmarkExecutionError(
            f"Docker image inspect returned invalid JSON: {image}"
        ) from exc
    observed = sorted(
        {str(value).rsplit("@", 1)[-1] for value in repo_digests or []}
    )
    if expected not in observed:
        raise BenchmarkExecutionError(f"observed image digest mismatch: {image}")
    return {
        "image": image,
        "expected_digest": expected,
        "observed_digests": observed,
        "pull": pull_refs,
        "inspect": inspect_refs,
    }


def remove_materialized_image(
    image: str,
    tags: list[str],
    evidence_root: Path,
    index: int,
) -> dict[str, Any]:
    """Remove only the exact digest/tag aliases after its serial smoke pair."""

    references = list(dict.fromkeys([*tags, image]))
    if (
        "@sha256:" not in image
        or not references
        or any(not value or any(char.isspace() for char in value) for value in references)
    ):
        raise BenchmarkExecutionError("image cleanup references are not exact")
    removed, refs = _run(
        ["docker", "image", "rm", "--force", *references],
        evidence_root,
        index,
        "remove",
    )
    if removed.returncode != 0:
        raise BenchmarkExecutionError(f"exact Docker image cleanup failed: {image}")
    return {
        "image": image,
        "references": references,
        "remove": refs,
        "status": "PASS",
    }


def pull_and_observe(phase: str, approval_path: Path, evidence_root: Path) -> dict[str, Any]:
    approval = validate_exec_approval(phase, approval_path)
    images = selected_images(phase)
    evidence_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, image in enumerate(images):
        rows.append(pull_and_observe_image(image, evidence_root, index))
    report = {
        "schema": "trimem/digest-only-image-materialization/1.0",
        "status": "PASS",
        "phase": approval["phase"],
        "approval_artifact_sha256": approval["approval_artifact_sha256"],
        "images": rows,
        "docker_pull_count": len(rows),
    }
    write_json(evidence_root / "image-materialization-report.json", report)
    return report


def _cleanup_reference(
    reference: str, evidence_root: Path, index: int
) -> dict[str, Any]:
    inspected, inspect_refs = _run(
        ["docker", "image", "inspect", reference],
        evidence_root,
        index,
        "cleanup-inspect",
    )
    if inspected.returncode != 0:
        missing = (
            inspected.returncode == 1
            and "no such image" in inspected.stderr.lower()
        )
        if not missing:
            raise BenchmarkExecutionError(
                f"cannot establish exact cleanup state for Docker reference: {reference}"
            )
        return {
            "reference": reference,
            "status": "ALREADY_ABSENT",
            "inspect": inspect_refs,
        }
    removed, remove_refs = _run(
        ["docker", "image", "rm", "--force", reference],
        evidence_root,
        index,
        "cleanup-remove",
    )
    if removed.returncode != 0:
        raise BenchmarkExecutionError(
            f"exact workflow cleanup failed for Docker reference: {reference}"
        )
    return {
        "reference": reference,
        "status": "REMOVED",
        "inspect": inspect_refs,
        "remove": remove_refs,
    }


def cleanup_grader_smoke_images(evidence_root: Path) -> dict[str, Any]:
    """Remove only the seven frozen smoke image digests and their harness tags."""

    manifest = read_json(MANIFESTS["grader-smoke"])
    targets = manifest.get("targets")
    try:
        validate_serial_targets(
            matrix_kind=manifest.get("matrix_kind"),
            noop_baseline=manifest.get("noop_baseline"),
            targets=targets,
        )
    except (SmokeProtocolError, TypeError) as exc:
        raise BenchmarkExecutionError(str(exc)) from exc
    images, support = image_entries(require_benchmark=False)
    if len(support) != 1:
        raise BenchmarkExecutionError("smoke cleanup requires one exact support image")
    identities = [target["instance_id"] for target in targets[0::2]]
    if len(identities) != 6 or len(set(identities)) != 6:
        raise BenchmarkExecutionError("smoke cleanup identity set is not exact")
    image_rows = [images[identity] for identity in identities]
    support_image, support_tag = support[0]
    references: list[str] = []
    for row in image_rows:
        references.extend([row["harness_image_tag"], row["image"]])
    references.extend([support_tag, support_image])
    if (
        len(references) != 14
        or len(set(references)) != 14
        or any(not isinstance(value, str) or not value for value in references)
    ):
        raise BenchmarkExecutionError("smoke cleanup references are not exact and unique")
    evidence_root.mkdir(parents=True, exist_ok=True)
    rows = [
        _cleanup_reference(reference, evidence_root, index)
        for index, reference in enumerate(references)
    ]
    report = {
        "schema": "trimem/grader-smoke-workflow-image-cleanup/1.0",
        "status": "PASS",
        "exact_reference_count": 14,
        "removed_reference_count": sum(row["status"] == "REMOVED" for row in rows),
        "already_absent_reference_count": sum(
            row["status"] == "ALREADY_ABSENT" for row in rows
        ),
        "references": rows,
    }
    write_json(evidence_root / "workflow-image-cleanup-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=tuple(MANIFESTS))
    parser.add_argument("--approval-file", type=Path)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--cleanup-grader-smoke", action="store_true")
    args = parser.parse_args()
    try:
        if args.cleanup_grader_smoke:
            if args.phase is not None or args.approval_file is not None:
                raise BenchmarkExecutionError(
                    "workflow cleanup accepts no phase or approval artifact"
                )
            report = cleanup_grader_smoke_images(args.evidence_dir.resolve())
            output = {
                "exact_references": report["exact_reference_count"],
                "status": report["status"],
            }
        else:
            if args.phase is None or args.approval_file is None:
                raise BenchmarkExecutionError(
                    "image pull requires --phase and --approval-file"
                )
            report = pull_and_observe(
                args.phase, args.approval_file, args.evidence_dir.resolve()
            )
            output = {"images": len(report["images"]), "status": "PASS"}
        print(json.dumps(output, sort_keys=True))
        return 0
    except (BenchmarkExecutionError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
