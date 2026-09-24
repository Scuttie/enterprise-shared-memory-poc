"""Local Linux preparation for the additive SK hynix DEV comparison.

Reuses frozen dataset, image, checkout and official-grader primitives.  This
module never invokes a model or runs the official grader. Locked images are
materialized per target and only newly pulled images are eligible for cleanup.
Each cell receives a separate, lazily materialized base-only checkout.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_benchmark_run as benchmark  # noqa: E402
from enterprise_memory.trimem.agent_runtime import CodingTask  # noqa: E402
from enterprise_memory.trimem.git_workspace import (  # noqa: E402
    DockerSandboxCommandRunner,
    GitCheckoutWorkspaceFactory,
)
from trimem_harness_lock import (  # noqa: E402
    prepare_harnesses,
    validate_lexical_directory_chain,
)
from trimem_official_harness_loader_preflight import (  # noqa: E402
    run_official_harness_loader_preflight,
)


ARMS = ("NO_MEMORY", "EXISTING_M2", "SKHYNIX")


class LocalEnvironmentError(RuntimeError):
    """A required local execution binding is unavailable or differs."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _retain(path: Path, value: Mapping[str, Any]) -> None:
    raw = _canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise LocalEnvironmentError(f"Existing preparation evidence differs: {path.name}")
        return
    with path.open("xb") as stream:
        stream.write(raw)


def _safe_name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise LocalEnvironmentError("Unsafe arm or target identifier")
    if value in {".", ".."}:
        raise LocalEnvironmentError("Unsafe arm or target identifier")
    return value


def _image_environment_evidence(values: Any) -> dict[str, Any]:
    """Retain environment names/hash only; never expose image values."""
    if values is None:
        values = []
    if not isinstance(values, list) or len(values) > 256:
        raise LocalEnvironmentError("Malformed image environment")
    names = []
    for item in values:
        if not isinstance(item, str) or len(item.encode("utf-8")) > 8192:
            raise LocalEnvironmentError("Malformed image environment entry")
        name, separator, value = item.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in names:
            raise LocalEnvironmentError("Malformed image environment name")
        upper = name.upper()
        if (upper in {"OPENAI_API_KEY", "GITHUB_TOKEN", "GH_TOKEN", "AWS_ACCESS_KEY_ID",
                      "AWS_SECRET_ACCESS_KEY", "AZURE_CLIENT_SECRET"}
                or upper.endswith(("_PASSWORD", "_SECRET", "_TOKEN"))
                or any(marker in value.casefold() for marker in (
                    "test.patch", "fix.patch", "fail_to_pass", "pass_to_pass",
                    "gold_patch", "target_gold", "-----begin private key-----"))):
            raise LocalEnvironmentError("Solver image environment exposes evaluator or secret material")
        names.append(name)
    return {"variable_names": sorted(names),
            "canonical_sha256": hashlib.sha256(_canonical(values)).hexdigest()}


