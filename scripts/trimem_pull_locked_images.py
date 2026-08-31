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


def pull_and_observe(phase: str, approval_path: Path, evidence_root: Path) -> dict[str, Any]:
    approval = validate_exec_approval(phase, approval_path)
    images = selected_images(phase)
    evidence_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, image in enumerate(images):
        expected = image.rsplit("@", 1)[1]
        pulled, pull_refs = _run(
            ["docker", "pull", image], evidence_root, index, "pull"
        )
        if pulled.returncode != 0:
            raise BenchmarkExecutionError(f"digest-only Docker pull failed: {image}")
        inspected, inspect_refs = _run(
            ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image],
            evidence_root, index, "inspect",
        )
        if inspected.returncode != 0:
            raise BenchmarkExecutionError(f"Docker image inspect failed: {image}")
        try:
            repo_digests = strict_json_loads(inspected.stdout.strip())
        except (json.JSONDecodeError, ValueError) as exc:
            raise BenchmarkExecutionError(f"Docker image inspect returned invalid JSON: {image}") from exc
        observed = sorted({str(value).rsplit("@", 1)[-1] for value in repo_digests or []})
        if expected not in observed:
            raise BenchmarkExecutionError(f"observed image digest mismatch: {image}")
        rows.append({
            "image": image,
            "expected_digest": expected,
            "observed_digests": observed,
            "pull": pull_refs,
            "inspect": inspect_refs,
        })
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=tuple(MANIFESTS), required=True)
    parser.add_argument("--approval-file", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = pull_and_observe(args.phase, args.approval_file, args.evidence_dir.resolve())
        print(json.dumps({"images": len(report["images"]), "status": "PASS"}, sort_keys=True))
        return 0
    except (BenchmarkExecutionError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
