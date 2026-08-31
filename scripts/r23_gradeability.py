#!/usr/bin/env python3
"""Run one frozen R23 official-grader smoke target (GOLD + NOOP).

Execution is credential-free but Docker-bearing and is therefore gated on an
explicit EXEC approval. The target must come from the committed smoke
manifest. Before the official ``swebench==5.0.2`` harness is invoked, this
driver verifies the pinned dataset parquet and row hashes, pulls the frozen
image reference by digest, and verifies Docker's observed RepoDigest.

The complete stdout, stderr, prediction, local dataset row, official report,
and harness-created log tree are retained under ``artifacts/r23/grader_run``.
No model endpoint is imported or called.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from r23_gradeability_prepare import (  # noqa: E402
    DEFAULT_MANIFEST,
    NOOP_R23_PATCH,
    ManifestError,
    validate_manifest,
)


ART = ROOT / "artifacts" / "r23"
DEFAULT_RESULTS = ART / "grader_run"
APPROVAL_ENV = "R23_UPSTREAM_EXEC_APPROVED"
APPROVAL_VALUE = "1"
TERMINAL_LABELS = {"GRADEABLE", "UNGRADEABLE_GOLD", "UNGRADEABLE_NOOP"}
REQUIRED_ROW_FIELDS = {
    "instance_id",
    "repo",
    "base_commit",
    "patch",
    "test_patch",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "image",
    "eval_script",
    "log_parser",
    "eval_type",
    "version",
}


class EmptyBaselineRejected(ValueError):
    pass


class GradeabilityInfraError(RuntimeError):
    pass


def assert_valid_baseline(patch: str) -> str:
    if not (patch or "").strip():
        raise EmptyBaselineRejected("empty patch short-circuits the harness; use NOOP_R23_PATCH")
    return patch


def _approved() -> bool:
    return os.environ.get(APPROVAL_ENV) == APPROVAL_VALUE


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_row_sha256(row: dict[str, Any]) -> str:
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _sha256_bytes(payload)


def _target_from_manifest(manifest: dict, instance_id: str) -> dict:
    matches = [target for target in manifest["targets"] if target.get("instance_id") == instance_id]
    if len(matches) != 1:
        raise ManifestError(f"instance_id must occur exactly once in committed smoke manifest: {instance_id}")
    return matches[0]


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value or "", encoding="utf-8")


def _run_logged(cmd: list[str], cwd: Path, prefix: Path, timeout: int | None = None) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        _write_text(prefix.with_name(prefix.name + "_stdout.log"), stdout)
        _write_text(prefix.with_name(prefix.name + "_stderr.log"), stderr + f"\nTIMEOUT after {timeout}s\n")
        raise GradeabilityInfraError(f"command timed out after {timeout}s: {cmd[0]}") from exc
    _write_text(prefix.with_name(prefix.name + "_stdout.log"), proc.stdout or "")
    _write_text(prefix.with_name(prefix.name + "_stderr.log"), proc.stderr or "")
    return proc


def _load_pinned_row(manifest: dict, target: dict) -> tuple[dict, str]:
    """Download one exact-revision parquet, verify it, and return one locked row."""
    dataset = manifest["dataset"]
    from huggingface_hub import hf_hub_download
    import pyarrow.parquet as parquet

    parquet_path = Path(
        hf_hub_download(
            repo_id=dataset["dataset_id"],
            repo_type="dataset",
            revision=dataset["revision_sha"],
            filename=dataset["parquet_path"],
        )
    )
    observed_parquet_sha = _sha256_file(parquet_path)
    if observed_parquet_sha != dataset["parquet_sha256"]:
        raise GradeabilityInfraError(
            f"pinned parquet digest mismatch: expected {dataset['parquet_sha256']}, observed {observed_parquet_sha}"
        )
    table = parquet.read_table(parquet_path, filters=[("instance_id", "=", target["instance_id"])])
    matches = [dict(row) for row in table.to_pylist()]
    if len(matches) != 1:
        raise GradeabilityInfraError(
            f"expected one pinned dataset row for {target['instance_id']}, found {len(matches)}"
        )
    row = matches[0]
    missing = sorted(field for field in REQUIRED_ROW_FIELDS if row.get(field) in (None, ""))
    if missing:
        raise GradeabilityInfraError(f"pinned row missing required fields: {missing}")
    if row["repo"] != target["repository"]:
        raise GradeabilityInfraError(f"repository drift for {target['instance_id']}")
    if row["image"] != target["image_tag"]:
        raise GradeabilityInfraError(f"image tag drift for {target['instance_id']}")
    if _sha256_bytes(row["patch"].encode("utf-8")) != target["gold_patch_sha256"]:
        raise GradeabilityInfraError(f"gold patch drift for {target['instance_id']}")
    if _canonical_row_sha256(row) != target["dataset_row_sha256"]:
        raise GradeabilityInfraError(f"dataset row drift for {target['instance_id']}")
    return row, observed_parquet_sha


def _parse_repo_digests(stdout: str) -> list[str]:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise GradeabilityInfraError(f"Docker inspect returned malformed RepoDigests JSON: {exc}") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise GradeabilityInfraError("Docker inspect returned no RepoDigests list")
    return sorted(set(value))


def _pull_and_verify_image(target: dict, target_dir: Path) -> list[str]:
    image_ref = target["image_ref"]
    pull = _run_logged(["docker", "pull", image_ref], ROOT, target_dir / "image_pull", timeout=1800)
    if pull.returncode != 0:
        raise GradeabilityInfraError(f"digest-pinned Docker pull failed with rc={pull.returncode}")
    inspect = _run_logged(
        ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image_ref],
        ROOT,
        target_dir / "image_inspect",
        timeout=120,
    )
    if inspect.returncode != 0:
        raise GradeabilityInfraError(f"Docker image inspect failed with rc={inspect.returncode}")
    observed_refs = _parse_repo_digests(inspect.stdout or "")
    if image_ref not in observed_refs:
        raise GradeabilityInfraError(
            f"observed RepoDigests do not contain frozen ref {image_ref}: {observed_refs}"
        )
    return observed_refs


def _find_report(condition_dir: Path, run_id: str) -> tuple[dict | None, Path | None]:
    candidates = sorted(condition_dir.glob(f"*.{run_id}.json"))
    parsed: list[tuple[dict, Path]] = []
    for path in candidates:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(report, dict) and "resolved_ids" in report:
            parsed.append((report, path))
    if len(parsed) > 1:
        raise GradeabilityInfraError(f"multiple official reports found for {run_id}")
    return parsed[0] if parsed else (None, None)


def _grade(
    instance_id: str,
    model_patch: str,
    dataset_path: Path,
    condition_dir: Path,
    condition: str,
    timeout_seconds: int,
) -> dict:
    condition_dir.mkdir(parents=True, exist_ok=True)
    patch = assert_valid_baseline(model_patch)
    run_hash = _sha256_bytes((instance_id + "\0" + condition + "\0" + patch).encode("utf-8"))[:10]
    run_id = f"r23-{condition.lower()}-{instance_id.replace('__', '_')}-{run_hash}"
    predictions_path = condition_dir / "prediction.jsonl"
    predictions_path.write_text(
        json.dumps(
            {"instance_id": instance_id, "model_name_or_path": "r23", "model_patch": patch},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    cmd = [
        sys.executable,
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        str(dataset_path.resolve()),
        "--split",
        "test",
        "--instance_ids",
        instance_id,
        "--predictions_path",
        str(predictions_path.resolve()),
        "--run_id",
        run_id,
        "--max_workers",
        "1",
        "--timeout",
        str(timeout_seconds),
        "--report_dir",
        str(condition_dir.resolve()),
    ]
    proc = _run_logged(cmd, condition_dir, condition_dir / "harness")
    report, report_path = _find_report(condition_dir, run_id)
    resolved = bool(report and instance_id in set(report.get("resolved_ids") or []))
    completed = bool(report and instance_id in set(report.get("completed_ids") or []))
    infra_ids = set((report or {}).get("infra_failure_ids") or [])
    error_ids = set((report or {}).get("error_ids") or [])
    incomplete_ids = set((report or {}).get("incomplete_ids") or [])
    ambiguous_ids = set((report or {}).get("ambiguous_failure_ids") or [])
    empty_patch_ids = set((report or {}).get("empty_patch_ids") or [])
    infra_ok = (
        proc.returncode == 0
        and report is not None
        and completed
        and instance_id not in infra_ids | error_ids | incomplete_ids | ambiguous_ids | empty_patch_ids
    )
    return {
        "condition": condition,
        "resolved": resolved,
        "completed": completed,
        "empty_patch": instance_id in empty_patch_ids,
        "infra_ok": infra_ok,
        "returncode": proc.returncode,
        "report_found": report is not None,
        "report_path": str(report_path.relative_to(ROOT)).replace(os.sep, "/") if report_path else None,
        "run_id": run_id,
        "patch_sha256": _sha256_bytes(patch.encode("utf-8")),
    }


def classify(gold: dict, noop: dict) -> str:
    if not gold.get("infra_ok") or not noop.get("infra_ok"):
        return "INFRA_FAILURE"
    if not gold.get("resolved"):
        return "UNGRADEABLE_GOLD"
    if noop.get("resolved"):
        return "UNGRADEABLE_NOOP"
    return "GRADEABLE"


def _evidence_meta(path: Path) -> dict:
    return {
        "relpath": str(path.relative_to(ROOT)).replace(os.sep, "/"),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _collect_evidence(target_dir: Path) -> list[dict]:
    return [_evidence_meta(path) for path in sorted(target_dir.rglob("*")) if path.is_file()]


def _write_summary(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _base_summary(instance_id: str, target: dict | None = None) -> dict:
    return {
        "schema": "r23/gradeability_target/1.0.0",
        "instance_id": instance_id,
        "repository_key": (target or {}).get("repository_key"),
        "label": "INFRA_FAILURE",
        "gold": None,
        "noop": None,
        "image_expected_ref": (target or {}).get("image_ref"),
        "image_expected_digest": (target or {}).get("image_digest"),
        "image_observed_repo_digests": [],
        "image_digest_verified": False,
        "dataset_revision": None,
        "dataset_parquet_sha256": None,
        "raw_evidence": [],
        "paid_model_calls": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out", required=True)
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS))
    args = parser.parse_args(argv)
    out_path = Path(args.out).resolve()

    if not _approved():
        print(f"R23 gradeability execution requires {APPROVAL_ENV}={APPROVAL_VALUE}; refusing before Docker.")
        return 3

    target: dict | None = None
    target_dir = Path(args.results_dir).resolve() / args.instance_id
    summary = _base_summary(args.instance_id)
    try:
        manifest = validate_manifest(args.manifest)
        target = _target_from_manifest(manifest, args.instance_id)
        summary = _base_summary(args.instance_id, target)
        target_dir.mkdir(parents=True, exist_ok=True)

        row, parquet_sha = _load_pinned_row(manifest, target)
        observed_refs = _pull_and_verify_image(target, target_dir)
        # Force the official harness to use the digest-pinned image already verified above.
        row_for_harness = dict(row)
        row_for_harness["image"] = target["image_ref"]
        dataset_path = target_dir / "dataset.json"
        dataset_path.write_text(json.dumps([row_for_harness], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        timeout_seconds = int(manifest["harness"]["timeout_seconds_per_condition"])
        gold = _grade(args.instance_id, row["patch"], dataset_path, target_dir / "gold", "GOLD", timeout_seconds)
        noop = _grade(
            args.instance_id,
            assert_valid_baseline(NOOP_R23_PATCH),
            dataset_path,
            target_dir / "noop",
            "NOOP",
            timeout_seconds,
        )
        label = classify(gold, noop)
        summary.update(
            {
                "label": label,
                "gold": gold,
                "noop": noop,
                "image_observed_repo_digests": observed_refs,
                "image_digest_verified": target["image_ref"] in observed_refs,
                "dataset_revision": manifest["dataset"]["revision_sha"],
                "dataset_parquet_sha256": parquet_sha,
                "dataset_row_sha256": target["dataset_row_sha256"],
                "noop_patch_sha256": _sha256_bytes(NOOP_R23_PATCH.encode("utf-8")),
            }
        )
    except Exception as exc:
        # Any unexpected dependency, parser, filesystem, Docker, or harness
        # failure is an infrastructure record, never a silently absent shard.
        summary["error"] = f"{type(exc).__name__}: {exc}"
        print(summary["error"], file=sys.stderr)
    finally:
        if target_dir.is_dir():
            summary["raw_evidence"] = _collect_evidence(target_dir)
        _write_summary(out_path, summary)

    print(
        f"R23 GRADE {args.instance_id} -> {summary['label']} "
        f"gold={bool((summary.get('gold') or {}).get('resolved'))} "
        f"noop={bool((summary.get('noop') or {}).get('resolved'))}"
    )
    return 0 if summary["label"] in TERMINAL_LABELS else 1


if __name__ == "__main__":
    raise SystemExit(main())
