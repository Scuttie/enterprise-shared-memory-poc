"""Emit only committed TriMem matrices and aggregate them fail closed.

Online memory is a serial stream. Development and held-out execution therefore
parallelize by arm only; task-level modulo sharding is deliberately unsupported.
The independent GOLD/NOOP grader smoke may fan out one committed target per job.
"""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from trimem_m2_candidates import (  # noqa: E402
    CANDIDATE_IDS,
    candidate_row,
    load_candidate_policy,
    runtime_lock_for,
    select_development_candidate,
    validate_selected_m2,
)
ALLOWED_MANIFESTS = {
    "development": Path("configs/trimem_v1/development_manifest.json"),
    "heldout": Path("configs/trimem_v1/heldout_manifest.json"),
    "grader-smoke": Path("configs/trimem_v1/grader_smoke_manifest.json"),
}
IMAGE_LOCK = Path("artifacts/trimem_v1/grader_image_lock.json")
ARMS = ("M0", "M1", "M2")
DEVELOPMENT_STREAMS = tuple(f"M2-{candidate_id}" for candidate_id in CANDIDATE_IDS) + ("M0", "M1")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")
ACCOUNTING_FIELDS = (
    "solve_calls", "decomposition_calls", "extraction_calls", "input_tokens",
    "cached_input_tokens", "output_tokens", "reasoning_tokens",
    "model_wall_time_ms", "tool_wall_time_ms", "grader_wall_time_ms",
    "task_wall_time_ms",
    "model_gateway_calls", "paid_model_calls", "grader_calls", "grader_containers",
    "official_grader_runs",
)
MEMORY_FIELDS = (
    "recall_attempts", "injected_records", "episodic_injections",
    "user_semantic_injections", "org_semantic_injections", "abstention_decisions",
    "retained_records", "archived_records", "net_memory_growth",
)


class MatrixError(ValueError):
    pass


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _load(path: Path) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise MatrixError(f"duplicate JSON key in {_display(path)}: {key}")
            value[key] = child
        return value
    try:
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatrixError(f"invalid JSON {_display(path)}: {exc}") from exc


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _strict_loads(raw: str | bytes) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise MatrixError(f"duplicate JSON key: {key}")
            value[key] = child
        return value
    return json.loads(raw, object_pairs_hook=reject_duplicate_keys)


def manifest_path(name: str) -> Path:
    try:
        relative = ALLOWED_MANIFESTS[name]
    except KeyError as exc:
        raise MatrixError(f"manifest must be one of {sorted(ALLOWED_MANIFESTS)}") from exc
    path = (ROOT / relative).resolve()
    if ROOT.resolve() not in path.parents or not path.is_file():
        raise MatrixError(f"committed manifest is missing: {relative.as_posix()}")
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative.as_posix()],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if tracked.returncode != 0:
        raise MatrixError(f"execution manifest is not git-tracked: {relative.as_posix()}")
    return path


def _validate_target_set(manifest: dict[str, Any], *, ordered: bool) -> list[dict[str, Any]]:
    targets = manifest.get("targets")
    if not isinstance(targets, list) or not targets:
        raise MatrixError("manifest has no frozen targets")
    if manifest.get("status") not in {"FROZEN", "FROZEN_TARGET_SET_EXECUTION_PENDING"}:
        raise MatrixError("manifest target set is not frozen")
    if hashlib.sha256(_canonical(targets)).hexdigest() != manifest.get("target_set_sha256"):
        raise MatrixError("manifest canonical target-set digest mismatch")
    ids = [target.get("target_id") for target in targets if isinstance(target, dict)]
    if len(ids) != len(targets) or any(not isinstance(value, str) or not value for value in ids):
        raise MatrixError("every target requires a non-empty target_id")
    duplicates = sorted(target for target, count in Counter(ids).items() if count != 1)
    if duplicates:
        raise MatrixError(f"duplicate target IDs: {duplicates}")
    for position, target in enumerate(targets):
        revision = target.get("dataset_revision")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise MatrixError(f"target has no exact dataset revision: {target.get('target_id')}")
        if not SHA256.fullmatch(str(target.get("source_row_sha256"))):
            raise MatrixError(f"target has no exact source-row hash: {target.get('target_id')}")
        if ordered and target.get("order_index") != position:
            raise MatrixError(f"target order_index mismatch at position {position}")
    return targets


