"""Emit only committed TriMem matrices and aggregate them fail closed.

Online memory is a serial stream. Development and held-out execution therefore
parallelize by arm only; task-level modulo sharding is deliberately unsupported.
The independent GOLD/NOOP_BASELINE grader smoke is one frozen serial sequence.
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
from trimem_grader_smoke_protocol import (  # noqa: E402
    NOOP_BASELINE_LOCK,
    NOOP_BASELINE_PATCH,
    SmokeProtocolError,
    validate_serial_targets,
)
from trimem_exec_approval import (  # noqa: E402
    ApprovalValidationError,
    validate_external_approval_document,
)
from trimem_grader_smoke_trigger_preflight import (  # noqa: E402
    SENTINEL_PATH as GRADER_SMOKE_SENTINEL_PATH,
)
from trimem_select_targets import (  # noqa: E402
    SelectionError,
    instance_id as source_instance_id,
    load_sources,
    row_hash,
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
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")
SMOKE_EXECUTION_CONTRACT_FIELDS = {
    "schema",
    "profile",
    "execution_mode",
    "human_mode",
    "force_build",
    "need_clone",
    "report_module",
    "report_mode",
    "source_image_build_calls",
    "host_prepare_script_reads",
    "submitted_patch_bytes",
    "submitted_patch_sha256",
    "patch_transport",
    "api_calls",
}
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
        if ordered and (
            type(target.get("order_index")) is not int
            or target.get("order_index") != position
        ):
            raise MatrixError(f"target order_index mismatch at position {position}")
    return targets


def _validate_smoke_protocol(
    manifest: dict[str, Any], targets: list[dict[str, Any]]
) -> None:
    try:
        validate_serial_targets(
            matrix_kind=manifest.get("matrix_kind"),
            noop_baseline=manifest.get("noop_baseline"),
            targets=targets,
        )
    except SmokeProtocolError as exc:
        raise MatrixError(str(exc)) from exc


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


def _locked_harness_revisions() -> dict[str, str]:
    lock = _load(ROOT / "configs/trimem_v1/grader_lock.json")
    rows = lock.get("harnesses")
    if not isinstance(rows, list) or len(rows) != 2:
        raise MatrixError("frozen official harness registry is missing")
    result: dict[str, str] = {}
    for row in rows:
        benchmark_ids = row.get("benchmark_ids") if isinstance(row, dict) else None
        revision = row.get("revision") if isinstance(row, dict) else None
        if (
            not isinstance(benchmark_ids, list)
            or not benchmark_ids
            or not HEX40.fullmatch(str(revision))
        ):
            raise MatrixError("frozen official harness registry is malformed")
        for benchmark_id in benchmark_ids:
            if not isinstance(benchmark_id, str) or benchmark_id in result:
                raise MatrixError("frozen official harness registry is duplicated")
            result[benchmark_id] = revision
    expected = {"swebench_verified", "multi_swe_bench_mini", "multi_swe_bench_flash"}
    if set(result) != expected:
        raise MatrixError("frozen official harness registry coverage differs")
    return result


def execution_matrix(name: str) -> list[dict[str, Any]]:
    manifest = _load(manifest_path(name))
    if name == "grader-smoke":
        targets = _validate_target_set(manifest, ordered=True)
        _validate_smoke_protocol(manifest, targets)
        images = _locked_images()
        rows = []
        for target in targets:
            instance_id = target.get("instance_id")
            if instance_id not in images:
                raise MatrixError(f"missing grader image lock for {instance_id}")
            rows.append({**target, "image": images[instance_id]})
        return rows
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


def _json_evidence(result_file: Path, record: dict[str, Any], name: str) -> dict[str, Any]:
    raw = _evidence_file(result_file, record, name)
    try:
        value = _strict_loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatrixError(f"{result_file.name}: {name} evidence is invalid JSON") from exc
    if not isinstance(value, dict):
        raise MatrixError(f"{result_file.name}: {name} evidence is not an object")
    return value


def _strict_string_list(value: Any, *, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise MatrixError(f"{label} is not a unique non-empty string list")
    return value


def _exact_int(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


def _multi_test_result(value: Any, *, label: str) -> dict[str, int]:
    required = {
        "passed_count", "failed_count", "skipped_count",
        "passed_tests", "failed_tests", "skipped_tests",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise MatrixError(f"{label} test result field set drift")
    classified: dict[str, list[str]] = {}
    for kind in ("passed", "failed", "skipped"):
        rows = _strict_string_list(value[f"{kind}_tests"], label=f"{label}.{kind}_tests")
        count = value.get(f"{kind}_count")
        if type(count) is not int or count != len(rows):
            raise MatrixError(f"{label}.{kind}_count differs from classified tests")
        classified[kind] = rows
    if any(
        set(classified[left]) & set(classified[right])
        for left, right in (("passed", "failed"), ("passed", "skipped"), ("failed", "skipped"))
    ):
        raise MatrixError(f"{label} test result classifications overlap")
    return {f"{kind}_count": len(classified[kind]) for kind in classified}


def _validate_smoke_test_status(
    result_file: Path,
    target: dict[str, Any],
    status: dict[str, Any],
    summary: dict[str, Any],
    *,
    resolved: bool,
    source_row: dict[str, Any],
) -> None:
    benchmark_id = target["benchmark_id"]
    common = {
        "schema": "trimem/official-test-status-summary/1.0",
        "benchmark_id": benchmark_id,
        "resolved": resolved,
    }
    if any(summary.get(field) != value for field, value in common.items()):
        raise MatrixError(f"{result_file.name}: official test summary identity/result mismatch")
    if benchmark_id == "swebench_verified":
        if set(status) != {target["instance_id"]}:
            raise MatrixError(f"{result_file.name}: SWE test-status target set mismatch")
        instance = status[target["instance_id"]]
        tests = instance.get("tests_status") if isinstance(instance, dict) else None
        if not isinstance(tests, dict) or not {"FAIL_TO_PASS", "PASS_TO_PASS"} <= set(tests):
            raise MatrixError(f"{result_file.name}: SWE official test-status structure is missing")
        counts: dict[str, tuple[int, int]] = {}
        expected_sets: dict[str, list[str]] = {}
        for group in ("FAIL_TO_PASS", "PASS_TO_PASS"):
            expected_value = source_row.get(group)
            if isinstance(expected_value, str):
                try:
                    expected_value = _strict_loads(expected_value)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise MatrixError(f"{result_file.name}: frozen {group} source is invalid") from exc
            expected = _strict_string_list(
                expected_value, label=f"{result_file.name}:source.{group}"
            )
            expected_sets[group] = expected
            row = tests.get(group)
            if not isinstance(row, dict) or set(row) != {"success", "failure"}:
                raise MatrixError(f"{result_file.name}: SWE {group} status field set drift")
            success = _strict_string_list(row["success"], label=f"{result_file.name}:{group}.success")
            failure = _strict_string_list(row["failure"], label=f"{result_file.name}:{group}.failure")
            if (
                set(success) & set(failure)
                or set(success) | set(failure) != set(expected)
            ):
                raise MatrixError(f"{result_file.name}: SWE {group} classifications overlap")
            counts[group] = (len(success) + len(failure), len(failure))
        computed_resolved = counts["FAIL_TO_PASS"][1] == 0
        if (
            counts["FAIL_TO_PASS"][0] <= 0
            or counts["PASS_TO_PASS"][1] != 0
            or not isinstance(instance, dict)
            or instance.get("patch_exists") is not True
            or instance.get("patch_is_None") is not False
            or instance.get("patch_successfully_applied") is not True
            or instance.get("infra_failure") is not False
            or instance.get("resolved") is not computed_resolved
            or computed_resolved is not resolved
            or summary.get("source") != "SWE_PER_INSTANCE_REPORT"
            or summary.get("fail_to_pass_expected") != counts["FAIL_TO_PASS"][0]
            or summary.get("fail_to_pass_classified") != counts["FAIL_TO_PASS"][0]
            or summary.get("fail_to_pass_failures") != counts["FAIL_TO_PASS"][1]
            or summary.get("pass_to_pass_expected") != counts["PASS_TO_PASS"][0]
            or summary.get("pass_to_pass_classified") != counts["PASS_TO_PASS"][0]
            or summary.get("pass_to_pass_regressions") != 0
            or summary.get("expected_test_spec_sha256") != hashlib.sha256(_canonical({
                group: sorted(expected_sets[group])
                for group in ("FAIL_TO_PASS", "PASS_TO_PASS")
            })).hexdigest()
        ):
            raise MatrixError(f"{result_file.name}: SWE actual test proof is incomplete")
        return

    parts = target["instance_id"].split("__", 1)
    if len(parts) != 2 or "-" not in parts[1]:
        raise MatrixError(f"{result_file.name}: Multi-SWE target identity is invalid")
    org, repo_number = parts
    repo, number = repo_number.rsplit("-", 1)
    if (
        status.get("org") != org
        or status.get("repo") != repo
        or str(status.get("number")) != number
        or status.get("valid") is not resolved
    ):
        raise MatrixError(f"{result_file.name}: Multi-SWE test-status identity/result mismatch")
    results = {
        name: _multi_test_result(status.get(name), label=f"{result_file.name}:{name}")
        for name in ("run_result", "test_patch_result", "fix_patch_result")
    }
    for name in ("fixed_tests", "p2p_tests", "f2p_tests", "s2p_tests", "n2p_tests"):
        if not isinstance(status.get(name), dict):
            raise MatrixError(f"{result_file.name}: Multi-SWE {name} is missing")
    fix = results["fix_patch_result"]
    classified = sum(fix.values())
    if (
        classified <= 0
        or summary.get("source") != "MULTI_SWE_PER_INSTANCE_REPORT"
        or summary.get("fix_tests_classified") != classified
        or summary.get("fix_tests_passed") != fix["passed_count"]
        or summary.get("fix_tests_failed") != fix["failed_count"]
        or summary.get("fix_tests_skipped") != fix["skipped_count"]
    ):
        raise MatrixError(f"{result_file.name}: Multi-SWE actual test proof is incomplete")


def _restricted_evidence(result_file: Path, record: dict[str, Any]) -> None:
    references = record.get("evidence", {}).get("restricted_grader_raw")
    if not isinstance(references, list) or not references:
        raise MatrixError(f"{result_file.name}: restricted grader evidence list is missing")
    observed: set[tuple[str, str, int]] = set()
    for index, reference in enumerate(references):
        relative = reference.get("path") if isinstance(reference, dict) else None
        if (
            not isinstance(reference, dict)
            or set(reference) != {"path", "sha256", "bytes"}
            or not isinstance(relative, str)
            or not relative.startswith("official-grader/restricted-evidence/")
            or not isinstance(reference.get("sha256"), str)
            or SHA256.fullmatch(reference["sha256"]) is None
            or type(reference.get("bytes")) is not int
            or reference["bytes"] < 0
        ):
            raise MatrixError(f"{result_file.name}: restricted grader evidence shape differs")
        if any(row[0] == relative for row in observed):
            raise MatrixError(f"{result_file.name}: duplicate restricted grader evidence path")
        _evidence_reference(result_file, reference, f"restricted_grader_raw[{index}]")
        observed.add((str(relative), str(reference["sha256"]), reference["bytes"]))

    report = _json_evidence(result_file, record, "report")
    trimem = report.get("_trimem")
    if not isinstance(trimem, dict):
        raise MatrixError(f"{result_file.name}: official report has no TriMem evidence root")
    expected: set[tuple[str, str, int]] = set()

    def require_streams(value: Any, label: str) -> None:
        if not isinstance(value, dict) or set(value) != {"stdout", "stderr"}:
            raise MatrixError(f"{result_file.name}: {label} raw stream references differ")
        for stream, reference in value.items():
            if (
                not isinstance(reference, dict)
                or not isinstance(reference.get("path"), str)
                or not reference["path"].startswith("restricted-evidence/")
            ):
                raise MatrixError(
                    f"{result_file.name}: {label}.{stream} raw reference is malformed"
                )

    require_streams(trimem.get("harness_restricted_raw_streams"), "official harness")
    image_evidence = trimem.get("image_evidence")
    expected_image_rows = 2 if str(record.get("benchmark_id")).startswith("multi_swe_bench") else 1
    if not isinstance(image_evidence, list) or len(image_evidence) != expected_image_rows:
        raise MatrixError(f"{result_file.name}: image raw evidence coverage differs")
    for index, image_row in enumerate(image_evidence):
        if not isinstance(image_row, dict):
            raise MatrixError(f"{result_file.name}: image raw evidence row is malformed")
        require_streams(
            image_row.get("inspect_restricted_raw_streams"),
            f"image[{index}] inspect",
        )
        require_streams(
            image_row.get("tag_restricted_raw_streams"),
            f"image[{index}] tag",
        )

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            relative = value.get("path")
            digest = value.get("sha256")
            byte_count = value.get("bytes")
            if (
                isinstance(relative, str)
                and relative.startswith("restricted-evidence/")
                and isinstance(digest, str)
                and SHA256.fullmatch(digest)
                and type(byte_count) is int
                and byte_count >= 0
            ):
                expected.add(("official-grader/" + relative, digest, byte_count))
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(trimem)
    if not expected or observed != expected:
        raise MatrixError(
            f"{result_file.name}: restricted grader raw evidence exact set differs"
        )


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
            or expected not in observed or any(not OCI_DIGEST.fullmatch(str(item)) for item in observed)):
        raise MatrixError(f"{result_file.name}: official report does not prove inspected digest equality")
    return expected


def _validate_smoke_completion_report(
    result_file: Path,
    target: dict[str, Any],
    report: dict[str, Any],
    *,
    resolved: bool,
) -> None:
    if target["benchmark_id"] == "swebench_verified":
        identity = target["instance_id"]
    else:
        org, repo_number = target["instance_id"].split("__", 1)
        repo, number = repo_number.rsplit("-", 1)
        identity = f"{org}/{repo}:pr-{number}"
    ids = {
        field: _strict_string_list(report.get(field), label=f"{result_file.name}:{field}")
        for field in (
            "submitted_ids", "completed_ids", "incomplete_ids", "resolved_ids",
            "unresolved_ids", "empty_patch_ids", "error_ids",
        )
    }
    if target["benchmark_id"] == "swebench_verified":
        for field in ("infra_failure_ids", "ambiguous_failure_ids"):
            ids[field] = _strict_string_list(
                report.get(field), label=f"{result_file.name}:{field}"
            )
    classified = ids["resolved_ids"] if resolved else ids["unresolved_ids"]
    opposite = ids["unresolved_ids"] if resolved else ids["resolved_ids"]
    common_invalid = (
        not _exact_int(report.get("total_instances"), 1)
        or not _exact_int(report.get("submitted_instances"), 1)
        or not _exact_int(report.get("completed_instances"), 1)
        or not _exact_int(report.get("empty_patch_instances"), 0)
        or not _exact_int(report.get("error_instances"), 0)
        or ids["submitted_ids"] != [identity]
        or ids["completed_ids"] != [identity]
        or classified != [identity]
        or opposite
        or ids["incomplete_ids"]
        or ids["empty_patch_ids"]
        or ids["error_ids"]
        or ids.get("infra_failure_ids", [])
        or ids.get("ambiguous_failure_ids", [])
        or not _exact_int(report.get("resolved_instances"), len(ids["resolved_ids"]))
        or not _exact_int(report.get("unresolved_instances"), len(ids["unresolved_ids"]))
        or not _exact_int(report.get("empty_patch_instances"), len(ids["empty_patch_ids"]))
        or not _exact_int(report.get("error_instances"), len(ids["error_ids"]))
    )
    if target["benchmark_id"] == "swebench_verified":
        benchmark_invalid = (
            report.get("schema_version") != 2
            or not _exact_int(
                report.get("infra_failure_instances"), len(ids["infra_failure_ids"])
            )
            or not _exact_int(
                report.get("ambiguous_failure_instances"),
                len(ids["ambiguous_failure_ids"]),
            )
        )
    else:
        benchmark_invalid = (
            not _exact_int(report.get("incomplete_instances"), len(ids["incomplete_ids"]))
        )
    if common_invalid or benchmark_invalid:
        raise MatrixError(f"{result_file.name}: final official report is incomplete or has an empty patch")


def _expected_smoke_execution_contract(
    target: dict[str, Any], raw_patch: bytes
) -> dict[str, Any]:
    common = {
        "schema": "trimem/official-grader-execution-contract/1.0",
        "source_image_build_calls": 0,
        "host_prepare_script_reads": 0,
        "submitted_patch_bytes": len(raw_patch),
        "submitted_patch_sha256": hashlib.sha256(raw_patch).hexdigest(),
        "api_calls": 0,
    }
    if target.get("benchmark_id") == "swebench_verified":
        return {
            **common,
            "profile": "SWE_BENCH_OFFICIAL_PREDICTION",
            "execution_mode": "evaluation",
            "human_mode": None,
            "force_build": None,
            "need_clone": None,
            "report_module": "swebench.harness.run_evaluation",
            "report_mode": "inline",
            "patch_transport": {
                "host_source": "prediction.jsonl.model_patch",
                "container_destination": None,
                "mode": None,
            },
        }
    if str(target.get("benchmark_id", "")).startswith("multi_swe_bench_"):
        return {
            **common,
            "profile": "MULTI_SWE_PREBUILT_EVALUATION",
            "execution_mode": "instance_only",
            "human_mode": True,
            "force_build": False,
            "need_clone": False,
            "report_module": "multi_swe_bench.harness.gen_report",
            "report_mode": "evaluation",
            "patch_transport": {
                "host_source": "evaluation_instance_fix.patch",
                "container_destination": "/home/fix.patch",
                "mode": "rw",
            },
        }
    raise MatrixError(f"unsupported smoke benchmark execution contract: {target.get('benchmark_id')}")


def _validate_smoke_execution_contract(
    result_file: Path,
    target: dict[str, Any],
    raw_patch: bytes,
    report: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    """Bind the adapter contract to the exact retained submitted-patch bytes."""

    trimem = report.get("_trimem")
    report_contract = (
        trimem.get("execution_contract") if isinstance(trimem, dict) else None
    )
    if (
        not isinstance(report_contract, dict)
        or set(report_contract) != SMOKE_EXECUTION_CONTRACT_FIELDS
    ):
        raise MatrixError(
            f"{result_file.name}: official report execution-contract evidence is missing"
        )
    expected = _expected_smoke_execution_contract(target, raw_patch)
    if _canonical(report_contract) != _canonical(expected):
        raise MatrixError(
            f"{result_file.name}: official report execution-contract evidence drift"
        )

    evidence = _json_evidence(result_file, record, "execution_contract")
    contract_sha256 = hashlib.sha256(_canonical(report_contract)).hexdigest()
    if (
        set(evidence)
        != {
            "schema",
            "target_id",
            "execution_contract_sha256",
            "execution_contract",
        }
        or evidence.get("schema")
        != "trimem/grader-smoke-execution-contract-evidence/1.0"
        or evidence.get("target_id") != target["target_id"]
        or evidence.get("execution_contract_sha256") != contract_sha256
        or _canonical(evidence.get("execution_contract")) != _canonical(report_contract)
        or record.get("execution_contract_sha256") != contract_sha256
    ):
        raise MatrixError(
            f"{result_file.name}: submitted-patch execution-contract binding mismatch"
        )

    return {
        "execution_contract_sha256": contract_sha256,
        "execution_contract": report_contract,
    }


def _expected_smoke_execution_control(
    target: dict[str, Any], expected_harness_revision: str
) -> dict[str, Any]:
    common = {
        "schema": "trimem/official-grader-execution-control/1.0",
        "harness_revision": expected_harness_revision,
        "source_image_build_calls": 0,
        "host_prepare_script_reads": 0,
    }
    if target.get("benchmark_id") == "swebench_verified":
        return {
            **common,
            "profile": "SWE_BENCH_OFFICIAL_PREDICTION",
            "proof_basis": "PINNED_CONTROL_FLOW_AND_FIXED_ARGV",
            "dispatch": "main(task_repo=None,rewrite_reports=False)->run_instances",
            "source_build_guard": {
                "expression": "task_repo and not rewrite_reports",
                "task_repo_argv_present": False,
                "rewrite_reports_argv_present": False,
                "evaluates": False,
            },
            "structurally_excluded_calls": ["_build_before_eval"],
        }
    return {
        **common,
        "profile": "MULTI_SWE_PREBUILT_EVALUATION",
        "proof_basis": "PINNED_CONTROL_FLOW_AND_ADAPTER_CONSTRUCTION_INVARIANT",
        "dispatch": (
            "trimem_multi_swe_entrypoint.execute_pinned_instance_only"
            "->CliArgs.run(instance_only)->run_mode_instance_only"
        ),
        "support_container_bootstrap_calls": 0,
        "upstream_module_main_executed": False,
        "structurally_excluded_calls": [
            "run_evaluation.__main__.nix_swe_bootstrap",
            "run_mode_image",
            "check_commit_hashes",
            "build_image",
            "run_and_save_logs",
        ],
    }


def _validate_smoke_execution_control(
    result_file: Path,
    target: dict[str, Any],
    expected_harness_revision: str,
    report: dict[str, Any],
    record: dict[str, Any],
    execution_contract: dict[str, Any],
) -> dict[str, Any]:
    trimem = report.get("_trimem")
    control = (
        trimem.get("execution_control_evidence")
        if isinstance(trimem, dict)
        else None
    )
    expected = _expected_smoke_execution_control(target, expected_harness_revision)
    if not isinstance(control, dict) or _canonical(control) != _canonical(expected):
        raise MatrixError(
            f"{result_file.name}: official execution-control evidence drift"
        )
    if (
        control["profile"] != execution_contract.get("profile")
        or control["source_image_build_calls"]
        != execution_contract.get("source_image_build_calls")
        or control["host_prepare_script_reads"]
        != execution_contract.get("host_prepare_script_reads")
    ):
        raise MatrixError(
            f"{result_file.name}: execution-control/contract counter binding differs"
        )
    control_sha256 = hashlib.sha256(_canonical(control)).hexdigest()
    evidence = _json_evidence(result_file, record, "execution_control")
    if (
        set(evidence)
        != {
            "schema",
            "target_id",
            "execution_control_sha256",
            "execution_control",
        }
        or evidence.get("schema")
        != "trimem/grader-smoke-execution-control-evidence/1.0"
        or evidence.get("target_id") != target["target_id"]
        or evidence.get("execution_control_sha256") != control_sha256
        or _canonical(evidence.get("execution_control")) != _canonical(control)
        or record.get("execution_control_sha256") != control_sha256
    ):
        raise MatrixError(
            f"{result_file.name}: direct execution-control evidence binding differs"
        )
    return {
        "execution_control_sha256": control_sha256,
        "host_prepare_sh_access_count": control["host_prepare_script_reads"],
        "source_image_build_count": control["source_image_build_calls"],
    }


def _smoke_prediction_input_bytes(
    target: dict[str, Any], raw_patch: bytes
) -> bytes:
    patch = raw_patch.decode("utf-8")
    if target.get("benchmark_id") == "swebench_verified":
        value = {
            "instance_id": target["instance_id"],
            "model_patch": patch,
            "model_name_or_path": f"trimem-v1-smoke-{str(target['probe']).lower()}",
        }
    else:
        repository, number = target["instance_id"].rsplit("-", 1)
        org, repo = repository.split("__", 1)
        value = {"org": org, "repo": repo, "number": number, "fix_patch": patch}
    return _canonical(value) + b"\n"


def _validate_smoke_submitted_patch_identity(
    result_file: Path,
    target: dict[str, Any],
    raw_patch: bytes,
    report: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    trimem = report.get("_trimem")
    private_inputs = (
        trimem.get("materialized_private_inputs") if isinstance(trimem, dict) else None
    )
    expected_names = (
        ["dataset.json", "prediction.jsonl"]
        if target.get("benchmark_id") == "swebench_verified"
        else ["dataset.jsonl", "prediction.jsonl", "config.json"]
    )
    if not isinstance(private_inputs, list) or len(private_inputs) != len(expected_names):
        raise MatrixError(f"{result_file.name}: private-input identity set differs")
    grader_root = result_file.parent / "official-grader"
    task_relative = target["target_id"].replace("/", "_")
    task_root = (grader_root / task_relative).resolve()
    if grader_root.resolve() not in task_root.parents:
        raise MatrixError(f"{result_file.name}: private-input path escaped grader root")
    normalized_inputs: list[dict[str, Any]] = []
    for expected_name, raw_row in zip(expected_names, private_inputs, strict=True):
        if not isinstance(raw_row, dict) or set(raw_row) != {
            "name", "sha256", "bytes", "retention"
        }:
            raise MatrixError(f"{result_file.name}: private-input evidence fields differ")
        if (
            raw_row.get("name") != expected_name
            or not isinstance(raw_row.get("sha256"), str)
            or SHA256.fullmatch(raw_row["sha256"]) is None
            or type(raw_row.get("bytes")) is not int
            or raw_row["bytes"] <= 0
            or raw_row.get("retention") != "PURGED_AFTER_HASH_BOUND_GRADING"
        ):
            raise MatrixError(f"{result_file.name}: private-input identity drift")
        host_path = task_root / expected_name
        if host_path.exists() or host_path.is_symlink():
            raise MatrixError(f"{result_file.name}: private input was not purged")
        normalized_inputs.append({
            **raw_row,
            "host_path": host_path.relative_to(grader_root.resolve()).as_posix(),
            "purged_after_capture": True,
        })
    prediction_raw = _smoke_prediction_input_bytes(target, raw_patch)
    prediction = normalized_inputs[expected_names.index("prediction.jsonl")]
    if (
        prediction["bytes"] != len(prediction_raw)
        or prediction["sha256"] != hashlib.sha256(prediction_raw).hexdigest()
    ):
        raise MatrixError(
            f"{result_file.name}: prediction input submitted-patch identity differs"
        )

    patch_sha256 = hashlib.sha256(raw_patch).hexdigest()
    applied_patch_ref = record.get("evidence", {}).get("applied_patch")
    if applied_patch_ref != {
        "path": "restricted-input/applied.patch",
        "sha256": patch_sha256,
        "bytes": len(raw_patch),
    }:
        raise MatrixError(f"{result_file.name}: restricted submitted-patch reference differs")
    materialized = (
        trimem.get("materialized_patch_evidence") if isinstance(trimem, dict) else None
    )
    if target.get("benchmark_id") == "swebench_verified":
        if materialized is not None or (
            isinstance(trimem, dict) and "materialized_patch_evidence" in trimem
        ):
            raise MatrixError(
                f"{result_file.name}: SWE route claims materialized host-patch evidence"
            )
        route = "SWE_BENCH_PREDICTION_JSONL"
        normalized_materialized = None
    else:
        required_materialized_fields = {
            "schema",
            "host_path",
            "container_destination",
            "mode",
            "bytes",
            "sha256",
            "request_identity_match",
            "restricted_materialized_patch",
            "purged_after_capture",
        }
        if not isinstance(materialized, dict) or set(materialized) != required_materialized_fields:
            raise MatrixError(
                f"{result_file.name}: Multi-SWE materialized patch evidence is missing"
            )
        repository, number = target["instance_id"].rsplit("-", 1)
        org, repo = repository.split("__", 1)
        expected_host_path = (
            f"{task_relative}/work/{org}/{repo}/evals/pr-{number}/fix.patch"
        )
        expected_restricted_path = (
            "restricted-evidence/submitted-patch-materialized-"
            f"{patch_sha256}.bin"
        )
        restricted = materialized.get("restricted_materialized_patch")
        if (
            materialized.get("schema")
            != "trimem/materialized-submitted-patch-evidence/1.0"
            or materialized.get("host_path") != expected_host_path
            or materialized.get("container_destination") != "/home/fix.patch"
            or materialized.get("mode") != "rw"
            or type(materialized.get("bytes")) is not int
            or materialized["bytes"] != len(raw_patch)
            or materialized.get("sha256") != patch_sha256
            or materialized.get("request_identity_match") is not True
            or materialized.get("purged_after_capture") is not True
            or not isinstance(restricted, dict)
            or set(restricted) != {"path", "sha256", "bytes", "access"}
            or restricted.get("path") != expected_restricted_path
            or restricted.get("sha256") != patch_sha256
            or type(restricted.get("bytes")) is not int
            or restricted["bytes"] != len(raw_patch)
            or restricted.get("access") != "RESTRICTED_RAW_NOT_FOR_PUBLIC_LOGS"
        ):
            raise MatrixError(
                f"{result_file.name}: materialized submitted-patch identity drift"
            )
        restricted_raw = _evidence_reference(
            result_file,
            {
                "path": "official-grader/" + expected_restricted_path,
                "sha256": patch_sha256,
                "bytes": len(raw_patch),
            },
            "restricted materialized submitted patch",
        )
        if restricted_raw != raw_patch:
            raise MatrixError(
                f"{result_file.name}: restricted materialized patch bytes differ"
            )
        materialized_path = (grader_root / expected_host_path).resolve()
        if materialized_path.exists() or materialized_path.is_symlink():
            raise MatrixError(
                f"{result_file.name}: materialized submitted patch was not purged"
            )
        route = "MULTI_SWE_MATERIALIZED_FIX_PATCH"
        normalized_materialized = materialized

    identity_body = {
        "schema": "trimem/grader-smoke-submitted-patch-identity-evidence/1.0",
        "target_id": target["target_id"],
        "benchmark_id": target["benchmark_id"],
        "route": route,
        "submitted_patch_bytes": len(raw_patch),
        "submitted_patch_sha256": patch_sha256,
        "restricted_submitted_patch": applied_patch_ref,
        "prediction_input_identity": prediction,
        "private_input_identities": normalized_inputs,
        "materialized_patch_evidence": normalized_materialized,
        "submitted_patch_identity": True,
    }
    identity_sha256 = hashlib.sha256(_canonical(identity_body)).hexdigest()
    evidence = _json_evidence(result_file, record, "submitted_patch_identity")
    if (
        set(evidence) != {*set(identity_body), "identity_evidence_sha256"}
        or evidence.get("identity_evidence_sha256") != identity_sha256
        or _canonical({
            key: value for key, value in evidence.items()
            if key != "identity_evidence_sha256"
        }) != _canonical(identity_body)
        or record.get("submitted_patch_identity_sha256") != identity_sha256
    ):
        raise MatrixError(
            f"{result_file.name}: direct submitted-patch identity evidence differs"
        )
    return {
        "submitted_patch_identity_sha256": identity_sha256,
        "submitted_patch_identity": True,
    }


def _validate_smoke_evidence(
    result_file: Path,
    record: dict[str, Any],
    target: dict[str, Any],
    source_row: dict[str, Any],
    expected_harness_revision: str,
) -> dict[str, Any]:
    probe = target["probe"]
    if (
        record.get("arm") != probe
        or record.get("probe") != probe
        or type(record.get("order_index")) is not int
        or record.get("order_index") != target["order_index"]
        or record.get("benchmark_id") != target["benchmark_id"]
    ):
        raise MatrixError(f"{result_file.name}: smoke probe/order/benchmark binding mismatch")

    patch = _json_evidence(result_file, record, "patch")
    expected_patch_fields = {
        "schema", "mode", "probe", "patch_bytes", "patch_nonempty", "patch_sha256",
        "restricted_applied_patch", "noop_baseline_changed_paths", "source_row_sha256",
        "applied_patch_bytes_retained", "gold_or_test_bytes_public",
    }
    if set(patch) != expected_patch_fields:
        raise MatrixError(f"{result_file.name}: patch evidence field set drift")
    raw_patch = _evidence_file(result_file, record, "applied_patch")
    patch_ref = record.get("evidence", {}).get("applied_patch")
    patch_sha = hashlib.sha256(raw_patch).hexdigest()
    if (
        not raw_patch
        or not raw_patch.strip()
        or patch_sha == hashlib.sha256(b"").hexdigest()
        or patch.get("schema") != "trimem/grader-smoke-patch-evidence/1.0"
        or patch.get("mode") != "OFFICIAL_GRADER_SMOKE_PRIVATE_PATCH"
        or patch.get("probe") != probe
        or patch.get("patch_nonempty") is not True
        or patch.get("patch_bytes") != len(raw_patch)
        or patch.get("patch_sha256") != patch_sha
        or patch.get("restricted_applied_patch") != patch_ref
        or patch.get("source_row_sha256") != target["source_row_sha256"]
        or patch.get("applied_patch_bytes_retained") != "RESTRICTED_EVIDENCE_ONLY"
        or patch.get("gold_or_test_bytes_public") is not False
        or record.get("patch_bytes") != len(raw_patch)
        or record.get("patch_sha256") != patch_sha
    ):
        raise MatrixError(f"{result_file.name}: exact applied-patch evidence mismatch")
    if probe == "NOOP_BASELINE":
        if (
            raw_patch != NOOP_BASELINE_PATCH
            or patch_sha != NOOP_BASELINE_LOCK["patch_sha256"]
            or len(raw_patch) != NOOP_BASELINE_LOCK["patch_bytes"]
            or patch.get("noop_baseline_changed_paths")
            != NOOP_BASELINE_LOCK["changed_paths"]
        ):
            raise MatrixError(f"{result_file.name}: NOOP_BASELINE patch differs from frozen bytes")
    elif patch.get("noop_baseline_changed_paths") is not None:
        raise MatrixError(f"{result_file.name}: GOLD patch claims NOOP_BASELINE paths")
    if probe == "GOLD":
        field = "patch" if target["benchmark_id"] == "swebench_verified" else "fix_patch"
        source_patch = source_row.get(field)
        if (
            not isinstance(source_patch, str)
            or not source_patch.strip()
            or raw_patch != source_patch.encode("utf-8")
        ):
            raise MatrixError(f"{result_file.name}: GOLD patch differs from frozen source row")

    test_output = _evidence_file(result_file, record, "test_output")
    status_raw = _evidence_file(result_file, record, "official_test_status")
    if not test_output.strip() or not status_raw.strip():
        raise MatrixError(f"{result_file.name}: actual official test evidence is empty")
    try:
        status = _strict_loads(status_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatrixError(f"{result_file.name}: official per-instance test status is invalid JSON") from exc
    if not isinstance(status, dict):
        raise MatrixError(f"{result_file.name}: official per-instance test status is not an object")

    tests = _json_evidence(result_file, record, "tests")
    if set(tests) != {
        "schema", "official_test_status", "probe", "summary", "target_id", "test_output"
    }:
        raise MatrixError(f"{result_file.name}: tests evidence field set drift")
    summary = tests.get("summary")
    if (
        tests.get("schema") != "trimem/grader-smoke-tests-evidence/1.0"
        or tests.get("probe") != probe
        or tests.get("target_id") != target["target_id"]
        or tests.get("test_output") != {
            "bytes": len(test_output), "sha256": hashlib.sha256(test_output).hexdigest()
        }
        or tests.get("official_test_status") != {
            "bytes": len(status_raw), "sha256": hashlib.sha256(status_raw).hexdigest()
        }
        or not isinstance(summary, dict)
    ):
        raise MatrixError(f"{result_file.name}: actual tests evidence binding mismatch")
    _validate_smoke_test_status(
        result_file, target, status, summary,
        resolved=record["resolved"], source_row=source_row,
    )

    report = _json_evidence(result_file, record, "report")
    _validate_smoke_completion_report(
        result_file, target, report, resolved=record["resolved"]
    )
    trimem = report.get("_trimem")
    report_tests = trimem.get("test_evidence") if isinstance(trimem, dict) else None
    if not isinstance(report_tests, dict) or report_tests.get("summary") != summary:
        raise MatrixError(f"{result_file.name}: report/test-summary binding mismatch")
    for name, raw in (("test_output", test_output), ("official_test_status", status_raw)):
        reference = report_tests.get(name)
        if (
            not isinstance(reference, dict)
            or reference.get("bytes") != len(raw)
            or reference.get("sha256") != hashlib.sha256(raw).hexdigest()
        ):
            raise MatrixError(f"{result_file.name}: report/{name} evidence binding mismatch")
    execution_contract_validation = _validate_smoke_execution_contract(
        result_file, target, raw_patch, report, record
    )

    container = _json_evidence(result_file, record, "container")
    expected_container = {
        "schema": "trimem/grader-smoke-container-evidence/1.0",
        "container_digest": target["image"],
        "container_started": True,
        "exit_code": 0,
        "official": True,
        "status": "success",
        "target_id": target["target_id"],
    }
    if not _exact_int(container.get("exit_code"), 0) or container != expected_container:
        raise MatrixError(f"{result_file.name}: container evidence mismatch")

    evaluator = _json_evidence(result_file, record, "evaluator")
    harness_revision = evaluator.get("harness_revision")
    expected_grader = f"official-{target['benchmark_id']}@{expected_harness_revision}"
    if (
        set(evaluator) != {
            "schema", "benchmark_id", "dataset_revision", "grader_id",
            "harness_revision", "source_row_sha256", "target_id",
        }
        or evaluator.get("schema") != "trimem/grader-smoke-evaluator-evidence/1.0"
        or evaluator.get("benchmark_id") != target["benchmark_id"]
        or evaluator.get("dataset_revision") != target["dataset_revision"]
        or evaluator.get("source_row_sha256") != target["source_row_sha256"]
        or evaluator.get("target_id") != target["target_id"]
        or harness_revision != expected_harness_revision
        or evaluator.get("grader_id") != expected_grader
        or record.get("grader_id") != expected_grader
        or not isinstance(trimem, dict)
        or trimem.get("benchmark_id") != target["benchmark_id"]
        or trimem.get("dataset_revision") != target["dataset_revision"]
        or trimem.get("source_row_sha256") != target["source_row_sha256"]
        or trimem.get("harness_revision") != harness_revision
    ):
        raise MatrixError(f"{result_file.name}: evaluator/source/revision evidence mismatch")

    locked_digest = target["image"].rsplit("@", 1)[1]
    digest = _json_evidence(result_file, record, "digest")
    if digest != {
        "schema": "trimem/grader-smoke-digest-evidence/1.0",
        "container_digest": target["image"],
        "expected_image_digest": locked_digest,
        "observed_image_digest": locked_digest,
        "target_id": target["target_id"],
    }:
        raise MatrixError(f"{result_file.name}: digest evidence mismatch")

    execution_control_evidence = _validate_smoke_execution_control(
        result_file,
        target,
        expected_harness_revision,
        report,
        record,
        execution_contract_validation["execution_contract"],
    )
    submitted_patch_evidence = _validate_smoke_submitted_patch_identity(
        result_file, target, raw_patch, report, record
    )
    execution_evidence = {
        "patch_applied": True,
        "tests_executed": True,
        "digest_match": True,
        "submitted_patch_identity": submitted_patch_evidence[
            "submitted_patch_identity"
        ],
        "host_prepare_sh_access_count": execution_control_evidence[
            "host_prepare_sh_access_count"
        ],
        "source_image_build_count": execution_control_evidence[
            "source_image_build_count"
        ],
        "api_calls": execution_contract_validation["execution_contract"][
            "api_calls"
        ],
    }
    if _canonical(record.get("execution_evidence")) != _canonical(execution_evidence):
        raise MatrixError(
            f"{result_file.name}: per-cell execution evidence differs from validated proofs"
        )

    accounting = record.get("actual_accounting")
    if (
        not isinstance(accounting, dict)
        or any(type(value) is not int for value in accounting.values())
        or accounting != {
        "model_gateway_calls": 0,
        "paid_model_calls": 0,
        "api_calls": 0,
        "grader_calls": 1,
        "grader_containers": 1,
        "official_grader_runs": 1,
        }
    ):
        raise MatrixError(f"{result_file.name}: smoke call/container accounting mismatch")
    if (
        record.get("grader_container_digest") != target["image"]
        or record.get("expected_image_digest") != locked_digest
        or record.get("observed_image_digest") != locked_digest
    ):
        raise MatrixError(f"{result_file.name}: smoke record image/digest binding mismatch")
    return {
        "applied_patch_sha256": patch_sha,
        "official_test_output_sha256": hashlib.sha256(test_output).hexdigest(),
        "official_test_status_sha256": hashlib.sha256(status_raw).hexdigest(),
        "execution_contract_sha256": execution_contract_validation[
            "execution_contract_sha256"
        ],
        "execution_control_sha256": execution_control_evidence[
            "execution_control_sha256"
        ],
        "submitted_patch_identity_sha256": submitted_patch_evidence[
            "submitted_patch_identity_sha256"
        ],
        **execution_evidence,
    }


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
    if set(value) != required:
        raise MatrixError("external approval evidence field set differs")
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

    request = (
        ROOT / GRADER_SMOKE_SENTINEL_PATH
        if name == "grader-smoke"
        else ROOT / "configs/trimem_v1/benchmark_exec_request.json"
    )
    freeze = ROOT / "artifacts/trimem_v1/freeze.json"
    if not request.is_file():
        raise MatrixError("external approval request sentinel is missing")
    if value["approved_request_sha256"] != hashlib.sha256(request.read_bytes()).hexdigest():
        raise MatrixError("external approval request digest differs from the committed request")
    if value["freeze_sha256"] != hashlib.sha256(freeze.read_bytes()).hexdigest():
        raise MatrixError("external approval freeze digest differs from the committed freeze")
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0 or completed.stdout.strip() != value["git_head"]:
        raise MatrixError("external approval git_head differs from aggregate HEAD")
    restricted = results_dir / "restricted-external-approval.json"
    if not restricted.is_file():
        raise MatrixError("restricted exact external approval evidence is missing")
    restricted_raw = restricted.read_bytes()
    if (
        not restricted_raw
        or hashlib.sha256(restricted_raw).hexdigest() != value["approval_artifact_sha256"]
    ):
        raise MatrixError("restricted exact external approval evidence hash differs")
    try:
        restricted_value = _strict_loads(restricted_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatrixError("restricted exact external approval evidence is invalid JSON") from exc
    if not isinstance(restricted_value, dict):
        raise MatrixError("restricted exact external approval evidence is not an object")
    raw_approval = restricted_value.get("approval")
    raw_request = restricted_value.get("approved_request_sha256")
    if isinstance(raw_request, str) and raw_request.startswith("sha256:"):
        raw_request = raw_request.removeprefix("sha256:")
    raw_freeze = raw_approval.get("approved_freeze_sha256") if isinstance(raw_approval, dict) else None
    if isinstance(raw_freeze, str) and raw_freeze.startswith("sha256:"):
        raw_freeze = raw_freeze.removeprefix("sha256:")
    if (
        restricted_value.get("schema") != "trimem/external-exec-approval/1.0"
        or not isinstance(raw_approval, dict)
        or raw_request != value["approved_request_sha256"]
        or raw_freeze != value["freeze_sha256"]
        or raw_approval.get("approved_git_commit") != value["git_head"]
        or raw_approval.get("approved_phase") != value["phase"]
        or str(raw_approval.get("approved_workflow_run_id"))
        != str(value["approved_workflow_run_id"])
        or str(raw_approval.get("approved_workflow_run_attempt"))
        != str(value["approved_workflow_run_attempt"])
    ):
        raise MatrixError("restricted exact external approval/public subset binding differs")
    policy_request = _load(ROOT / "configs/trimem_v1/benchmark_exec_request.json")
    request_value = _load(request)
    cost = _load(ROOT / "configs/trimem_v1/cost_plan.json")
    hard_cap = cost.get("phase_hard_caps", {}).get(expected_phase)
    if not isinstance(policy_request, dict) or not isinstance(request_value, dict) or not isinstance(hard_cap, dict):
        raise MatrixError("external approval frozen policy/cap material is malformed")
    try:
        validate_external_approval_document(
            restricted_value,
            request=request_value,
            policy_request=policy_request,
            phase=expected_phase,
            hard_cap=hard_cap,
            request_sha256=value["approved_request_sha256"],
            freeze_sha256=value["freeze_sha256"],
            git_head=value["git_head"],
            workflow_run_id=str(value["approved_workflow_run_id"]),
            workflow_run_attempt=str(value["approved_workflow_run_attempt"]),
        )
    except ApprovalValidationError as exc:
        raise MatrixError(str(exc)) from None
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


def _smoke_source_rows(expected_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    wanted = {
        (row["benchmark_id"], row["instance_id"])
        for row in expected_rows
    }
    try:
        sources, _ = load_sources(ROOT / ".trimem-exec/datasets")
    except (OSError, ValueError, SelectionError) as exc:
        raise MatrixError(f"cannot reload frozen grader-smoke source rows: {exc}") from exc
    by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    for benchmark_id, rows in sources.items():
        for source in rows:
            try:
                key = (benchmark_id, source_instance_id(source))
            except SelectionError as exc:
                raise MatrixError(str(exc)) from exc
            if key not in wanted:
                continue
            if key in by_identity:
                raise MatrixError(f"duplicate frozen grader-smoke source row: {key}")
            by_identity[key] = dict(source)
    if set(by_identity) != wanted:
        raise MatrixError("frozen grader-smoke source rows are missing during aggregate")
    result: dict[str, dict[str, Any]] = {}
    for target in expected_rows:
        source = by_identity[(target["benchmark_id"], target["instance_id"])]
        if row_hash(source) != target["source_row_sha256"]:
            raise MatrixError(f"frozen source-row hash differs: {target['target_id']}")
        result[target["target_id"]] = source
    return result


def _aggregate_smoke(results_dir: Path) -> dict[str, Any]:
    expected_rows = execution_matrix("grader-smoke")
    expected = {row["target_id"]: row for row in expected_rows}
    source_rows = _smoke_source_rows(expected_rows)
    harness_revisions = _locked_harness_revisions()
    records = _result_records(results_dir)
    observed_ids = [value.get("target_id") for _, value in records]
    if any(not isinstance(target_id, str) or not target_id for target_id in observed_ids):
        raise MatrixError("grader-smoke result has an invalid target_id")
    duplicates = sorted(target for target, count in Counter(observed_ids).items() if count > 1)
    missing = sorted(set(expected) - set(observed_ids))
    unknown = sorted(str(value) for value in set(observed_ids) - set(expected))
    if duplicates or missing or unknown:
        raise MatrixError(f"result target mismatch: missing={missing}, duplicate={duplicates}, unknown={unknown}")
    outcomes_by_id: dict[str, dict[str, Any]] = {}
    for path, value in records:
        target = expected[value["target_id"]]
        if (
            value.get("execution_status") != "SUCCESS"
            or not _exact_int(value.get("grader_exit_code"), 0)
            or value.get("grader_status") != "success"
            or value.get("container_started") is not True
        ):
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
            raise MatrixError(f"{path.name}: GOLD/NOOP_BASELINE expectation failed")
        for stream in ("stdout", "stderr"):
            _evidence_file(path, value, stream)
        _restricted_evidence(path, value)
        sealed = _validate_smoke_evidence(
            path,
            value,
            target,
            source_rows[value["target_id"]],
            harness_revisions[target["benchmark_id"]],
        )
        outcomes_by_id[value["target_id"]] = {
            "benchmark_id": target["benchmark_id"],
            "order_index": target["order_index"],
            "probe": target["probe"],
            "resolved": value["resolved"],
            "target_id": value["target_id"],
            **sealed,
        }
    probe_counts = Counter(row["probe"] for row in outcomes_by_id.values())
    resolved_counts = Counter(
        (row["probe"], row["resolved"]) for row in outcomes_by_id.values()
    )
    if (
        probe_counts != Counter({"GOLD": 6, "NOOP_BASELINE": 6})
        or resolved_counts != Counter({("GOLD", True): 6, ("NOOP_BASELINE", False): 6})
    ):
        raise MatrixError("grader-smoke exact 6/6 discrimination outcome counts differ")
    outcomes = [outcomes_by_id[row["target_id"]] for row in expected_rows]
    proof_counts = {
        "patch_applied_count": sum(
            row.get("patch_applied") is True for row in outcomes
        ),
        "tests_executed_count": sum(
            row.get("tests_executed") is True for row in outcomes
        ),
        "digest_match_count": sum(row.get("digest_match") is True for row in outcomes),
        "submitted_patch_identity_count": sum(
            row.get("submitted_patch_identity") is True for row in outcomes
        ),
        "host_prepare_sh_access_count": sum(
            int(row["host_prepare_sh_access_count"]) for row in outcomes
        ),
        "source_image_build_count": sum(
            int(row["source_image_build_count"]) for row in outcomes
        ),
        "api_calls": sum(int(row["api_calls"]) for row in outcomes),
    }
    required_proof_counts = {
        "patch_applied_count": 12,
        "tests_executed_count": 12,
        "digest_match_count": 12,
        "submitted_patch_identity_count": 12,
        "host_prepare_sh_access_count": 0,
        "source_image_build_count": 0,
        "api_calls": 0,
    }
    if proof_counts != required_proof_counts:
        raise MatrixError(
            f"grader-smoke execution proof counts differ: {proof_counts}"
        )
    accounting_fields = (
        "grader_calls",
        "grader_containers",
        "model_gateway_calls",
        "official_grader_runs",
        "paid_model_calls",
        "api_calls",
    )
    actual_accounting = {
        field: sum(int(value["actual_accounting"][field]) for _, value in records)
        for field in accounting_fields
    }
    expected_accounting = {
        "grader_calls": 12,
        "grader_containers": 12,
        "model_gateway_calls": 0,
        "official_grader_runs": 12,
        "paid_model_calls": 0,
        "api_calls": 0,
    }
    if actual_accounting != expected_accounting:
        raise MatrixError(
            f"grader-smoke aggregate call/container accounting differs: {actual_accounting}"
        )
    evidence_names = (
        "patch",
        "tests",
        "container",
        "evaluator",
        "report",
        "digest",
        "execution_contract",
        "execution_control",
        "submitted_patch_identity",
        "applied_patch",
        "test_output",
        "official_test_status",
    )
    evidence_counts = {
        name: sum(
            isinstance(value.get("evidence"), dict)
            and name in value["evidence"]
            for _, value in records
        )
        for name in evidence_names
    }
    if any(count != len(records) for count in evidence_counts.values()):
        raise MatrixError(
            f"grader-smoke direct evidence coverage differs: {evidence_counts}"
        )
    return {
        "actual_accounting": actual_accounting,
        "api_calls": proof_counts["api_calls"],
        "digest_match_count": proof_counts["digest_match_count"],
        "empty_patch_ids": [],
        "evidence_counts": evidence_counts,
        "expected_target_count": len(expected),
        "host_prepare_sh_access_count": proof_counts[
            "host_prepare_sh_access_count"
        ],
        "infrastructure_failure_count": sum(
            value.get("execution_status") != "SUCCESS"
            for _, value in records
        ),
        "observed_target_count": len(records),
        "outcomes": outcomes,
        "patch_applied_count": proof_counts["patch_applied_count"],
        "probe_counts": dict(probe_counts),
        "resolved_counts": {"GOLD": 6, "NOOP_BASELINE": 0},
        "source_image_build_count": proof_counts["source_image_build_count"],
        "submitted_patch_identity_count": proof_counts[
            "submitted_patch_identity_count"
        ],
        "tests_executed_count": proof_counts["tests_executed_count"],
        "unresolved_counts": {"GOLD": 0, "NOOP_BASELINE": 6},
        "status": "PASS",
    }


def _validate_smoke_image_lifecycle(
    results_dir: Path, image_evidence_dir: Path
) -> dict[str, Any]:
    report_path = image_evidence_dir / "image-lifecycle-report.json"
    report = _load(report_path)
    expected_fields = {
        "schema", "status", "phase", "approval_artifact_sha256", "git_head",
        "expected", "actual", "failure", "events",
    }
    if not isinstance(report, dict) or set(report) != expected_fields:
        raise MatrixError("grader-smoke image lifecycle report field set differs")
    expected_counts = {
        "target_image_pulls": 6,
        "support_image_pulls": 1,
        "exact_image_removals": 7,
        "max_resident_target_images": 1,
        "max_resident_support_images": 1,
    }
    actual_counts = {
        **expected_counts,
        "resident_target_images": 0,
        "resident_support_images": 0,
    }
    if (
        report.get("schema") != "trimem/grader-smoke-image-lifecycle/1.0"
        or report.get("status") != "PASS"
        or report.get("phase") != "GRADER_SMOKE"
        or report.get("failure") is not None
        or report.get("expected") != expected_counts
        or report.get("actual") != actual_counts
    ):
        raise MatrixError("grader-smoke image lifecycle did not finish exact and clean")

    approval = _load(results_dir / "external-approval-evidence.json")
    if (
        report.get("approval_artifact_sha256")
        != approval.get("approval_artifact_sha256")
        or report.get("git_head") != approval.get("git_head")
        or report.get("phase") != approval.get("phase")
    ):
        raise MatrixError("grader-smoke image lifecycle approval/HEAD binding differs")

    targets = execution_matrix("grader-smoke")
    lock = _load(ROOT / IMAGE_LOCK)
    lock_rows = lock.get("targets")
    support_rows = lock.get("support_images")
    if not isinstance(lock_rows, list) or not isinstance(support_rows, list) or len(support_rows) != 1:
        raise MatrixError("grader-smoke image lifecycle lock coverage is malformed")
    tags = {
        row.get("instance_id"): row.get("harness_image_tag")
        for row in lock_rows if isinstance(row, dict)
    }
    support = support_rows[0]
    support_image, support_tag = support.get("image"), support.get("harness_image_tag")
    if not IMAGE.fullmatch(str(support_image)) or not isinstance(support_tag, str):
        raise MatrixError("grader-smoke support image lifecycle lock is malformed")
    expected_events: list[tuple[str, str, str, str | None]] = []
    pairs = targets[0::2]
    multi_pairs = [
        index for index, target in enumerate(pairs)
        if str(target["benchmark_id"]).startswith("multi_swe_bench")
    ]
    for pair_index, target in enumerate(pairs):
        identity = target["instance_id"]
        if pair_index == multi_pairs[0]:
            expected_events.append(
                ("PULL_SUPPORT", "multi_swe_bench_support", support_image, None)
            )
        expected_events.append(("PULL_TARGET", identity, target["image"], None))
        expected_events.append(
            ("REMOVE_TARGET", identity, target["image"], tags.get(identity))
        )
        if pair_index == multi_pairs[-1]:
            expected_events.append(
                ("REMOVE_SUPPORT", "multi_swe_bench_support", support_image, support_tag)
            )
    events = report.get("events")
    if not isinstance(events, list) or len(events) != len(expected_events):
        raise MatrixError("grader-smoke image lifecycle event count differs")
    for index, (event, expected) in enumerate(zip(events, expected_events)):
        action, identity, image, tag = expected
        if (
            not isinstance(event, dict)
            or set(event) != {"action", "identity", "record"}
            or event.get("action") != action
            or event.get("identity") != identity
        ):
            raise MatrixError(f"grader-smoke image lifecycle event {index} differs")
        record = event.get("record")
        if not isinstance(record, dict) or record.get("image") != image:
            raise MatrixError(f"grader-smoke image lifecycle image {index} differs")
        if action.startswith("PULL_"):
            digest = image.rsplit("@", 1)[1]
            observed = record.get("observed_digests")
            if (
                record.get("expected_digest") != digest
                or not isinstance(observed, list)
                or any(not isinstance(value, str) for value in observed)
                or observed != sorted(set(observed))
                or digest not in observed
                or any(not OCI_DIGEST.fullmatch(str(value)) for value in observed)
            ):
                raise MatrixError(f"grader-smoke pull digest evidence {index} differs")
            stage_names = ("pull", "inspect")
        else:
            if (
                not isinstance(tag, str)
                or record.get("status") != "PASS"
                or record.get("references") != [tag, image]
            ):
                raise MatrixError(f"grader-smoke exact removal evidence {index} differs")
            stage_names = ("remove",)
        for stage_name in stage_names:
            stage = record.get(stage_name)
            if not isinstance(stage, dict) or set(stage) != {"stdout", "stderr"}:
                raise MatrixError(f"grader-smoke image stage evidence {index} differs")
            for stream in ("stdout", "stderr"):
                _evidence_reference(
                    report_path,
                    stage[stream],
                    f"image_lifecycle[{index}].{stage_name}.{stream}",
                )
    raw = report_path.read_bytes()
    return {
        "actual": actual_counts,
        "event_count": len(events),
        "report_bytes": len(raw),
        "report_sha256": hashlib.sha256(raw).hexdigest(),
        "status": "PASS",
    }


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


def aggregate(
    name: str,
    results_dir: Path,
    image_evidence_dir: Path | None = None,
) -> dict[str, Any]:
    if name == "grader-smoke":
        if image_evidence_dir is None:
            raise MatrixError("grader-smoke aggregate requires image lifecycle evidence")
        report = _aggregate_smoke(results_dir)
        report["image_lifecycle"] = _validate_smoke_image_lifecycle(
            results_dir, image_evidence_dir
        )
    else:
        if image_evidence_dir is not None:
            raise MatrixError("benchmark aggregate rejects grader-smoke image evidence")
        report = _aggregate_benchmark(name, results_dir)
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
    aggregate_parser.add_argument("--image-evidence-dir", type=Path)
    aggregate_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "emit":
            print(json.dumps({"include": execution_matrix(args.manifest)}, ensure_ascii=False,
                             separators=(",", ":"), sort_keys=True))
        else:
            report = aggregate(
                args.manifest,
                args.results_dir.resolve(),
                args.image_evidence_dir.resolve()
                if args.image_evidence_dir is not None else None,
            )
            _write_json(args.output.resolve(), report)
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    except (MatrixError, OSError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