def inspect_locked_images(
    targets: Sequence[Mapping[str, Any]], images: Mapping[str, Mapping[str, Any]],
    support: Sequence[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Require exact local image digests before any solver can spend tokens."""
    solver_images = {str(images[str(target["instance_id"])]["image"]) for target in targets}
    wanted = solver_images | ({image for image, _ in support} if any(
        str(target["benchmark_id"]).startswith("multi_swe_bench") for target in targets
    ) else set())
    evidence = []
    missing = []
    for image in sorted(wanted):
        completed = subprocess.run(
            ["docker", "image", "inspect", "--format",
             '{"digests":{{json .RepoDigests}},"environment":{{json .Config.Env}}}', image],
            capture_output=True, text=True, check=False, timeout=60,
        )
        if completed.returncode != 0:
            missing.append(image)
            continue
        try:
            value = benchmark.strict_json_loads(completed.stdout)
            digests = value["digests"]
            if (not isinstance(digests, list) or not digests
                    or any(not isinstance(item, str) or "@sha256:" not in item for item in digests)
                    or len(digests) != len(set(digests))):
                raise ValueError("invalid RepoDigests")
            observed = sorted({item.rsplit("@", 1)[1] for item in digests})
            if observed != [image.rsplit("@", 1)[1]]:
                raise ValueError("digest mismatch")
            row = {"image": image, "observed_digests": observed, "status": "PASS"}
            if image in solver_images:
                row["environment"] = _image_environment_evidence(value["environment"])
            evidence.append(row)
        except (KeyError, TypeError, ValueError) as exc:
            raise LocalEnvironmentError("Locked image inspection is invalid") from exc
    if missing:
        raise LocalEnvironmentError("Locked Docker images are not local: " + ", ".join(missing))
    return evidence


def _probe_solver(cell: "PreparedLocalCell") -> dict[str, Any]:
    factory, task = cell.workspace_factory, cell.task
    runner = factory.command_runners[task.task_id]
    checkout = factory.checkout_roots[task.task_id]
    files, directories = benchmark.solver_image_masks(task, cell.target)
    if (type(runner) is not DockerSandboxCommandRunner
            or tuple(runner.masked_image_files) != tuple(sorted(files))
            or tuple(runner.masked_image_directories) != tuple(sorted(directories))
            or runner.content_hash != cell.checkout_evidence["command_sandbox_content_hash"]):
        raise LocalEnvironmentError("Solver sandbox masks differ from target binding")
    # Multi-SWE images include a repository beside evaluator files.  Confirm
    # that public tree is pristine at the target base without reading patches.
    if directories:
        baked_root = directories[0].removesuffix("/.git")
        raw = subprocess.run(
            ["docker", "run", "--rm", "--pull=never", "--network=none", "--read-only",
             "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=64",
             "--entrypoint", "/bin/sh", runner.image, "-ceu",
             'test "$(git -C "$1" rev-parse HEAD)" = "$2"; '
             'test -z "$(git -C "$1" status --porcelain=v1 --untracked-files=all)"',
             "skhynix-base-probe", baked_root, task.commit],
            capture_output=True, text=True, check=False, timeout=120,
        )
        if raw.returncode != 0:
            raise LocalEnvironmentError("Baked solver repository is not a pristine target base")
    checks = [
        "set -eu", 'test "$(id -u)" = 1000', 'test "$(id -g)" = 1000',
        'test "$(git -C /testbed rev-parse HEAD)" = "$1"',
        'test "$(git -C /testbed rev-list --count HEAD)" = 1',
        'test -z "$(git -C /testbed for-each-ref --format=\'%(refname)\')"',
        'test -z "$(git -C /testbed remote)"', "test -w /testbed",
        'test -z "$(env | grep -E \'^(OPENAI_API_KEY|GH_TOKEN|GITHUB_TOKEN|TRIMEM_)\' || true)"',
        "set -- /sys/class/net/*", 'test "$#" = 1', 'test "${1##*/}" = lo',
    ]
    for path in files:
        checks.extend([f"test -e {shlex.quote(path)}", f"test ! -s {shlex.quote(path)}"])
    for path in directories:
        checks.extend([f"test -d {shlex.quote(path)}",
                       f'test -z "$(find {shlex.quote(path)} -mindepth 1 -print -quit)"'])
    checks.append("printf 'PASS_LOCAL_SOLVER_SANDBOX\\n'")
    result = runner.run(checkout, ("/bin/sh", "-ceu", "; ".join(checks),
                                  "skhynix-sandbox-probe", task.commit),
                        cwd=None, timeout_seconds=120)
    if (result.exit_code != 0 or result.timed_out or result.output_truncated
            or result.stdout != "PASS_LOCAL_SOLVER_SANDBOX\n"):
        raise LocalEnvironmentError("Local masked solver sandbox probe failed")
    return {"status": "PASS", "command_sandbox_content_hash": runner.content_hash,
            "masked_image_files": list(files), "masked_image_directories": list(directories),
            "probe_containers": 1 + bool(directories), "official_grader_runs": 0}


@dataclass(frozen=True)
class PreparedLocalCell:
    arm: str
    task: CodingTask
    target: Mapping[str, Any]
    workspace_factory: GitCheckoutWorkspaceFactory
    checkout_evidence: Mapping[str, Any]
    grader: Any = field(repr=False)
    output_root: Path


@dataclass
class PreparedLocalEnvironment:
    tasks: tuple[CodingTask, ...]
    targets_by_id: Mapping[str, Mapping[str, Any]]
    workspace_root: Path
    output_root: Path
    arms: tuple[str, ...]
    loader_preflight: Mapping[str, Any]
    summary: Mapping[str, Any]
    _rows: Mapping[str, Mapping[str, Any]] = field(repr=False)
    _images: Mapping[str, Mapping[str, Any]] = field(repr=False)
    _support: Sequence[tuple[str, str]] = field(repr=False)
    _harnesses: Mapping[str, Path] = field(repr=False)
    disk_reserve_bytes: int = 10 * 1024 ** 3
    _prepared_cells: set[tuple[str, str]] = field(default_factory=set, repr=False)
    _prepared_targets: set[str] = field(default_factory=set, repr=False)
    _owned_images: dict[str, list[str]] = field(default_factory=dict, repr=False)

    def _required_images(self, task: CodingTask) -> list[tuple[str, str]]:
        target = self.targets_by_id[task.task_id]
        entry = self._images[str(target["instance_id"])]
        required = [(str(entry["image"]), str(entry["harness_image_tag"]))]
        if str(target["benchmark_id"]).startswith("multi_swe_bench"):
            required.extend(self._support)
        return required

    @staticmethod
    def _image_id(reference: str) -> str | None:
        result = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", reference],
            capture_output=True, text=True, check=False, timeout=60,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def _check_disk_reserve(self) -> None:
        # WSL's virtual ext4 free capacity can exceed the host disk backing it.
        disk_root = Path("/mnt/c") if Path("/mnt/c").is_dir() else self.output_root
        while not disk_root.exists():
            disk_root = disk_root.parent
        if shutil.disk_usage(disk_root).free < self.disk_reserve_bytes:
            raise LocalEnvironmentError("Insufficient physical free disk space for locked image preparation")

    def prepare_target(self, task: CodingTask) -> Mapping[str, Any]:
        if task not in self.tasks:
            raise LocalEnvironmentError("Target is outside the declared DEV comparison")
        target = self.targets_by_id[task.task_id]
        if task.task_id not in self._prepared_targets:
            for image, tag in self._required_images(task):
                if self._image_id(image) is not None:
                    continue
                self._check_disk_reserve()
                preexisting_tag = self._image_id(tag)
                log = self.output_root / "control" / "image-pulls" / (
                    hashlib.sha256(image.encode()).hexdigest() + ".log"
                )
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open("ab") as stream:
                    process = subprocess.Popen(
                        ["docker", "pull", image], stdin=subprocess.DEVNULL,
                        stdout=stream, stderr=subprocess.STDOUT,
                    )
                    try:
                        deadline = time.monotonic() + 1800
                        while process.poll() is None:
                            self._check_disk_reserve()
                            if time.monotonic() >= deadline:
                                raise LocalEnvironmentError("Locked image pull exceeded 30 minutes")
                            time.sleep(1)
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait(timeout=30)
                if process.returncode != 0 or self._image_id(image) is None:
                    raise LocalEnvironmentError("Locked image pull failed; see image-pull log")
                self._owned_images[image] = [] if preexisting_tag else [tag]
                self._check_disk_reserve()
            self._prepared_targets.add(task.task_id)
        evidence = {"target_id": task.task_id, "status": "PASS",
                    "images": inspect_locked_images([target], self._images, self._support)}
        _retain(self.output_root / "control" / "target-images" / f"{task.task_id}.json", evidence)
        return evidence

    def _release_image(self, image: str) -> bool:
        if image not in self._owned_images:
            return False
        expected_id = self._image_id(image)
        if expected_id is None:
            del self._owned_images[image]
            return True
        references = [tag for tag in self._owned_images[image]
                      if self._image_id(tag) == expected_id] + [image]
        result = subprocess.run(["docker", "image", "rm", *references],
                                capture_output=True, text=True, check=False, timeout=120)
        removed = result.returncode == 0 and self._image_id(image) is None
        if removed:
            del self._owned_images[image]
        return removed

    def release_target(self, task: CodingTask) -> Mapping[str, Any]:
        """Release this run's target image after all arms; retain shared support."""
        if task not in self.tasks:
            raise LocalEnvironmentError("Target is outside the declared DEV comparison")
        image = self._required_images(task)[0][0]
        removed = self._release_image(image)
        self._prepared_targets.discard(task.task_id)
        return {"target_id": task.task_id, "image": image, "removed_owned_image": removed}

    def release_owned_images(self) -> list[dict[str, Any]]:
        """Explicit end-of-run cleanup; preexisting images are never selected."""
        return [{"image": image, "removed": self._release_image(image)}
                for image in list(self._owned_images)]

    def prepare_cell(self, arm: str, task: CodingTask, *, resume: bool = False) -> PreparedLocalCell:
        if arm not in self.arms or task not in self.tasks:
            raise LocalEnvironmentError("Cell is outside the declared DEV comparison")
        identity = (arm, task.task_id)
        if identity in self._prepared_cells:
            raise LocalEnvironmentError("Cell was already prepared in this process")
        self.prepare_target(task)
        arm_name, target_name = _safe_name(arm), _safe_name(task.task_id)
        checkouts = self.workspace_root / arm_name / target_name / "checkouts"
        cell_output = self.output_root / "cells" / arm_name / target_name
        if checkouts.exists() and any(checkouts.iterdir()) and not resume:
            raise LocalEnvironmentError("Fresh cell checkout already exists; use a new experiment root")
        target = self.targets_by_id[task.task_id]
        factory, evidence = benchmark.prepare_checkouts(
            [task], [target], self._images, checkouts, resume=resume,
        )
        attestation = evidence[task.task_id]
        if not resume and attestation.get("initial_status") != "":
            raise LocalEnvironmentError("Fresh cell checkout is not pristine")
        if not benchmark._valid_history_isolation_evidence(
            attestation.get("history_isolation"), expected_commit=task.commit,
        ):
            raise LocalEnvironmentError("Cell checkout history is not base-only")
        if type(factory) is not GitCheckoutWorkspaceFactory or not factory.production_capable:
            raise LocalEnvironmentError("Cell workspace lacks the frozen Docker command runner")
        grader = benchmark.grader_factory(
            target, self._rows[str(target["instance_id"])], self._images[str(target["instance_id"])],
            self._harnesses, cell_output / "official-grader", arm, self._support,
            loader_preflight_evidence=self.loader_preflight,
        )
        cell = PreparedLocalCell(arm, task, target, factory, attestation, grader, cell_output)
        sandbox = _probe_solver(cell)
        _retain(cell_output / "control" / "solver-sandbox-preflight.json", sandbox)
        if not resume:
            _retain(cell_output / "control" / "checkout-preflight.json", attestation)
        self._prepared_cells.add(identity)
        return cell


def prepare_local_environment(
    *, workspace_root: str | Path, output_root: str | Path,
    dataset_cache_root: str | Path, harness_root: str | Path,
    loader_preflight_path: str | Path | None = None,
    supplemental_manifest_path: str | Path | None = None,
    supplemental_manifest_sha256: str | None = None,
    arms: Sequence[str] = ARMS,
    disk_reserve_bytes: int = 10 * 1024 ** 3,
) -> PreparedLocalEnvironment:
    """Validate the frozen DEV stream or an additive native manifest."""
    if sys.platform != "linux":
        raise LocalEnvironmentError("Official local execution requires Linux; use the existing WSL runner")
    selected_arms = tuple(arms)
    if not selected_arms or len(set(selected_arms)) != len(selected_arms) or set(selected_arms) - set(ARMS):
        raise LocalEnvironmentError("Unknown or duplicate comparison arms")
    if type(disk_reserve_bytes) is not int or disk_reserve_bytes < 10 * 1024 ** 3:
        raise LocalEnvironmentError("Physical disk reserve must be at least 10 GiB")
    roots = {}
    for name, value in (("workspace", workspace_root), ("output", output_root),
                        ("dataset", dataset_cache_root), ("harness", harness_root)):
        roots[name] = validate_lexical_directory_chain(Path(value).absolute(), label=name)
    workspace = roots["workspace"]
    for name in ("output", "dataset", "harness"):
        other = roots[name]
        if workspace == other or workspace in other.parents or other in workspace.parents:
            raise LocalEnvironmentError("Cell workspaces must be separate from evidence, datasets and harnesses")
    supplemental = None
    if (supplemental_manifest_path is None) != (supplemental_manifest_sha256 is None):
        raise LocalEnvironmentError("Supplemental manifest path and raw SHA256 must be paired")
    if supplemental_manifest_path is None:
        targets, rows = benchmark.load_frozen_rows("development", roots["dataset"])
        if len(targets) != 12:
            raise LocalEnvironmentError("Expected the entire frozen 12-target DEV stream")
        images, support = benchmark.image_entries(require_benchmark=True)
    else:
        from trimem_skhynix_native_dataset import load_supplemental_rows
        targets, rows, images, supplemental = load_supplemental_rows(
            Path(supplemental_manifest_path), roots["dataset"],
            expected_sha256=supplemental_manifest_sha256,
        )
        support = []
    tasks = tuple(benchmark.coding_tasks(targets, rows))
    targets_by_id = {str(target["target_id"]): target for target in targets}
    if len(targets_by_id) != len(tasks) or len({task.task_id for task in tasks}) != len(tasks):
        raise LocalEnvironmentError("DEV target identities are not unique")
    for task in tasks:
        _safe_name(task.task_id)
    for target in targets:
        if str(target["instance_id"]) not in images:
            raise LocalEnvironmentError("Frozen target image binding is missing")
    harnesses = prepare_harnesses(roots["harness"])
    if loader_preflight_path is None:
        preflight = run_official_harness_loader_preflight(
            python_binary=sys.executable, swe_harness_root=harnesses["swebench_verified"],
            multi_harness_root=harnesses["multi_swe_bench_mini"],
        )
        preflight = benchmark.validate_official_harness_loader_preflight_evidence(preflight)
        _retain(roots["output"] / "control" / "official-harness-loader-preflight.json", preflight)
    else:
        preflight = benchmark.load_official_harness_loader_preflight(Path(loader_preflight_path))
    benchmark.validate_preflight_harness_root_binding(preflight, harnesses)
    grader_evidence = []
    for target in targets:
        grader = benchmark.grader_factory(
            target, rows[str(target["instance_id"])], images[str(target["instance_id"])],
            harnesses, roots["output"] / "control" / "grader-construction" / str(target["target_id"]),
            "SKHYNIX_PREFLIGHT", support, loader_preflight_evidence=preflight,
        )
        grader_evidence.append({"target_id": target["target_id"], "type": type(grader).__name__})
    summary = {
        "schema": "skhynix/local-environment-preflight/1.0", "status": "PASS",
        "split": "native_supplemental" if supplemental is not None else "development",
        "target_count": len(tasks), "arms": list(selected_arms),
        "planned_cells": len(tasks) * len(selected_arms),
        "target_ids": [task.task_id for task in tasks],
        "targets_sha256": hashlib.sha256(_canonical(targets)).hexdigest(),
        "image_materialization": "PER_TARGET_BEFORE_MODEL_CALLS",
        "image_lock_sha256": hashlib.sha256(_canonical(images)).hexdigest(),
        "grader_construction": grader_evidence,
        "loader_preflight_sha256": hashlib.sha256(_canonical(preflight)).hexdigest(),
        "checkouts": "MATERIALIZED_PER_CELL", "model_calls": 0, "official_grader_runs": 0,
    }
    if supplemental is not None:
        summary["supplemental_manifest_sha256"] = supplemental_manifest_sha256
        summary["target_roles"] = {target["target_id"]: target["role"] for target in targets}
        summary["scope_claim"] = supplemental["scope_claim"]
    _retain(roots["output"] / "control" / "local-environment-preflight.json", summary)
    return PreparedLocalEnvironment(
        tasks, targets_by_id, workspace, roots["output"], selected_arms, preflight, summary,
        rows, images, support, harnesses, disk_reserve_bytes,
    )