def _validate_benchmark_roles(
    manifest: dict[str, Any], targets: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = manifest.get("benchmark_roles")
    if not isinstance(rows, list) or not rows:
        raise MatrixError("benchmark role registry is missing")
    required = {
        "benchmark_id", "dataset_id", "dataset_revision", "role", "target_count"
    }
    benchmark_ids = [row.get("benchmark_id") for row in rows if isinstance(row, dict)]
    if len(benchmark_ids) != len(rows) or len(set(benchmark_ids)) != len(rows):
        raise MatrixError("benchmark role registry is malformed or duplicated")
    target_counts = Counter(row.get("benchmark_id") for row in targets)
    revisions: dict[str, set[str]] = {}
    for target in targets:
        revisions.setdefault(str(target.get("benchmark_id")), set()).add(
            str(target.get("dataset_revision"))
        )
    for row in rows:
        if set(row) != required:
            raise MatrixError("benchmark role registry field set drift")
        benchmark_id = row["benchmark_id"]
        if (
            not isinstance(benchmark_id, str)
            or not isinstance(row["dataset_id"], str)
            or not row["dataset_id"]
            or row["role"] not in {"PRIMARY", "SECONDARY"}
            or type(row["target_count"]) is not int
            or row["target_count"] <= 0
            or target_counts.get(benchmark_id) != row["target_count"]
            or revisions.get(benchmark_id) != {row["dataset_revision"]}
        ):
            raise MatrixError(f"benchmark role/count/revision drift: {benchmark_id}")
    if set(benchmark_ids) != set(target_counts):
        raise MatrixError("benchmark role registry does not cover the exact target set")
    primary = [row["benchmark_id"] for row in rows if row["role"] == "PRIMARY"]
    if primary != ["swebench_verified"] or any(
        row["role"] != "SECONDARY"
        for row in rows
        if row["benchmark_id"].startswith("multi_swe_bench_")
    ):
        raise MatrixError("primary/secondary benchmark endpoint roles drift")
    return rows


def _benchmark_endpoint_totals(
    outcomes: list[dict[str, Any]],
    streams: tuple[str, ...],
    roles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compute preregistered arm-by-benchmark Pass@1, never a pooled primary."""

    totals = []
    expected_pairs = {
        (stream, row["benchmark_id"]): row["target_count"]
        for stream in streams
        for row in roles
    }
    observed_pairs = Counter(
        (row.get("arm"), row.get("benchmark_id")) for row in outcomes
    )
    if observed_pairs != Counter(expected_pairs):
        raise MatrixError("arm-by-benchmark endpoint target counts drift")
    role_by_id = {row["benchmark_id"]: row for row in roles}
    for stream in streams:
        for role in roles:
            benchmark_id = role["benchmark_id"]
            rows = [
                row for row in outcomes
                if row["arm"] == stream and row["benchmark_id"] == benchmark_id
            ]
            if any(not isinstance(row.get("resolved"), bool) for row in rows):
                raise MatrixError("endpoint outcome is not boolean")
            n = len(rows)
            resolved = sum(row["resolved"] is True for row in rows)
            totals.append({
                "arm": stream,
                "benchmark_id": benchmark_id,
                "dataset_revision": role_by_id[benchmark_id]["dataset_revision"],
                "endpoint": "official_resolved_pass_at_1",
                "n": n,
                "pass_at_1": format(Decimal(resolved) / Decimal(n), ".12f"),
                "reporting_role": role_by_id[benchmark_id]["role"],
                "resolved_count": resolved,
            })
    return totals


def sequence_sha256(targets: list[dict[str, Any]]) -> str:
    rows = [
        {key: row[key] for key in (
            "target_id", "instance_id", "benchmark_id", "dataset_revision",
            "source_row_sha256", "base_commit", "order_index",
        )}
        for row in targets
    ]
    return hashlib.sha256(_canonical(rows)).hexdigest()


def _locked_images(*, benchmark: bool = False) -> dict[str, str]:
    value = _load(ROOT / IMAGE_LOCK)
    if value.get("smoke_status") != "FROZEN" or value.get("status") != "FROZEN":
        raise MatrixError("grader-smoke image lock is not FROZEN")
    if benchmark and value.get("benchmark_target_images", {}).get("status") != "FROZEN":
        raise MatrixError("development/held-out grader image locks are pending and benchmark EXEC is closed")
    rows = list(value.get("targets", []))
    if benchmark:
        benchmark_lock = value.get("benchmark_target_images", {})
        if not isinstance(benchmark_lock.get("targets"), list):
            raise MatrixError("development/held-out grader image target map is missing")
        rows.extend(benchmark_lock["targets"])
    result: dict[str, str] = {}
    for row in rows:
        instance_id, image, expected = row.get("instance_id"), row.get("image"), row.get("expected_digest")
        if not isinstance(instance_id, str) or not IMAGE.fullmatch(str(image)):
            raise MatrixError("grader image entry is not digest-pinned")
        if expected != image.rsplit("@", 1)[1]:
            raise MatrixError(f"image expected digest mismatch for {instance_id}")
        if instance_id in result:
            raise MatrixError(f"duplicate image lock for {instance_id}")
        result[instance_id] = image
    return result


def execution_matrix(name: str) -> list[dict[str, Any]]:
    manifest = _load(manifest_path(name))
    if name == "grader-smoke":
        targets = _validate_target_set(manifest, ordered=False)
        images = _locked_images()
        rows = []
        for target in targets:
            instance_id = target.get("instance_id")
            if instance_id not in images:
                raise MatrixError(f"missing grader image lock for {instance_id}")
            rows.append({**target, "image": images[instance_id]})
        return sorted(rows, key=lambda row: row["target_id"])
    targets = _validate_target_set(manifest, ordered=True)
    digest = sequence_sha256(targets)
    streams = DEVELOPMENT_STREAMS if name == "development" else ARMS
    return [{"arm": stream, "expected_target_count": len(targets), "manifest": name,
             "sequence_sha256": digest} for stream in streams]


def _evidence_reference(result_file: Path, evidence: Any, name: str) -> bytes:
    if not isinstance(evidence, dict):
        raise MatrixError(f"{result_file.name}: missing {name} evidence")
    relative, digest, byte_count = evidence.get("path"), evidence.get("sha256"), evidence.get("bytes")
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise MatrixError(f"{result_file.name}: unsafe {name} evidence path")
    target = (result_file.parent / relative).resolve()
    if result_file.parent.resolve() not in target.parents or not target.is_file():
        raise MatrixError(f"{result_file.name}: missing {name} evidence file")
    raw = target.read_bytes()
    if not SHA256.fullmatch(str(digest)) or hashlib.sha256(raw).hexdigest() != digest or len(raw) != byte_count:
        raise MatrixError(f"{result_file.name}: {name} evidence hash/size mismatch")
    return raw


def _evidence_file(result_file: Path, record: dict[str, Any], name: str) -> bytes:
    return _evidence_reference(result_file, record.get("evidence", {}).get(name), name)


def _restricted_evidence(result_file: Path, record: dict[str, Any]) -> None:
    references = record.get("evidence", {}).get("restricted_grader_raw")
    if not isinstance(references, list) or not references:
        raise MatrixError(f"{result_file.name}: restricted grader evidence list is missing")
    seen: set[str] = set()
    for index, reference in enumerate(references):
        relative = reference.get("path") if isinstance(reference, dict) else None
        if relative in seen:
            raise MatrixError(f"{result_file.name}: duplicate restricted grader evidence path")
        seen.add(str(relative))
        _evidence_reference(result_file, reference, f"restricted_grader_raw[{index}]")


def _report_image_digest(result_file: Path, record: dict[str, Any], expected_image: str) -> str:
    raw = _evidence_file(result_file, record, "report")
    try:
        report = _strict_loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatrixError(f"{result_file.name}: official report evidence is invalid JSON") from exc
    if not isinstance(report, dict):
        raise MatrixError(f"{result_file.name}: official report evidence root is not an object")
    trimem = report.get("_trimem")
    evidence = trimem.get("image_evidence") if isinstance(trimem, dict) else report.get("image_evidence")
    if not isinstance(evidence, list):
        raise MatrixError(f"{result_file.name}: official report has no image evidence")
    expected = expected_image.rsplit("@", 1)[1]
    matches = [row for row in evidence if isinstance(row, dict) and row.get("image") == expected_image]
    if len(matches) != 1:
        raise MatrixError(f"{result_file.name}: official report target image evidence is not unique")
    observed = matches[0].get("observed")
    if (matches[0].get("expected") != expected or not isinstance(observed, list)
            or expected not in observed or any(not SHA256.fullmatch(str(item)) for item in observed)):
        raise MatrixError(f"{result_file.name}: official report does not prove inspected digest equality")
    return expected


def _terminal_checkpoint(result_file: Path, record: dict[str, Any]) -> None:
    raw = _evidence_file(result_file, record, "terminal_checkpoint")
    try:
        checkpoint = _strict_loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatrixError(f"{result_file.name}: terminal checkpoint is invalid JSON") from exc
    if not isinstance(checkpoint, dict) or checkpoint.get("state") != "DONE":
        raise MatrixError(f"{result_file.name}: terminal checkpoint state is not DONE")
    digest = hashlib.sha256(_canonical(checkpoint)).hexdigest()
    if (record.get("terminal_state") != "DONE"
            or record.get("terminal_checkpoint_sha256") != digest
            or checkpoint.get("evidence_event_hash") != record.get("evidence_tail_hash")):
        raise MatrixError(f"{result_file.name}: terminal checkpoint/evidence binding mismatch")


def _result_records(results_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    if not results_dir.is_dir():
        raise MatrixError(f"results directory is missing: {results_dir}")
    records = []
    for path in sorted(results_dir.rglob("*.result.json")):
        value = _load(path)
        if not isinstance(value, dict):
            raise MatrixError(f"result must be an object: {path.name}")
        records.append((path, value))
    return records


def _approval_binding(name: str, results_dir: Path) -> dict[str, str]:
    """Revalidate and seal the public subset of the EXEC approval evidence."""

    path = results_dir / "external-approval-evidence.json"
    value = _load(path)
    if not isinstance(value, dict):
        raise MatrixError("external approval evidence is not an object")
    required = {
        "approval_artifact_sha256",
        "approved_request_sha256",
        "approved_workflow_run_id",
        "approved_workflow_run_attempt",
        "freeze_sha256",
        "git_head",
        "phase",
    }
    if not required <= set(value):
        raise MatrixError("external approval evidence is incomplete")
    for field in (
        "approval_artifact_sha256",
        "approved_request_sha256",
        "freeze_sha256",
    ):
        if not isinstance(value.get(field), str) or not SHA256.fullmatch(value[field]):
            raise MatrixError(f"external approval {field} is invalid")
    if not isinstance(value.get("git_head"), str) or not HEX40.fullmatch(value["git_head"]):
        raise MatrixError("external approval git_head is invalid")
    for field in ("approved_workflow_run_id", "approved_workflow_run_attempt"):
        item = str(value.get(field, ""))
        if re.fullmatch(r"[1-9][0-9]*", item) is None:
            raise MatrixError(f"external approval {field} is invalid")
        environment_name = (
            "GITHUB_RUN_ID" if field == "approved_workflow_run_id" else "GITHUB_RUN_ATTEMPT"
        )
        if os.environ.get(environment_name) != item:
            raise MatrixError(f"external approval {field} differs from this workflow")
    expected_phase = {
        "grader-smoke": "GRADER_SMOKE",
        "development": "DEVELOPMENT_TUNING",
        "heldout": "HELDOUT_BENCHMARK",
    }[name]
    if value.get("phase") != expected_phase:
        raise MatrixError("external approval phase differs from the aggregate manifest")

    request = ROOT / "configs/trimem_v1/benchmark_exec_request.json"
    freeze = ROOT / "artifacts/trimem_v1/freeze.json"
    if value["approved_request_sha256"] != hashlib.sha256(request.read_bytes()).hexdigest():
        raise MatrixError("external approval request digest differs from the committed request")
    if value["freeze_sha256"] != hashlib.sha256(freeze.read_bytes()).hexdigest():
        raise MatrixError("external approval freeze digest differs from the committed freeze")
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0 or completed.stdout.strip() != value["git_head"]:
        raise MatrixError("external approval git_head differs from aggregate HEAD")
    return {field: str(value[field]) for field in sorted(required)}


def _seal_aggregate(name: str, results_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    body = {
        **report,
        "approval_binding": _approval_binding(name, results_dir),
        "manifest": name,
        "schema": "trimem/verified-aggregate/1.0",
    }
    return {**body, "aggregate_sha256": hashlib.sha256(_canonical(body)).hexdigest()}


def _actual_usd_from_accounting(
    accounting: dict[str, Any], pricing: dict[str, Any]
) -> str:
    """Recompute provider cost from frozen pricing and exact token counters."""

    cached = int(accounting["cached_input_tokens"])
    total_input = int(accounting["input_tokens"])
    output = int(accounting["output_tokens"])
    if cached < 0 or total_input < cached or output < 0:
        raise MatrixError("cached/output token accounting is inconsistent")
    try:
        value = (
            Decimal(total_input - cached)
            * Decimal(str(pricing["input_per_million_tokens_usd"]))
            + Decimal(cached)
            * Decimal(str(pricing["cached_input_per_million_tokens_usd"]))
            + Decimal(output)
            * Decimal(str(pricing["output_per_million_tokens_usd"]))
        ) / Decimal(1_000_000)
    except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
        raise MatrixError("frozen model pricing is invalid") from exc
    return format(value, ".12f")


def _validate_stream_summary_totals(
    path: Path,
    summary: dict[str, Any],
    stream_records: list[dict[str, Any]],
    pricing: dict[str, Any],
) -> None:
    """Bind every published stream total to its raw task-arm records."""

    for record in stream_records:
        accounting = record.get("actual_accounting")
        memory = record.get("actual_memory_metrics")
        if not isinstance(accounting, dict) or set(accounting) != set(ACCOUNTING_FIELDS):
            raise MatrixError(f"{path.name}: task actual accounting shape differs")
        if not isinstance(memory, dict) or set(memory) != set(MEMORY_FIELDS):
            raise MatrixError(f"{path.name}: task memory metric shape differs")

    expected_accounting = {
        field: sum(int(record["actual_accounting"][field]) for record in stream_records)
        for field in ACCOUNTING_FIELDS
    }
    if summary.get("actual_accounting") != expected_accounting:
        raise MatrixError(f"{path.name}: task/stream actual accounting totals differ")

    expected_memory = {
        field: sum(int(record["actual_memory_metrics"][field]) for record in stream_records)
        for field in MEMORY_FIELDS
    }
    if summary.get("actual_memory_metrics") != expected_memory:
        raise MatrixError(f"{path.name}: task/stream memory metric totals differ")

    expected_resolved = sum(record["resolved"] is True for record in stream_records)
    if summary.get("resolved_count") != expected_resolved:
        raise MatrixError(f"{path.name}: task/stream resolved count differs")

    expected_total_tokens = (
        expected_accounting["input_tokens"] + expected_accounting["output_tokens"]
    )
    if summary.get("actual_total_tokens") != expected_total_tokens:
        raise MatrixError(f"{path.name}: task/stream total-token count differs")

    expected_usd = _actual_usd_from_accounting(expected_accounting, pricing)
    task_usd_total = sum(
        (Decimal(str(record["actual_usd"])) for record in stream_records), Decimal(0)
    )
    if (
        summary.get("actual_usd") != expected_usd
        or format(task_usd_total, ".12f") != expected_usd
    ):
        raise MatrixError(f"{path.name}: task/stream actual USD totals differ")


def _aggregate_smoke(results_dir: Path) -> dict[str, Any]:
    expected = {row["target_id"]: row for row in execution_matrix("grader-smoke")}
    records = _result_records(results_dir)
    observed_ids = [value.get("target_id") for _, value in records]
    duplicates = sorted(target for target, count in Counter(observed_ids).items() if count > 1)
    missing = sorted(set(expected) - set(observed_ids))
    unknown = sorted(str(value) for value in set(observed_ids) - set(expected))
    if duplicates or missing or unknown:
        raise MatrixError(f"result target mismatch: missing={missing}, duplicate={duplicates}, unknown={unknown}")
    outcomes = []
    for path, value in records:
        target = expected[value["target_id"]]
        if value.get("execution_status") != "SUCCESS" or value.get("grader_exit_code") != 0:
            raise MatrixError(f"{path.name}: grader task failed")
        if value.get("official_grader") is not True:
            raise MatrixError(f"{path.name}: result is not an official grader result")
        locked_digest = target["image"].rsplit("@", 1)[1]
        report_digest = _report_image_digest(path, value, target["image"])
        if (value.get("expected_image_digest") != locked_digest
                or value.get("observed_image_digest") != locked_digest
                or report_digest != locked_digest):
            raise MatrixError(f"{path.name}: lock/record/report image digest mismatch")
        if value.get("resolved") is not target.get("expected_resolved"):
            raise MatrixError(f"{path.name}: GOLD/NOOP expectation failed")
        for stream in ("stdout", "stderr", "checkout"):
            _evidence_file(path, value, stream)
        _restricted_evidence(path, value)
        outcomes.append({
            "benchmark_id": target["benchmark_id"],
            "resolved": value["resolved"],
            "target_id": value["target_id"],
        })
    return {"expected_target_count": len(expected), "observed_target_count": len(records),
            "outcomes": sorted(outcomes, key=lambda row: row["target_id"]), "status": "PASS"}


def _aggregate_benchmark(name: str, results_dir: Path) -> dict[str, Any]:
    manifest = _load(manifest_path(name))
    targets = _validate_target_set(manifest, ordered=True)
    benchmark_roles = _validate_benchmark_roles(manifest, targets)
    images = _locked_images(benchmark=True)
    cost_plan = _load(ROOT / "configs/trimem_v1/cost_plan.json")
    pricing = cost_plan.get("model_pricing")
    if not isinstance(pricing, dict):
        raise MatrixError("frozen model pricing is missing")
    expected_sequence = sequence_sha256(targets)
    target_by_id = {row["target_id"]: row for row in targets}
    records = _result_records(results_dir)
    expected_streams = DEVELOPMENT_STREAMS if name == "development" else ARMS
    observed_keys = [(row.get("arm"), row.get("target_id")) for _, row in records]
    expected_keys = {(stream, row["target_id"]) for stream in expected_streams for row in targets}
    duplicates = sorted(key for key, count in Counter(observed_keys).items() if count > 1)
    missing, unknown = sorted(expected_keys - set(observed_keys)), sorted(set(observed_keys) - expected_keys)
    if duplicates or missing or unknown:
        raise MatrixError(f"task-arm result mismatch: missing={missing}, duplicate={duplicates}, unknown={unknown}")
    namespaces: dict[str, str] = {}
    outcomes = []
    selected_candidate_id: str
    selection_evidence: dict[str, Any] | None = None
    if name == "development":
        selection_path = results_dir / "development-selection.json"
        selection_evidence = _load(selection_path)
        if selection_evidence.get("schema") != "trimem/development-m2-selection-evidence/1.0":
            raise MatrixError("development selection evidence schema mismatch")
        recalculated = select_development_candidate(selection_evidence.get("candidate_summaries", []))
        if selection_evidence.get("selection") != recalculated:
            raise MatrixError("development M2 selection is not deterministic")
        selected_candidate_id = str(recalculated["selected_candidate_id"])
    else:
        try:
            selected_candidate_id = str(validate_selected_m2(require_frozen=True)["selected_candidate_id"])
        except ValueError as exc:
            raise MatrixError(str(exc)) from exc
    for path, value in records:
        arm, target = value["arm"], target_by_id[value["target_id"]]
        if value.get("benchmark_id") != target["benchmark_id"]:
            raise MatrixError(f"{path.name}: benchmark identity differs from frozen target")
        runtime_arm = "M2" if arm.startswith("M2-") else arm
        if value.get("runtime_arm") != runtime_arm or runtime_arm not in ARMS:
            raise MatrixError(f"{path.name}: runtime arm/stream identity mismatch")
        if value.get("sequence_index") != target["order_index"] or value.get("sequence_sha256") != expected_sequence:
            raise MatrixError(f"{path.name}: frozen task sequence mismatch")
        namespace = value.get("namespace")
        if not isinstance(namespace, str) or not namespace:
            raise MatrixError(f"{path.name}: durable namespace is missing")
        if arm in namespaces and namespaces[arm] != namespace:
            raise MatrixError(f"{path.name}: arm namespace changed during stream")
        namespaces[arm] = namespace
        if value.get("execution_status") != "SUCCESS" or value.get("grader_exit_code") != 0:
            raise MatrixError(f"{path.name}: task-arm execution failed")
        if value.get("official_grader") is not True or not isinstance(value.get("resolved"), bool):
            raise MatrixError(f"{path.name}: official grader result is absent")
        prompt_candidate = arm.removeprefix("M2-") if arm.startswith("M2-") else selected_candidate_id
        if value.get("selected_prompt_candidate_id") != prompt_candidate:
            raise MatrixError(f"{path.name}: selected/candidate prompt identity mismatch")
        expected_runtime = "sha256:" + runtime_lock_for(prompt_candidate).content_hash
        if value.get("runtime_lock_sha256") != expected_runtime:
            raise MatrixError(f"{path.name}: frozen RuntimeLock mismatch")
        expected_policy_hash = None
        if runtime_arm == "M2":
            expected_policy_hash = "sha256:" + hashlib.sha256(
                _canonical(load_candidate_policy(prompt_candidate))
            ).hexdigest()
        if value.get("m2_policy_manifest_sha256") != expected_policy_hash:
            raise MatrixError(f"{path.name}: full M2 policy manifest binding mismatch")
        identity_seed_digest = value.get("identity_seed_digest")
        if not isinstance(identity_seed_digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", identity_seed_digest) is None:
            raise MatrixError(f"{path.name}: canonical admin seed evidence binding is missing")
        locked = images.get(target["instance_id"])
        if locked is None:
            raise MatrixError(f"{path.name}: frozen image lock is missing")
        locked_digest = locked.rsplit("@", 1)[1]
        report_digest = _report_image_digest(path, value, locked)
        if (value.get("expected_image_digest") != locked_digest
                or value.get("observed_image_digest") != locked_digest
                or report_digest != locked_digest):
            raise MatrixError(f"{path.name}: lock/record/report image digest mismatch")
        accounting = value.get("actual_accounting")
        if not isinstance(accounting, dict) or set(accounting) != set(ACCOUNTING_FIELDS):
            raise MatrixError(f"{path.name}: actual call/token accounting is incomplete")
        if any(type(accounting[field]) is not int or accounting[field] < 0 for field in ACCOUNTING_FIELDS):
            raise MatrixError(f"{path.name}: actual accounting must be non-negative integers")
        try:
            task_actual_usd = Decimal(str(value.get("actual_usd")))
        except InvalidOperation as exc:
            raise MatrixError(f"{path.name}: exact task-arm actual USD is missing") from exc
        if task_actual_usd < 0 or str(value.get("actual_usd")) != format(task_actual_usd, ".12f"):
            raise MatrixError(f"{path.name}: task-arm actual USD must be a non-negative 12-place decimal string")
        if str(value.get("actual_usd")) != _actual_usd_from_accounting(
            accounting, pricing
        ):
            raise MatrixError(
                f"{path.name}: task-arm actual USD differs from frozen pricing/accounting"
            )
        if accounting["decomposition_calls"] != 1 or accounting["extraction_calls"] != 1:
            raise MatrixError(f"{path.name}: common decomposition/extraction path was not used exactly once")
        if not 1 <= accounting["solve_calls"] <= 24:
            raise MatrixError(f"{path.name}: solve-call count is outside the frozen common budget")
        if accounting["model_gateway_calls"] != (
            accounting["solve_calls"] + accounting["decomposition_calls"] + accounting["extraction_calls"]
        ):
            raise MatrixError(f"{path.name}: model gateway call total is inconsistent")
        if accounting["paid_model_calls"] != accounting["model_gateway_calls"]:
            raise MatrixError(f"{path.name}: benchmark model calls are not all provider-accounted paid calls")
        if (accounting["grader_calls"], accounting["grader_containers"], accounting["official_grader_runs"]) != (1, 1, 1):
            raise MatrixError(f"{path.name}: exact official grader/container accounting mismatch")
        memory = value.get("actual_memory_metrics")
        if not isinstance(memory, dict) or set(memory) != set(MEMORY_FIELDS):
            raise MatrixError(f"{path.name}: actual retrieval/memory accounting is incomplete")
        if any(type(memory[field]) is not int for field in MEMORY_FIELDS):
            raise MatrixError(f"{path.name}: memory accounting must contain exact integers")
        if any(memory[field] < 0 for field in MEMORY_FIELDS if field != "net_memory_growth"):
            raise MatrixError(f"{path.name}: memory accounting cannot contain negative counts")
        if memory["injected_records"] != sum(memory[field] for field in (
            "episodic_injections", "user_semantic_injections", "org_semantic_injections"
        )):
            raise MatrixError(f"{path.name}: memory-bank injection counts do not add up")
        if memory["net_memory_growth"] != memory["retained_records"] - memory["archived_records"]:
            raise MatrixError(f"{path.name}: net memory growth arithmetic mismatch")
        if runtime_arm == "M0" and any(memory[field] for field in (
            "injected_records", "retained_records", "archived_records", "net_memory_growth"
        )):
            raise MatrixError(f"{path.name}: M0 mutated or injected memory")
        for stream in ("stdout", "stderr", "raw_events", "checkout"):
            _evidence_file(path, value, stream)
        _terminal_checkpoint(path, value)
        _restricted_evidence(path, value)
        outcomes.append({
            "arm": arm, "benchmark_id": target["benchmark_id"],
            "benchmark_role": next(
                row["role"] for row in benchmark_roles
                if row["benchmark_id"] == target["benchmark_id"]
            ),
            "resolved": value["resolved"], "target_id": value["target_id"],
            "actual_accounting": accounting, "actual_memory_metrics": memory,
            "actual_usd": str(value["actual_usd"]),
        })
    if len(set(namespaces.values())) != len(expected_streams):
        raise MatrixError("task-arm durable namespaces are not isolated")
    summaries = []
    summary_paths = sorted(results_dir.rglob("*.arm-summary.json"))
    if len(summary_paths) != len(expected_streams):
        raise MatrixError("benchmark stream summary count mismatch")
    for path in summary_paths:
        row = _load(path)
        arm = row.get("arm")
        if arm not in expected_streams or any(summary.get("arm") == arm for summary in summaries):
            raise MatrixError(f"{path.name}: duplicate or unknown arm summary")
        if row.get("sequence_sha256") != expected_sequence or row.get("final_resume_cursor") != len(targets):
            raise MatrixError(f"{path.name}: incomplete serial stream or invalid resume cursor")
        if row.get("namespace") != namespaces[arm] or row.get("status") != "PASS":
            raise MatrixError(f"{path.name}: namespace/status mismatch")
        stream_seed_digests = {
            record.get("identity_seed_digest") for _, record in records
            if record.get("arm") == arm
        }
        if stream_seed_digests != {row.get("identity_seed_digest")}:
            raise MatrixError(f"{path.name}: stream identity seed digest drift")
        stream_records = [record for _, record in records if record.get("arm") == arm]
        _validate_stream_summary_totals(path, row, stream_records, pricing)
        summaries.append(row)
    if {row["arm"] for row in summaries} != set(expected_streams):
        raise MatrixError("benchmark stream summaries are incomplete")
    if name == "development":
        compact = {row.get("candidate_id"): row for row in summaries if str(row.get("arm", "")).startswith("M2-")}
        evidence_rows = {
            row.get("candidate_id"): row for row in (selection_evidence or {}).get("candidate_summaries", [])
            if isinstance(row, dict)
        }
        if set(compact) != set(CANDIDATE_IDS) or set(evidence_rows) != set(CANDIDATE_IDS):
            raise MatrixError("development candidate summary set mismatch")
        for candidate_id in CANDIDATE_IDS:
            summary = compact[candidate_id]
            evidence = evidence_rows[candidate_id]
            for field in (
                "completed_target_count", "final_resume_cursor", "resolved_count",
                "actual_total_tokens", "actual_usd", "sequence_sha256", "runtime_lock_sha256",
                "m2_policy_manifest_sha256", "namespace",
            ):
                if summary.get(field) != evidence.get(field):
                    raise MatrixError(f"development selection evidence drift: {candidate_id}.{field}")
    benchmark_totals = _benchmark_endpoint_totals(
        outcomes, tuple(expected_streams), benchmark_roles
    )
    return {"arms": list(expected_streams), "selected_candidate_id": selected_candidate_id,
            "benchmark_roles": benchmark_roles,
            "benchmark_totals": benchmark_totals,
            "primary_endpoints": [
                row for row in benchmark_totals if row["reporting_role"] == "PRIMARY"
            ],
            "secondary_endpoints": [
                row for row in benchmark_totals if row["reporting_role"] == "SECONDARY"
            ],
            "expected_task_arm_count": len(expected_keys),
            "observed_task_arm_count": len(records),
            "outcomes": sorted(outcomes, key=lambda row: (row["arm"], row["target_id"])),
            "stream_totals": sorted(({
                "arm": row["arm"],
                "actual_accounting": row.get("actual_accounting"),
                "actual_memory_metrics": row.get("actual_memory_metrics"),
                "actual_usd": row.get("actual_usd"),
                "identity_seed_digest": row.get("identity_seed_digest"),
                "reporting_scope": "DESCRIPTIVE_POOLED_ALL_BENCHMARKS",
                "resolved_count": row.get("resolved_count"),
            } for row in summaries), key=lambda row: row["arm"]),
            "sequence_sha256": expected_sequence, "status": "PASS"}


def aggregate(name: str, results_dir: Path) -> dict[str, Any]:
    report = (
        _aggregate_smoke(results_dir)
        if name == "grader-smoke"
        else _aggregate_benchmark(name, results_dir)
    )
    return _seal_aggregate(name, results_dir, report)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    emit = sub.add_parser("emit")
    emit.add_argument("--manifest", choices=sorted(ALLOWED_MANIFESTS), required=True)
    aggregate_parser = sub.add_parser("aggregate")
    aggregate_parser.add_argument("--manifest", choices=sorted(ALLOWED_MANIFESTS), required=True)
    aggregate_parser.add_argument("--results-dir", type=Path, required=True)
    aggregate_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "emit":
            print(json.dumps({"include": execution_matrix(args.manifest)}, ensure_ascii=False,
                             separators=(",", ":"), sort_keys=True))
        else:
            report = aggregate(args.manifest, args.results_dir.resolve())
            _write_json(args.output.resolve(), report)
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    except (MatrixError, OSError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
