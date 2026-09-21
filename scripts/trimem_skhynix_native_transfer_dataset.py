"""Fixed native009 transfer enrollment; existing native manifests stay immutable.

The four targets are the remaining eligible native005 public candidates after
native002-007 enrollments and the explicitly known development target 21596.
Source rows are decoded only for opaque hashes and the existing grader handoff.
This module does not run containers, solvers, graders, or network requests.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any

import trimem_skhynix_native_dataset as dataset

SCHEMA = "skhynix/native-disjoint-transfer-manifest/1.0"
TARGET_IDS = tuple(f"sympy__sympy-{n}" for n in (21612, 21847, 22714, 24661))
SOURCE_IDS = tuple(f"sympy__sympy-{n}" for n in (20428, 20438))
KNOWN_DEVELOPMENT_IDS = ("sympy__sympy-21596",)
PRIOR_PATHS = dataset.EXCLUSION_PATHS + tuple(
    f"configs/skhynix_v1/codex_{n:03}_manifest.json" for n in range(2, 8))
NATIVE005_PATH = "configs/skhynix_v1/codex_005_manifest.json"
NATIVE007_PATH = "configs/skhynix_v1/codex_007_manifest.json"
SCOPE = (
    "FOUR_FIXED_PUBLIC_METADATA_INFORMED_TRANSFER_TARGETS_UNUSED_IN_NATIVE002_THROUGH007_ENROLLMENTS_"
    "IN_AN_INSPECTED_REPOSITORY_NOT_GLOBALLY_UNSEEN_NOT_RANDOM_NOT_DIFFICULTY_PROVEN_"
    "NOT_ORIGINAL_HELDOUT_ENDPOINT"
)
SELECTION = {
    "profile": "NATIVE009_DISJOINT_TRANSFER_FROM_KNOWN_NATIVE007_FAILURES",
    "repository": dataset.REPOSITORY,
    "order": "ASCENDING_NUMERIC_INSTANCE_ID",
    "new_training_count": 0,
    "evaluation_count": 4,
    "evaluation_instance_ids": list(TARGET_IDS),
    "memory_source_instance_ids": list(SOURCE_IDS),
    "known_development_exclusions": list(KNOWN_DEVELOPMENT_IDS),
    "candidate_pool": "FROZEN_NATIVE005_PUBLIC_RUNTIME_COMPATIBLE_CANDIDATES",
    "method": "FIXED_REMAINING_ELIGIBLE_IDS_AFTER_PRIOR_ENROLLMENT_AND_KNOWN_DEVELOPMENT_EXCLUSION",
    "public_metadata_informed_planner": True,
    "selection_not_claimed": ["GLOBAL_UNSEEN", "RANDOM", "PROVEN_DIFFICULTY"],
}


def _read(path: Path) -> tuple[bytes, dict[str, Any]]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise dataset.SupplementalDatasetError("Transfer manifest or prior enrollment is unavailable")
    raw = path.read_bytes()
    value = dataset.benchmark.strict_json_loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise dataset.SupplementalDatasetError("Transfer manifest or prior enrollment is not an object")
    return raw, value


def _prior_enrollments(root: Path):
    excluded, bindings, values, raw_values = set(), [], {}, {}
    for relative in PRIOR_PATHS:
        raw, value = _read(root / relative)
        targets = value.get("targets")
        if not isinstance(targets, list) or any(
                not isinstance(row, dict) or not isinstance(row.get("instance_id"), str)
                for row in targets):
            raise dataset.SupplementalDatasetError("Prior enrollment target identities are malformed")
        excluded.update(row["instance_id"] for row in targets)
        bindings.append({"path": relative, "raw_sha256": dataset.sha(raw)})
        values[relative], raw_values[relative] = value, raw
    if set(TARGET_IDS) & (excluded | set(KNOWN_DEVELOPMENT_IDS)):
        raise dataset.SupplementalDatasetError("Transfer targets overlap a prior or development enrollment")
    # Native006 and native007 deliberately reused the immutable native005 cohort.
    if any(raw_values[f"configs/skhynix_v1/codex_{n:03}_manifest.json"] != raw_values[NATIVE005_PATH]
           for n in (6, 7)):
        raise dataset.SupplementalDatasetError("Native005-007 reused enrollment bytes differ")
    return excluded, bindings, values, raw_values


def _selected_rows(path: Path) -> dict[str, dict[str, Any]]:
    import pyarrow.parquet as pq
    identities = pq.read_table(path, columns=["instance_id", "repo"]).to_pylist()
    for instance in TARGET_IDS:
        matches = [row for row in identities if row["instance_id"] == instance]
        if len(matches) != 1 or matches[0]["repo"] != dataset.REPOSITORY:
            raise dataset.SupplementalDatasetError("Fixed transfer public identity is absent or duplicated")
    rows = pq.read_table(path, filters=[("instance_id", "in", list(TARGET_IDS))]).to_pylist()
    if len(rows) != len(TARGET_IDS) or {row["instance_id"] for row in rows} != set(TARGET_IDS):
        raise dataset.SupplementalDatasetError("Fixed transfer source rows differ")
    return {row["instance_id"]: dict(row) for row in rows}


def _instruction_sha(row: dict[str, Any]) -> str:
    instruction = dataset.benchmark.public_instruction(row, dataset.BENCHMARK)
    return dataset.sha(instruction.encode("utf-8"))


def _ancestry(history: Path, sources: list[dict[str, Any]], targets: list[dict[str, Any]]):
    if not history.is_dir() or history.is_symlink():
        raise dataset.SupplementalDatasetError("Public history checkout is unavailable")
    origin = dataset._git(history, ["remote", "get-url", "origin"])
    if origin.returncode or origin.stdout.strip() != "https://github.com/sympy/sympy.git":
        raise dataset.SupplementalDatasetError("Public history origin differs")
    timestamps = {}
    for row in [*sources, *targets]:
        commit = row["base_commit"]
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise dataset.SupplementalDatasetError("Malformed transfer chronology commit")
        observed = dataset._git(history, ["cat-file", "commit", commit])
        match = re.search(r"^committer .+ ([0-9]+) [+-][0-9]{4}$",
                          observed.stdout.split("\n\n", 1)[0], re.MULTILINE)
        if observed.returncode or match is None:
            raise dataset.SupplementalDatasetError("Public transfer commit timestamp is unavailable")
        timestamps[commit] = int(match.group(1))
    evidence = []
    for source in sources:
        for target in targets:
            base, head = source["base_commit"], target["base_commit"]
            observed = dataset._git(history, ["merge-base", "--is-ancestor", base, head])
            if observed.returncode != 0 or timestamps[base] >= timestamps[head]:
                raise dataset.SupplementalDatasetError("Memory source base does not precede transfer target")
            evidence.append({"source_instance_id": source["instance_id"], "source_base_commit": base,
                "target_instance_id": target["instance_id"], "target_base_commit": head,
                "source_commit_unix_seconds": timestamps[base], "target_commit_unix_seconds": timestamps[head],
                "method": "git merge-base --is-ancestor", "returncode": observed.returncode})
    return evidence


def _assemble(*, cache_root: Path, history: Path, root: Path):
    excluded, bindings, prior_values, prior_raw = _prior_enrollments(root)
    previous = prior_values[NATIVE005_PATH]
    if previous.get("schema") != dataset.SCHEMA or previous.get("selection") != dataset.NATIVE005_SELECTION:
        raise dataset.SupplementalDatasetError("Native005 runtime source profile differs")
    # This existing validator rechecks every public candidate/runner, the locked
    # dataset, image registry receipts, public Python probes, and original split.
    prior_targets, prior_rows, _, previous = dataset.load_supplemental_rows(
        root / NATIVE005_PATH, cache_root, expected_sha256=dataset.sha(prior_raw[NATIVE005_PATH]), root=root)
    screening = previous["selection_evidence"]["runtime_screening"]
    eligible = {row["instance_id"]: row for row in screening["images"] if row["eligible"] is True}
    remainder = [row["instance_id"] for row in previous["selection_evidence"]["candidates"]
                 if row["instance_id"] in eligible and row["instance_id"] not in excluded
                 and row["instance_id"] not in KNOWN_DEVELOPMENT_IDS]
    if remainder != list(TARGET_IDS):
        raise dataset.SupplementalDatasetError("Eligible public transfer remainder differs from the fixed four")
    path, spec = dataset._locked_dataset(cache_root, root)
    rows = _selected_rows(path)
    targets = [{"target_id": dataset.BENCHMARK + "--" + instance, "instance_id": instance,
        "benchmark_id": dataset.BENCHMARK, "repository": dataset.REPOSITORY, "language": "python",
        "base_commit": rows[instance]["base_commit"], "dataset_revision": spec["dataset_revision"],
        "source_row_sha256": dataset.sha(dataset.canonical(rows[instance])), "order_index": index,
        "role": "EVALUATION", "public_issue_created_at": rows[instance]["created_at"],
        "public_instruction_sha256": _instruction_sha(rows[instance])}
        for index, instance in enumerate(TARGET_IDS)]
    source_map = {row["instance_id"]: row for row in prior_targets}
    sources = []
    for instance in SOURCE_IDS:
        source = source_map.get(instance)
        if source is None or source["role"] != "EVALUATION":
            raise dataset.SupplementalDatasetError("Native007 evaluation memory source is missing")
        sources.append({**source, "origin_manifest": NATIVE007_PATH,
                        "public_instruction_sha256": _instruction_sha(prior_rows[instance])})
    images = []
    for instance in TARGET_IDS:
        runtime = eligible[instance]
        registry = dataset._public_evidence_file(runtime["registry_evidence_path"],
                                                  runtime["registry_response_sha256"])
        name = "swebench/sweb.eval.x86_64." + instance.replace("__", "_1776_")
        images.append({"instance_id": instance, "benchmark_id": dataset.BENCHMARK,
            "image": runtime["image"], "harness_image_tag": name + ":latest",
            "registry_evidence_url": f"https://hub.docker.com/v2/repositories/{name}/tags/latest",
            "registry_response_sha256": runtime["registry_response_sha256"],
            "registry_response_canonical_sha256": runtime["registry_response_canonical_sha256"],
            "registry_last_updated_utc": registry["last_updated"], "registry_response": registry})
    image_map = dataset._validate_images(images, list(TARGET_IDS))
    dataset._validate_selected_runtime_images(images, screening)
    value = {"schema": SCHEMA, "status": "FROZEN", "selection": deepcopy(SELECTION),
        "dataset": spec, "excluded_manifests": bindings, "targets": targets, "images": images,
        "memory_source_targets": sources, "history_path": str(history.resolve()),
        "ancestry": _ancestry(history, sources, targets),
        "chronology_claim": "MEMORY_SOURCE_BASE_ANCESTRY_ONLY_NOT_NATIVE_PATCH_UPSTREAM_MERGE",
        "scope_claim": SCOPE, "model_calls_at_selection": None, "planner_llm_involved_at_selection": True,
        "solver_model_calls_at_selection": 0, "new_target_grader_runs_at_selection": 0,
        "restricted_source_use": "OPAQUE_ROW_HASH_AND_EXISTING_GRADER_HANDOFF_ONLY",
        "runtime_evidence": {"origin_manifest": NATIVE005_PATH,
            "runtime_screening_raw_sha256": previous["selection_evidence"]["runtime_screening_raw_sha256"],
            "candidate_pool_canonical_sha256": previous["selection_evidence"]["candidates_canonical_sha256"],
            "runner_evidence_canonical_sha256": previous["selection_evidence"]["runner_evidence_canonical_sha256"],
            "required_runner_sha256": dataset.NATIVE005_RUNNER_SHA256,
            "required_public_python_version": "Python 3.9.20",
            "eligible_remaining_instance_ids": remainder,
            "selected_public_runtime_receipts": [eligible[instance] for instance in TARGET_IDS]}}
    return targets, rows, image_map, value


def build_transfer_manifest(*, cache_root: Path, history: Path, output_path: Path,
                            root: Path = dataset.ROOT) -> dict[str, Any]:
    """Freeze the fixed four only when called; importing never enrolls a task."""
    if output_path.exists() or output_path.is_symlink():
        raise dataset.SupplementalDatasetError("Transfer manifest already exists; never overwrite")
    value = _assemble(cache_root=cache_root, history=history, root=root)[3]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("xb") as stream:
        stream.write(dataset.canonical(value) + b"\n")
    return value


def load_transfer_rows(manifest_path: Path, cache_root: Path, *, expected_sha256: str,
                       root: Path = dataset.ROOT):
    raw, value = _read(manifest_path)
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise dataset.SupplementalDatasetError("Transfer manifest raw hash binding is invalid")
    if dataset.sha(raw) != expected_sha256:
        raise dataset.SupplementalDatasetError("Transfer manifest raw hash differs")
    if (value.get("schema") != SCHEMA or value.get("status") != "FROZEN"
            or not isinstance(value.get("history_path"), str)
            or dataset.canonical(value.get("selection")) != dataset.canonical(SELECTION)):
        raise dataset.SupplementalDatasetError("Transfer selection contract differs")
    targets, rows, images, expected = _assemble(cache_root=cache_root, history=Path(value["history_path"]), root=root)
    if dataset.canonical(value) != dataset.canonical(expected):
        raise dataset.SupplementalDatasetError("Transfer scientific inputs or evidence differ")
    return targets, rows, images, value
