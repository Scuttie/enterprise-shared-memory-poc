"""Public, byte-pinned SWE datasets for the PDF architecture comparison.

The public loader reads an explicit parquet column allowlist. Only the isolated
grader handoff decodes one private source row, solely for the existing official
grader API; private rows are never returned in public tasks or manifests.
Training task IDs retain the original SWE-bench namespace. ``benchmark_id`` is
the existing SWE adapter key, not a claim that training belongs to Verified.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Mapping

import trimem_skhynix_architecture_plan as plan


SCHEMA = "skhynix/pdf-architecture-dataset/1.0"
PROPOSAL_SCHEMA = "skhynix/pdf-architecture-training-proposal/1.0"
PUBLIC_COLUMNS = ("instance_id", "repo", "base_commit", "created_at", "problem_statement")
PUBLIC_ENVIRONMENT_COLUMNS = ("version", "environment_setup_commit")
ROLES = ("TRAINING", "EVALUATION")
TRAINING_SOURCE = {
    "dataset_id": "SWE-bench/SWE-bench",
    "revision": "c6fe717fd7a4c3ac1daa4055a4fd082c6a1d28a2",
    "split": "test", "bytes": 33293897,
    "sha256": "d4f5a245c75319fa8240c540674958c4d491e82edf274b144d43836bdcbc4567",
}


class ArchitectureDatasetError(ValueError):
    """A public dataset or private grader binding differs from its contract."""


def _fail(message):
    raise ArchitectureDatasetError(message)


def _source_path(dataset):
    path = plan._path(dataset["path"])
    if path.stat().st_size != dataset["bytes"] or plan.file_sha(path) != dataset["sha256"]:
        _fail("Dataset bytes differ from their pinned source")
    return path


def _inventories(evaluation_inventory, training_inventory):
    evaluation_ref, evaluation = plan.load_public_inventory(evaluation_inventory, evaluation=True)
    training_ref, training = plan.load_public_inventory(training_inventory)
    if any(training["dataset"][key] != value for key, value in TRAINING_SOURCE.items()):
        _fail("Training dataset differs from the pinned original SWE-bench source")
    evaluation_ids = {row["instance_id"] for row in evaluation["tasks"]}
    evaluation_hashes = {row["instruction_sha256"] for row in evaluation["tasks"]}
    repositories = {row["repository"] for row in evaluation["tasks"]}
    for row in training["tasks"]:
        if row["instance_id"] in evaluation_ids or row["instruction_sha256"] in evaluation_hashes:
            _fail("Training candidates overlap the evaluation identities or public instructions")
        if row["repository"] not in repositories:
            _fail("Training repository is outside the evaluation inventory")
    return evaluation_ref, evaluation, training_ref, training


def propose_training_enrollment(evaluation_inventory, training_inventory, *, per_repository=2):
    """Return a deterministic public-metadata proposal; write no files.

    PR creation time orders candidates; this is not a git ancestry assertion.
    No issue text, gold content, image availability or outcome drives selection.
    """
    if type(per_repository) is not int or not 1 <= per_repository <= 100:
        _fail("Training count per repository must be an integer from 1 to 100")
    evaluation_ref, evaluation, training_ref, training = _inventories(
        evaluation_inventory, training_inventory)
    selected = []
    for repository in sorted({row["repository"] for row in evaluation["tasks"]}):
        candidates = sorted((row for row in training["tasks"] if row["repository"] == repository),
            key=lambda row: (datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
                             row["instance_id"]))
        if len(candidates) < per_repository:
            _fail("A repository has insufficient disjoint training candidates")
        selected.extend(dict(row) for row in candidates[:per_repository])
    return {"schema": PROPOSAL_SCHEMA, "status": "PROPOSED_NOT_ENROLLED",
        "evaluation_inventory": evaluation_ref, "training_inventory": training_ref,
        "selection": "PER_REPOSITORY_ASCENDING_CREATED_AT_THEN_INSTANCE_ID",
        "selection_fields": ["repository", "created_at", "instance_id"],
        "per_repository": per_repository, "tasks": selected,
        "instance_ids": [row["instance_id"] for row in selected],
        "git_ancestry_verified": False, "runtime_compatibility_verified": False,
        "model_calls": 0, "official_grader_runs": 0, "training_runs": 0}


def _descriptor(row):
    statement = row.get("problem_statement")
    if not isinstance(statement, str) or not statement.strip():
        _fail("Public task instruction is missing")
    return {"instance_id": row.get("instance_id"), "repository": row.get("repo"),
        "base_commit": row.get("base_commit"), "created_at": row.get("created_at"),
        "instruction_sha256": plan.sha(statement.strip().encode("utf-8"))}


def _public_rows(inventory, selected, *, evaluation):
    import pyarrow.parquet as pq

    dataset = inventory["dataset"]
    path = _source_path(dataset)
    names = set(pq.read_schema(path).names)
    if not set(PUBLIC_COLUMNS) <= names:
        _fail("Dataset is missing required public columns")
    columns = [*PUBLIC_COLUMNS, *(name for name in PUBLIC_ENVIRONMENT_COLUMNS if name in names)]
    # Every read explicitly excludes patches, hints and evaluator test lists.
    source = pq.read_table(path, columns=columns).to_pylist()
    rows = {}
    all_ids = set()
    for row in source:
        if set(row) != set(columns):
            _fail("Public reader returned missing or forbidden columns")
        identity = row.get("instance_id")
        if not isinstance(identity, str) or identity in all_ids:
            _fail("Dataset has invalid or duplicate source identities")
        all_ids.add(identity)
        if identity not in selected:
            continue
        if _descriptor(row) != selected[identity]:
            _fail("Public source row differs from its inventory descriptor")
        for field in PUBLIC_ENVIRONMENT_COLUMNS:
            if field in row and row[field] is not None and not isinstance(row[field], str):
                _fail("Public environment metadata has an invalid type")
        rows[identity] = dict(row)
    if set(rows) != set(selected):
        _fail("Selected public rows are missing")
    if evaluation and all_ids != set(selected):
        _fail("Evaluation source is not exactly the entire Verified inventory")
    _source_path(dataset)
    return rows


def _assemble(evaluation_inventory, training_inventory, training_instance_ids):
    evaluation_ref, evaluation, training_ref, training = _inventories(
        evaluation_inventory, training_inventory)
    if (not isinstance(training_instance_ids, (list, tuple)) or not training_instance_ids
            or any(not isinstance(identity, str) for identity in training_instance_ids)
            or len(set(training_instance_ids)) != len(training_instance_ids)):
        _fail("Training enrollment requires explicit unique source instance IDs")
    candidates = {row["instance_id"]: row for row in training["tasks"]}
    if not set(training_instance_ids) <= set(candidates):
        _fail("Training enrollment contains a source outside the disjoint candidate inventory")
    training_ids = sorted(training_instance_ids)
    targets, public_rows = [], {}
    for role, inventory, descriptors in (
        ("TRAINING", training, {identity: candidates[identity] for identity in training_ids}),
        ("EVALUATION", evaluation, {row["instance_id"]: row for row in evaluation["tasks"]}),
    ):
        rows = _public_rows(inventory, descriptors, evaluation=role == "EVALUATION")
        public_rows.update(rows)
        prefix = "swebench_verified--" if role == "EVALUATION" else "swebench--"
        for identity in sorted(descriptors):
            descriptor = descriptors[identity]
            targets.append({"target_id": prefix + identity, "instance_id": identity,
                "benchmark_id": "swebench_verified", "role": role, "language": "python",
                "repository": descriptor["repository"], "base_commit": descriptor["base_commit"],
                "public_issue_created_at": descriptor["created_at"],
                "instruction_sha256": descriptor["instruction_sha256"],
                "public_source_row_sha256": plan.sha(plan.canonical(rows[identity])),
                "source_dataset_id": inventory["dataset"]["dataset_id"],
                "dataset_revision": inventory["dataset"]["revision"],
                "source_split": inventory["dataset"]["split"], "order_index": len(targets)})
    manifest = {"schema": SCHEMA, "status": "FROZEN_PUBLIC_DATASET",
        "evaluation_inventory": evaluation_ref, "training_inventory": training_ref,
        "datasets": {"TRAINING": training["dataset"], "EVALUATION": evaluation["dataset"]},
        "training_instance_ids": training_ids, "targets": targets,
        "evaluation_count": len(evaluation["tasks"]), "training_count": len(training_ids),
        "evaluation_selection": "EXACT_ENTIRE_PINNED_PUBLIC_VERIFIED_500_INVENTORY",
        "training_selection": "EXPLICIT_SUBSET_OF_DISJOINT_PINNED_CANDIDATES",
        "public_columns": list(PUBLIC_COLUMNS),
        "optional_public_environment_columns": list(PUBLIC_ENVIRONMENT_COLUMNS),
        "source_instance_ids_disjoint": True, "public_instruction_hashes_disjoint": True,
        "model_calls": 0, "official_grader_runs": 0, "training_runs": 0}
    return manifest, public_rows


def build_architecture_manifest(evaluation_inventory, training_inventory, *, training_instance_ids, output):
    """Freeze explicit enrollment after validating only public columns.

    Existing bytes are retained exactly; conflicting output is never overwritten.
    This dataset freeze does not claim execution, trained memory, or readiness.
    """
    manifest, _ = _assemble(evaluation_inventory, training_inventory, training_instance_ids)
    path = plan._path(output, exists=False)
    raw = plan.canonical(manifest) + b"\n"
    if path.exists():
        if path.read_bytes() != raw:
            _fail("Existing architecture dataset manifest differs")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    return {"path": str(path), "sha256": plan.sha(raw), "status": manifest["status"],
        "evaluation_count": manifest["evaluation_count"], "training_count": manifest["training_count"]}


def load_architecture_rows(manifest_path, *, expected_sha256, role=None):
    """Return public targets, solver-safe rows and the validated frozen manifest."""
    if role is not None and role not in ROLES:
        _fail("Unknown architecture dataset role")
    reference = {"path": str(manifest_path), "sha256": expected_sha256}
    _, value = plan._read_reference(reference)
    if isinstance(value, dict) and value.get("schema") == "skhynix/pdf-architecture-scale-dataset/1.0":
        from trimem_skhynix_architecture_scale_dataset import load_scale_rows
        return load_scale_rows(manifest_path, expected_sha256=expected_sha256, role=role)
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        _fail("Unsupported architecture dataset manifest")
    try:
        expected, rows = _assemble(value["evaluation_inventory"], value["training_inventory"],
                                  value["training_instance_ids"])
    except KeyError as exc:
        raise ArchitectureDatasetError("Architecture manifest is missing required fields") from exc
    if plan.canonical(value) != plan.canonical(expected):
        _fail("Architecture manifest differs from its exact public source projection")
    plan._reference(reference)
    targets = [dict(target) for target in value["targets"] if role is None or target["role"] == role]
    return targets, {target["instance_id"]: rows[target["instance_id"]] for target in targets}, value


def official_image_tag(instance_id):
    """Canonical official SWE harness image tag for any repository instance."""
    if not isinstance(instance_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-[0-9]+", instance_id):
        _fail("Invalid SWE image instance identity")
    return "swebench/sweb.eval.x86_64." + instance_id.lower().replace("__", "_1776_") + ":latest"


def validate_image_bindings(targets, images):
    """Require a manager-resolved exact official digest for every requested task."""
    if not isinstance(images, Mapping):
        _fail("Image bindings must be an instance mapping")
    result = {}
    for target in targets:
        instance = target["instance_id"]
        image = images.get(instance)
        tag = official_image_tag(instance)
        if (not isinstance(image, Mapping) or image.get("instance_id") != instance
                or image.get("benchmark_id") != "swebench_verified"
                or image.get("harness_image_tag") != tag
                or not isinstance(image.get("image"), str)
                or not re.fullmatch(re.escape(tag.removesuffix(":latest")) + r"@sha256:[0-9a-f]{64}", image["image"])):
            _fail("Missing or mismatched official SWE image digest binding")
        result[instance] = dict(image)
    return result


def _private_grader_row(target, manifest):
    """Evaluator-only boundary: decode one pinned row without logging its contents."""
    import pyarrow.parquet as pq

    dataset = manifest["datasets"][target["role"]]
    if (target["source_dataset_id"] != dataset["dataset_id"]
            or target["dataset_revision"] != dataset["revision"]
            or target["source_split"] != dataset["split"]):
        _fail("Private grader dataset metadata differs from the public target")
    path = _source_path(dataset)
    source = pq.read_table(path, filters=[("instance_id", "==", target["instance_id"])]).to_pylist()
    _source_path(dataset)
    if len(source) != 1:
        _fail("Private grader source identity is missing or duplicated")
    row = source[0]
    public = {key: row[key] for key in (*PUBLIC_COLUMNS, *PUBLIC_ENVIRONMENT_COLUMNS) if key in row}
    if plan.sha(plan.canonical(public)) != target["public_source_row_sha256"]:
        _fail("Private grader source differs from the bound public task")
    descriptor = _descriptor(public)
    if any(descriptor[field] != target[target_field] for field, target_field in (
            ("instance_id", "instance_id"), ("repository", "repository"),
            ("base_commit", "base_commit"), ("created_at", "public_issue_created_at"),
            ("instruction_sha256", "instruction_sha256"))):
        _fail("Private grader public identity differs from its target metadata")
    return row


def bind_architecture_grader(target, manifest, image, harnesses, output_root, arm, *,
                             loader_preflight_evidence=None):
    """Return the public target hash and official gateway, never the private row.

    Call with a manifest returned by ``load_architecture_rows``. The gateway is
    manager-private, just as in the existing environment; never serialize it or
    give solver code access to its source_row attribute.
    """
    import trimem_benchmark_run as benchmark
    from trimem_official_grader import canonical_row_hash

    public_target = {key: value for key, value in target.items() if key != "source_row_sha256"}
    if manifest.get("schema") == "skhynix/pdf-architecture-scale-dataset/1.0":
        from trimem_skhynix_architecture_scale_dataset import public_grader_manifest
        manifest = public_grader_manifest(public_target, manifest)
    if (manifest.get("schema") != SCHEMA
            or public_target not in manifest.get("targets", ())):
        _fail("Grader target is outside the loaded architecture manifest")
    validated = validate_image_bindings([public_target], {target["instance_id"]: image})
    row = _private_grader_row(public_target, manifest)
    source_hash = canonical_row_hash(row)
    if "source_row_sha256" in target and target["source_row_sha256"] != source_hash:
        _fail("Previously bound private grader source hash changed")
    bound_target = {**public_target, "source_row_sha256": source_hash}
    grader = benchmark.grader_factory(bound_target, row, validated[target["instance_id"]],
        harnesses, Path(output_root), arm, (), loader_preflight_evidence=loader_preflight_evidence)
    return bound_target, grader
