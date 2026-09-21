"""Additive Linux execution environment for the generic architecture dataset.

Building validates public bindings only. Each requested cell independently
materializes the pinned image and base-only checkout, probes the public Python
runtime, and lazily constructs its existing official grader. No model or grade
is invoked here. Existing DEV/native preparation modules remain unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import sys

import trimem_skhynix_architecture_dataset as dataset
import trimem_skhynix_architecture_plan as plan
import trimem_skhynix_environment as local


ARMS = ("BASELINE", "PDF_MEMORY")
SCHEMA = "skhynix/pdf-architecture-environment/1.0"


def load_image_index(path, *, expected_sha256=None):
    path = plan._path(path)
    reference = {"path": str(path), "sha256": expected_sha256 or plan.file_sha(path)}
    _, value = plan._read_reference(reference)
    if isinstance(value, dict):
        entries = value.get("images", value.get("rows", value))
    else:
        entries = value
    if isinstance(entries, dict):
        images = {}
        for instance, entry in entries.items():
            if not isinstance(entry, dict) or entry.get("instance_id", instance) != instance:
                raise local.LocalEnvironmentError("Image index identity mapping is malformed")
            images[instance] = {"benchmark_id": "swebench_verified", **entry, "instance_id": instance}
    elif isinstance(entries, list):
        images = {}
        for entry in entries:
            if (not isinstance(entry, dict) or not isinstance(entry.get("instance_id"), str)
                    or entry["instance_id"] in images):
                raise local.LocalEnvironmentError("Image index has malformed or duplicate identities")
            images[entry["instance_id"]] = {"benchmark_id": "swebench_verified", **entry}
    else:
        raise local.LocalEnvironmentError("Image index must contain an instance map or rows")
    return images, reference


def _probe_public_python(cell):
    """Read actual executable metadata through the already masked sandbox."""
    runner = cell.workspace_factory.command_runners[cell.task.task_id]
    checkout = cell.workspace_factory.checkout_roots[cell.task.task_id]
    # Discover testbed interpreters from the image filesystem. The fallback is
    # the image PATH, not the host Python nor an unverified assumed installation.
    script = (
        "set -eu; candidate=''; "
        "for path in /opt/*/envs/testbed/bin/python; do "
        "if test -x \"$path\"; then "
        "test -z \"$candidate\" || exit 43; candidate=\"$path\"; fi; done; "
        "if test -z \"$candidate\"; then "
        "candidate=$(command -v python3 || command -v python); fi; "
        "exec \"$candidate\" -c 'import json, os, platform, sys; "
        "print(json.dumps({\"python_executable\": sys.executable, "
        "\"python_realpath\": os.path.realpath(sys.executable), "
        "\"python_version\": platform.python_version(), "
        "\"implementation\": platform.python_implementation()}, sort_keys=True))'"
    )
    result = runner.run(checkout, ("/bin/sh", "-ceu", script), cwd=None, timeout_seconds=60)
    if result.exit_code or result.timed_out or result.output_truncated:
        raise local.LocalEnvironmentError("Public image Python runtime probe failed")
    try:
        metadata = local.benchmark.strict_json_loads(result.stdout)
        if not isinstance(metadata, dict) or set(metadata) != {
                "python_executable", "python_realpath", "python_version", "implementation"}:
            raise ValueError("schema")
        for name in ("python_executable", "python_realpath"):
            if (not isinstance(metadata[name], str)
                    or not re.fullmatch(r"/(?:[A-Za-z0-9_.+-]+/)*[A-Za-z0-9_.+-]+", metadata[name])
                    or any(part in {".", ".."} for part in metadata[name].split("/"))):
                raise ValueError("executable")
        if (not isinstance(metadata["python_version"], str)
                or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[A-Za-z0-9.+-]*)", metadata["python_version"])
                or metadata["implementation"] not in {"CPython", "PyPy"}):
            raise ValueError("version")
    except (TypeError, ValueError) as exc:
        raise local.LocalEnvironmentError("Public image Python runtime metadata is invalid") from exc
    return {"schema": "skhynix/public-image-python/1.0", "status": "PASS",
        "image": runner.image, "command_sandbox_content_hash": runner.content_hash,
        "discovery": "IMAGE_TESTBED_EXECUTABLE_METADATA_THEN_IMAGE_PATH", **metadata,
        "probe_containers": 1, "model_calls": 0, "official_grader_runs": 0}


@dataclass
class PreparedArchitectureEnvironment(local.PreparedLocalEnvironment):
    _architecture_manifest: dict = field(default_factory=dict, repr=False)
    _runtime_by_cell: dict = field(default_factory=dict, repr=False)

    def prepare_cell(self, arm, task, *, resume=False):
        if arm not in self.arms or task not in self.tasks:
            raise local.LocalEnvironmentError("Cell is outside the declared architecture comparison")
        identity = (arm, task.task_id)
        if identity in self._prepared_cells:
            raise local.LocalEnvironmentError("Cell was already prepared in this process")
        self.prepare_target(task)
        arm_name, target_name = local._safe_name(arm), local._safe_name(task.task_id)
        checkouts = self.workspace_root / arm_name / target_name / "checkouts"
        cell_output = self.output_root / "cells" / arm_name / target_name
        if checkouts.exists() and any(checkouts.iterdir()) and not resume:
            raise local.LocalEnvironmentError("Fresh cell checkout already exists; use a new experiment root")
        target = self.targets_by_id[task.task_id]
        factory, evidence = local.benchmark.prepare_checkouts(
            [task], [target], self._images, checkouts, resume=resume)
        attestation = evidence[task.task_id]
        if not resume and attestation.get("initial_status") != "":
            raise local.LocalEnvironmentError("Fresh cell checkout is not pristine")
        if not local.benchmark._valid_history_isolation_evidence(
                attestation.get("history_isolation"), expected_commit=task.commit):
            raise local.LocalEnvironmentError("Cell checkout history is not base-only")
        if type(factory) is not local.GitCheckoutWorkspaceFactory or not factory.production_capable:
            raise local.LocalEnvironmentError("Cell workspace lacks the frozen Docker command runner")
        public_cell = local.PreparedLocalCell(arm, task, target, factory, attestation, None, cell_output)
        sandbox = local._probe_solver(public_cell)
        runtime = _probe_public_python(public_cell)
        bound, grader = dataset.bind_architecture_grader(target, self._architecture_manifest,
            self._images[target["instance_id"]], self._harnesses, cell_output / "official-grader", arm,
            loader_preflight_evidence=self.loader_preflight)
        cell = local.PreparedLocalCell(arm, task, bound, factory, attestation, grader, cell_output)
        local._retain(cell_output / "control" / "solver-sandbox-preflight.json", sandbox)
        local._retain(cell_output / "control" / "public-python-preflight.json", runtime)
        if not resume:
            local._retain(cell_output / "control" / "checkout-preflight.json", attestation)
        self._runtime_by_cell[identity] = runtime
        self._prepared_cells.add(identity)
        return cell

    def public_workspace_configuration(self, cell):
        identity = (cell.arm, cell.task.task_id)
        if (identity not in self._prepared_cells or cell.task not in self.tasks
                or cell.arm not in self.arms):
            raise local.LocalEnvironmentError("Public workspace configuration requires a prepared cell")
        runner = cell.workspace_factory.command_runners[cell.task.task_id]
        runtime = self._runtime_by_cell[identity]
        if runtime["command_sandbox_content_hash"] != runner.content_hash:
            raise local.LocalEnvironmentError("Public runtime and cell command sandbox differ")
        row = self._rows[cell.target["instance_id"]]
        return {"task_id": cell.task.task_id, "arm": cell.arm,
            "repository": cell.task.repository, "base_commit": cell.task.commit,
            "checkout_root": str(cell.workspace_factory.checkout_roots[cell.task.task_id]),
            "container_workspace": runner.container_workspace, "image": runner.image,
            "python_executable": runtime["python_executable"], "python_version": runtime["python_version"],
            "source_version": row.get("version"),
            "source_environment_setup_commit": row.get("environment_setup_commit"),
            "public_test_guidance": "Use run_command with the repository's public tests and this Python executable.",
            "network": "none", "command_sandbox_content_hash": runner.content_hash}


def build_environment(*, manifest_path, sha, image_index_path, workspace_root, output_root,
                      harness_root, loader_preflight_path, arms=ARMS, role=None,
                      image_index_sha256=None, disk_reserve_bytes=10 * 1024 ** 3):
    """Validate public execution inputs without pulling images or decoding gold."""
    if sys.platform != "linux":
        raise local.LocalEnvironmentError("Official architecture execution requires the existing Linux runner")
    selected_arms = tuple(arms)
    if (not selected_arms or len(set(selected_arms)) != len(selected_arms)
            or set(selected_arms) - set(ARMS)):
        raise local.LocalEnvironmentError("Unknown or duplicate architecture comparison arms")
    if type(disk_reserve_bytes) is not int or disk_reserve_bytes < 10 * 1024 ** 3:
        raise local.LocalEnvironmentError("Physical disk reserve must be at least 10 GiB")
    roots = {name: local.validate_lexical_directory_chain(Path(value).absolute(), label=name)
        for name, value in (("workspace", workspace_root), ("output", output_root), ("harness", harness_root))}
    workspace = roots["workspace"]
    for other in (roots["output"], roots["harness"]):
        if workspace == other or workspace in other.parents or other in workspace.parents:
            raise local.LocalEnvironmentError("Cell workspaces must be separate from evidence and harnesses")
    targets, rows, manifest = dataset.load_architecture_rows(manifest_path, expected_sha256=sha, role=role)
    for source in manifest["datasets"].values():
        source_path = plan._path(source["path"])
        source_root = source_path.parent
        if (workspace == source_root or workspace in source_root.parents
                or source_root in workspace.parents):
            raise local.LocalEnvironmentError("Cell workspaces must be separate from pinned datasets")
    index, image_reference = load_image_index(image_index_path, expected_sha256=image_index_sha256)
    images = dataset.validate_image_bindings(targets, index)
    tasks = tuple(local.benchmark.coding_tasks(targets, rows))
    by_id = {target["target_id"]: target for target in targets}
    if len(by_id) != len(tasks) or len({task.task_id for task in tasks}) != len(tasks):
        raise local.LocalEnvironmentError("Architecture target identities are not unique")
    for task in tasks:
        local._safe_name(task.task_id)
    harnesses = local.prepare_harnesses(roots["harness"])
    preflight = local.benchmark.load_official_harness_loader_preflight(Path(loader_preflight_path))
    local.benchmark.validate_preflight_harness_root_binding(preflight, harnesses)
    summary = {"schema": SCHEMA, "status": "PASS_PUBLIC_BINDINGS",
        "manifest_sha256": sha, "image_index": image_reference,
        "image_bindings_sha256": plan.sha(plan.canonical(images)), "arms": list(selected_arms),
        "target_count": len(tasks), "target_ids": [task.task_id for task in tasks],
        "role": role or "TRAINING_AND_EVALUATION",
        "evaluation_count": sum(target["role"] == "EVALUATION" for target in targets),
        "training_count": sum(target["role"] == "TRAINING" for target in targets),
        "loader_preflight_sha256": plan.sha(plan.canonical(preflight)),
        "image_materialization": "PER_TARGET_BEFORE_MODEL_CALLS",
        "grader_construction": "LAZY_PRIVATE_BINDING_PER_PREPARED_CELL",
        "checkouts": "BASE_ONLY_MATERIALIZED_PER_CELL", "live_cells_prepared": 0,
        "model_calls": 0, "official_grader_runs": 0}
    local._retain(roots["output"] / "control" / "architecture-environment-preflight.json", summary)
    return PreparedArchitectureEnvironment(tasks, by_id, workspace, roots["output"], selected_arms,
        preflight, summary, rows, images, (), harnesses, disk_reserve_bytes,
        _architecture_manifest=manifest)
