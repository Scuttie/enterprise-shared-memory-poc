"""Run the frozen 6-instance/12-target official grader smoke after approval."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from enterprise_memory.trimem.grader import GradeRequest, GradeResult, GraderInvocationFailure  # noqa: E402
from enterprise_memory.trimem.workspace import WorkspaceGraderContext  # noqa: E402
from trimem_benchmark_run import (  # noqa: E402
    BenchmarkExecutionError,
    evidence_reference,
    grader_factory,
    image_entries,
    observed_target_digest,
    prepare_harnesses,
    read_json,
    restricted_evidence_references,
    sha256_bytes,
    validate_benchmark_environment,
    validate_exec_approval,
    write_json,
)
from trimem_select_targets import canonical_bytes, instance_id, load_sources, row_hash  # noqa: E402


def _gold_patch(benchmark_id: str, row: Mapping[str, Any]) -> str:
    field = "patch" if benchmark_id == "swebench_verified" else "fix_patch"
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkExecutionError(f"frozen GOLD row lacks {field}")
    return value


def _rows_for_targets(targets: list[dict[str, Any]], cache: Path) -> dict[tuple[str, str], dict[str, Any]]:
    sources, _ = load_sources(cache)
    wanted = {(row["benchmark_id"], row["instance_id"]) for row in targets}
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for benchmark_id, rows in sources.items():
        for row in rows:
            key = (benchmark_id, instance_id(row))
            if key in wanted:
                if key in result:
                    raise BenchmarkExecutionError(f"duplicate official source row: {key}")
                result[key] = dict(row)
    if set(result) != wanted:
        raise BenchmarkExecutionError("official smoke source rows are missing")
    for target in targets:
        source = result[(target["benchmark_id"], target["instance_id"])]
        if row_hash(source) != target["source_row_sha256"]:
            raise BenchmarkExecutionError(f"official smoke source-row hash drift: {target['target_id']}")
    return result


def run_smoke(approval_path: Path, output_root: Path) -> dict[str, Any]:
    validate_benchmark_environment()
    approval = validate_exec_approval("grader-smoke", approval_path)
    manifest = read_json(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    targets = manifest.get("targets")
    if not isinstance(targets, list) or len(targets) != 12:
        raise BenchmarkExecutionError("grader-smoke target matrix must contain exactly 12 rows")
    rows = _rows_for_targets(targets, ROOT / ".trimem-exec/datasets")
    images, support = image_entries(require_benchmark=False)
    harnesses = prepare_harnesses(ROOT / ".trimem-exec/harnesses")
    output_root.mkdir(parents=True, exist_ok=True)
    write_json(output_root / "external-approval-evidence.json", {
        "approval_artifact_sha256": approval["approval_artifact_sha256"],
        "approved_request_sha256": approval["approved_request_sha256"],
        "approved_workflow_run_id": approval["approved_workflow_run_id"],
        "approved_workflow_run_attempt": approval["approved_workflow_run_attempt"],
        "freeze_sha256": approval["freeze_sha256"],
        "git_head": approval["git_head"],
        "phase": approval["phase"],
    })
    failures = []
    for index, target in enumerate(targets):
        source = rows[(target["benchmark_id"], target["instance_id"])]
        patch = _gold_patch(target["benchmark_id"], source) if target["probe"] == "GOLD" else ""
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", target["target_id"])
        task_dir = output_root / f"{index:03d}-{safe}"
        task_dir.mkdir(parents=True, exist_ok=True)
        grader = grader_factory(
            target, source, images[target["instance_id"]], harnesses,
            task_dir / "official-grader", f"smoke-{target['probe'].lower()}", support,
        )
        request = GradeRequest(
            task_id=target["target_id"], repository=target["repository"],
            base_commit=target["base_commit"], patch=patch,
            workspace=WorkspaceGraderContext(
                kind="official-grader-smoke-private-patch",
                repository_files={}, base_commit=target["base_commit"],
            ),
        )
        try:
            grade = grader.grade(request)
            execution_status = "SUCCESS"
        except GraderInvocationFailure as exc:
            grade = exc.result
            execution_status = "FAILURE"
            failures.append(target["target_id"])
        stdout_path, stderr_path, report_path = (
            task_dir / "stdout.txt", task_dir / "stderr.txt", task_dir / "report.json"
        )
        stdout_path.write_text(grade.stdout, encoding="utf-8", newline="\n")
        stderr_path.write_text(grade.stderr, encoding="utf-8", newline="\n")
        write_json(report_path, grade.report)
        checkout_path = task_dir / "checkout-evidence.json"
        write_json(checkout_path, {
            "mode": "OFFICIAL_GRADER_SMOKE_PRIVATE_PATCH",
            "probe": target["probe"],
            "patch_sha256": sha256_bytes(patch.encode("utf-8")),
            "source_row_sha256": target["source_row_sha256"],
            "gold_or_test_bytes_retained": False,
        })
        try:
            observed = observed_target_digest(grade)
        except BenchmarkExecutionError:
            observed = "UNPROVEN"
            failures.append(target["target_id"])
        record = {
            "target_id": target["target_id"],
            "arm": target["probe"],
            "execution_status": execution_status,
            "grader_exit_code": grade.exit_code,
            "official_grader": grade.official,
            "resolved": grade.resolved,
            "expected_image_digest": images[target["instance_id"]]["expected_digest"],
            "observed_image_digest": observed,
            "actual_accounting": {
                "model_gateway_calls": 0, "paid_model_calls": 0,
                "grader_calls": 1, "grader_containers": int(grade.container_started),
                "official_grader_runs": int(grade.official and grade.container_started),
            },
            "evidence": {
                "stdout": evidence_reference(task_dir, stdout_path),
                "stderr": evidence_reference(task_dir, stderr_path),
                "report": evidence_reference(task_dir, report_path),
                "checkout": evidence_reference(task_dir, checkout_path),
                "restricted_grader_raw": restricted_evidence_references(
                    task_dir, task_dir / "official-grader"
                ),
            },
        }
        write_json(task_dir / f"{safe}.result.json", record)
        if grade.resolved is not target["expected_resolved"]:
            failures.append(target["target_id"])
    report = {
        "schema": "trimem/grader-smoke-execution/1.0",
        "expected_target_count": 12,
        "observed_target_count": len(targets),
        "failures": sorted(set(failures)),
        "official_grader_runs": sum(
            read_json(path)["actual_accounting"]["official_grader_runs"]
            for path in output_root.rglob("*.result.json")
        ),
        "paid_model_calls": 0,
        "status": "PASS" if not failures else "FAIL",
    }
    write_json(output_root / "smoke-execution-summary.json", report)
    if failures:
        raise BenchmarkExecutionError(f"grader smoke failed closed: {sorted(set(failures))}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approval-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_smoke(args.approval_file.resolve(), args.output_dir.resolve())
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
