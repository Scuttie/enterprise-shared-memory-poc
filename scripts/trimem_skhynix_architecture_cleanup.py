"""Evidence-gated cleanup of completed architecture target checkouts/images.

Only generated checkouts are disposable. Cell/broker/native records, sealed
patches, private grader output, preparation evidence and capture receipts remain
in place and are hash-bound before deletion. Training requires its PDF cell;
evaluation requires both cells. No model, grader, shell or Docker prune is used.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import os
import re
import shutil
import stat
import sys

from enterprise_memory.trimem.accounting import strict_json_loads


SCHEMA = "skhynix/architecture-target-cleanup/1.0"
POLICY_SCHEMA = "skhynix/architecture-cleanup-policy/1.0"
EVALUATION_CAPTURE_SCHEMA = "skhynix/architecture-evaluation-capture/1.0"
PHASE_ARMS = {"TRAINING": ("PDF_MEMORY",), "EVALUATION": ("BASELINE", "PDF_MEMORY")}


class CleanupError(ValueError):
    pass


def _fail(message):
    raise CleanupError(message)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _path(value, *, kind=None, missing=False):
    if not isinstance(value, (str, Path)):
        _fail("Cleanup path must be an absolute canonical path")
    path = Path(value)
    if (not path.is_absolute() or str(path) != str(value) or ".." in path.parts
            or path.resolve() != path):
        _fail("Cleanup path is noncanonical or resolves elsewhere")
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            _fail("Linked cleanup paths are forbidden")
    if not missing and not path.exists():
        _fail("Required cleanup input is missing")
    if path.exists() and ((kind == "file" and not path.is_file()) or (kind == "directory" and not path.is_dir())):
        _fail("Cleanup path type differs")
    return path


def _file_hash(path):
    digest = hashlib.sha256()
    with _path(path, kind="file").open("rb") as stream:
        for raw in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(raw)
    return digest.hexdigest()


def _reference(path):
    path = _path(path, kind="file")
    return {"path": str(path), "sha256": _file_hash(path)}


def _checked(reference, *, decode=True):
    if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"}
            or not isinstance(reference["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", reference["sha256"]) is None):
        _fail("Malformed immutable cleanup reference")
    if _reference(reference["path"]) != reference:
        _fail("Preserved cleanup evidence bytes changed")
    return _read(reference["path"]) if decode else None


def _read(path):
    return strict_json_loads(_path(path, kind="file").read_bytes())


def _retain(path, value):
    path = _path(path, kind="file", missing=True)
    raw = _canonical(value) + b"\n"
    if path.exists():
        if path.read_bytes() != raw:
            _fail("Existing cleanup evidence is immutable")
        return _reference(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _path(path.parent, kind="directory")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return _reference(path)


def _linux():
    if sys.platform != "linux":
        _fail("Checkout cleanup is restricted to the existing Linux runner")


def _safe_task(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in {".", ".."}:
        _fail("Invalid cleanup task identity")
    return value


def create_cleanup_policy(output, *, experiment_reference, remove_checkouts=True, release_owned_images=True):
    """Freeze opt-in cleanup controls separately from the cohort/execution files."""
    _linux()
    if (type(remove_checkouts) is not bool or type(release_owned_images) is not bool
            or not (remove_checkouts or release_owned_images)):
        _fail("Cleanup policy must explicitly enable checkouts or owned images")
    from trimem_skhynix_architecture_run import load_experiment, execution_enrollment
    _checked(experiment_reference)
    config = load_experiment(experiment_reference["path"])
    enrollment = execution_enrollment(config, _checked(config["dataset_manifest"]))
    phase_arms = {phase: list(arms) for phase, arms in PHASE_ARMS.items()}
    if enrollment is not None:
        phase_arms[config["phase"].removesuffix("_RUNTIME")] = enrollment["arms"]
    root = _path(config["run_root"], kind="directory")
    value = {"schema": POLICY_SCHEMA, "experiment_reference": experiment_reference,
        "run_root": str(root), "remove_checkouts": remove_checkouts,
        "release_owned_images": release_owned_images,
        "phase_arms": phase_arms,
        "required_capture_completion": True, "preserve_all_evidence": True,
        "implementation_sha256": _file_hash(Path(__file__).absolute())}
    if enrollment is not None:
        value["scale_authority_reference"] = config["scale_authority_reference"]
    return _retain(output, value)


def _policy(reference, task_id):
    _linux()
    _safe_task(task_id)
    policy = _checked(reference)
    fields = {"schema", "experiment_reference", "run_root", "remove_checkouts", "release_owned_images",
        "phase_arms", "required_capture_completion", "preserve_all_evidence", "implementation_sha256"}
    if (not isinstance(policy, dict) or set(policy) not in (fields, fields | {"scale_authority_reference"}) or policy["schema"] != POLICY_SCHEMA
            or policy["required_capture_completion"] is not True or policy["preserve_all_evidence"] is not True
            or any(type(policy[name]) is not bool for name in ("remove_checkouts", "release_owned_images"))
            or not (policy["remove_checkouts"] or policy["release_owned_images"])
            or policy["implementation_sha256"] != _file_hash(Path(__file__).absolute())):
        _fail("Frozen cleanup policy differs from the supported safety contract")
    from trimem_skhynix_architecture_run import load_experiment, execution_enrollment
    _checked(policy["experiment_reference"])
    config = load_experiment(policy["experiment_reference"]["path"])
    root = _path(config["run_root"], kind="directory")
    if str(root) != policy["run_root"]:
        _fail("Cleanup run root differs from frozen execution")
    manifest = _checked(config["dataset_manifest"])
    enrollment = execution_enrollment(config, manifest)
    expected_arms = {phase: list(arms) for phase, arms in PHASE_ARMS.items()}
    if enrollment is not None:
        expected_arms[config["phase"].removesuffix("_RUNTIME")] = enrollment["arms"]
        if task_id not in enrollment["task_ids"]:
            _fail("Cleanup task is outside its authorized scale execution subset")
    if policy["phase_arms"] != expected_arms or policy.get("scale_authority_reference") != config.get("scale_authority_reference"):
        _fail("Cleanup arms or scale authority differs from frozen execution")
    if enrollment is None and (manifest.get("training_count") != 24 or manifest.get("evaluation_count") != 500
            or len(manifest.get("targets", ())) != 524
            or len({row["target_id"] for row in manifest["targets"]}) != 524
            or sum(row["role"] == "TRAINING" for row in manifest["targets"]) != 24
            or sum(row["role"] == "EVALUATION" for row in manifest["targets"]) != 500):
        _fail("Cleanup requires the exact frozen 24-training/all-500 enrollment")
    targets = [row for row in manifest["targets"] if row["target_id"] == task_id]
    if len(targets) != 1 or targets[0]["role"] not in PHASE_ARMS:
        _fail("Cleanup target is outside the frozen dataset")
    target = targets[0]
    cells = {arm: root / "cells" / target["role"] / task_id / arm / "cell.json"
        for arm in policy["phase_arms"][target["role"]]}
    return policy, config, target, cells


@contextmanager
def _locked(paths, *, exclusive):
    import fcntl
    with ExitStack() as stack:
        streams = [stack.enter_context(_path(path, kind="file").open("rb")) for path in sorted(paths)]
        for stream in streams:
            fcntl.flock(stream, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield dict(zip(sorted(paths), streams))
        finally:
            for stream in reversed(streams):
                fcntl.flock(stream, fcntl.LOCK_UN)


def _tree_references(root):
    root = _path(root, kind="directory")
    refs = []
    for current, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            _path(Path(current) / name, kind="directory")
        for name in files:
            refs.append(_reference(Path(current) / name))
    return refs


def _capture(reference, cell_path, cell, *, native_root, depth=0):
    """Follow only bounded immutable capture wrappers, retaining every link."""
    if depth > 4:
        _fail("Capture receipt wrapper depth exceeds its bound")
    value = _checked(reference)
    refs = [reference]
    if isinstance(value, dict) and set(value) == {"path", "sha256"}:
        return refs + _capture(value, cell_path, cell, native_root=native_root, depth=depth + 1)
    if value.get("operation") == "COHORT_CAPTURE":
        return refs + _capture(value["capture_receipt"], cell_path, cell, native_root=native_root, depth=depth + 1)
    task_id = cell["task_public"]["task_id"]
    if value.get("cell_path") != str(cell_path) or value.get("task_id") != task_id:
        _fail("Capture receipt belongs to another cell or task")
    if cell["phase"] == "TRAINING":
        if (value.get("schema") != "skhynix/native-architecture-learning/1.0"
                or value.get("operation") != "CAPTURE_CELL" or value.get("failures") != []
                or value.get("status") not in {"CAPTURED", "NO_PUBLIC_ATTEMPTS"}
                or value.get("owner_user_id") != cell["owner_user_id"]
                or value.get("source_execution_observed") is False):
            _fail("Training capture is incomplete or failed")
        if value["status"] == "CAPTURED" and not value.get("captures"):
            _fail("Successful training capture has no retained captures")
        if value["status"] == "NO_PUBLIC_ATTEMPTS" and (
                value.get("captures") != [] or value.get("source_execution_observed") is not True):
            _fail("Empty-attempt capture lacks completed source execution")
    else:
        if (value.get("schema") != EVALUATION_CAPTURE_SCHEMA
                or value.get("operation") != "CAPTURE_EVALUATION_CELL"
                or value.get("arm") != cell["arm"] or value.get("bank_sha256") != cell["bank_sha256"]
                or value.get("failures") != []):
            _fail("Evaluation capture binding is incomplete")
        if cell["arm"] == "BASELINE":
            if value.get("status") != "BASELINE_AUDIT_ONLY" or value.get("quarantine_references") != []:
                _fail("Baseline requires an explicit completed audit-only capture receipt")
        elif (value.get("status") not in {"CAPTURED", "NO_PUBLIC_ATTEMPTS"}
                or value.get("admitted_to_frozen_bank") is not False
                or not isinstance(value.get("quarantine_references"), list)
                or (value["status"] == "CAPTURED" and not value["quarantine_references"])):
            _fail("PDF evaluation capture lacks completed isolated quarantine evidence")
        for item in value["quarantine_references"]:
            _checked(item, decode=False)
            refs.append(item)
    sources = value.get("source_references")
    if not isinstance(sources, dict) or not {"cell.json", "state.json", "events.jsonl", "submission.diff"} <= set(sources):
        _fail("Capture receipt lacks sealed source references")
    for name, ref in sources.items():
        if name == "cell.json":
            expected = cell_path
        elif name in {"public-result.json", "execution-audit.json"}:
            expected = cell_path.parent / name
        elif re.fullmatch(r"broker/packets/[0-9]+\.json", name):
            expected = cell_path.parent / name
        elif match := re.fullmatch(r"native/worker-([0-9]+)/(?P<file>completion\.json|events\.jsonl|launch\.json|prompt\.txt|packet\.json)", name):
            number = int(match[1])
            if not 1 <= number <= 121:
                _fail("Capture native worker index exceeds the whole-task request bound")
            filename = match["file"]
            expected = native_root / f"worker-{number:03d}"
            if filename in {"completion.json", "events.jsonl", "launch.json"}:
                expected = expected / "output"
            expected = expected / filename
        elif name in {"manifest.json", "manifest.sha256", "initial-state.json", "state.json", "events.jsonl", "submission.json", "submission.diff"}:
            expected = cell_path.parent / "broker" / name
        else:
            _fail("Capture source reference has an undeclared manager artifact name")
        if ref["path"] != str(expected):
            _fail("Capture source reference points outside its sealed cell")
        _checked(ref, decode=False)
        refs.append(ref)
    return refs


def _workspace_snapshot(path, commit):
    from enterprise_memory.trimem.git_workspace import GitCheckoutWorkspace, validate_safe_local_git_configuration
    from trimem_benchmark_run import _run_hermetic_git
    path = _path(path, kind="directory")
    validate_safe_local_git_configuration(path)
    before = path.stat()
    observed = _run_hermetic_git(["-C", str(path), "rev-parse", "--verify", "HEAD"]).stdout.strip()
    if observed != commit:
        _fail("Disposable checkout no longer has the recorded base commit")
    checkpoint = GitCheckoutWorkspace(path, base_commit=commit).checkpoint_state()
    info = path.stat()
    if (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino):
        _fail("Disposable checkout directory changed during patch verification")
    return {"path": str(path), "device": info.st_dev, "inode": info.st_ino,
        "base_commit": commit, "patch_sha256": checkpoint["patch_sha256"],
        "inventory_sha256": checkpoint["inventory_sha256"]}


def _cell(config, target, arm, registration, *, prior=None, broker_lock=None):
    import trimem_skhynix_architecture_broker as broker_module
    import trimem_benchmark_run as benchmark
    root, task_id, phase = Path(config["run_root"]), target["target_id"], target["role"]
    path = _path(root / "cells" / phase / task_id / arm / "cell.json", kind="file")
    cell = _read(path)
    checksum = path.with_suffix(".sha256")
    if _sha(_canonical(cell)) != _path(checksum, kind="file").read_text().strip():
        _fail("Frozen cell configuration changed")
    public = cell["task_public"]
    if (cell.get("phase") != phase or cell.get("arm") != arm
            or cell.get("experiment_config") != registration["experiment_reference"]["path"]
            or public.get("task_id") != task_id or public.get("repository") != target["repository"]
            or public.get("commit") != target["base_commit"]
            or _sha(public.get("instruction", "").strip().encode()) != target["instruction_sha256"]
            or cell.get("broker_root") != str(path.parent / "broker")):
        _fail("Cell identity differs from frozen execution enrollment")
    checkout = _path(cell["workspace_configuration"]["checkout_root"], kind="directory", missing=prior is not None)
    expected_checkout = root / "workspaces" / arm / task_id / "checkouts" / task_id
    if checkout != expected_checkout:
        _fail("Disposable checkout differs from its exact generated task path")
    output = _path(cell["prepared_output_root"], kind="directory")
    if output != root / "environment" / phase / "cells" / arm / task_id:
        _fail("Preparation evidence is outside the generated cell evidence root")
    broker_root = Path(cell["broker_root"])
    if (broker_root / "pending.json").exists():
        _fail("Cleanup cannot recover or discard pending broker work")
    broker = broker_module.ArchitectureBroker(broker_root, workspace=SimpleNamespace(),
        configuration_sha256=_sha(_canonical(config)), bank_sha256=cell["bank_sha256"])
    state, events = broker._load()
    if (broker.task != public or broker.arm != arm or state["status"] != "SUBMITTED"
            or state["submission"] is None):
        _fail("Cleanup requires the enrolled sealed broker submission")
    event_tail = events[-1]["sha256"] if events else "0" * 64
    result_reference = registration["result_reference"]
    undetermined = result_reference["path"] == str(path.parent / "training-grade-undetermined.json")
    if undetermined:
        if (phase != "TRAINING" or arm != "PDF_MEMORY"
                or config.get("training_grade_hold_policy") != "CAPTURE_KNOWN_TERMINAL_AMBIGUITY_AND_CONTINUE"):
            _fail("Unscored terminal cleanup requires its explicit training-only authority")
        import trimem_skhynix_architecture_run as execution
        proof = execution.training_grade_undetermined(path, create=False, _broker_lock=broker_lock)
        if proof is None or proof[1] != result_reference:
            _fail("Unscored training outcome lacks matching retained terminal evidence")
    elif result_reference["path"] != str(path.parent / "public-result.json"):
        _fail("Completed result reference is outside its cell")
    result = _checked(result_reference)
    patch_reference = _reference(broker_root / "submission.diff")
    recorded = result.get("broker_status", {})
    if (result.get("task_id") != task_id or result.get("phase") != phase or result.get("arm") != arm
            or (undetermined and (result.get("official") is not False or result.get("resolved") is not None
                or result.get("grader_status") != "undetermined" or result.get("official_outcome") != "UNDETERMINED"))
            or (not undetermined and (result.get("official") is not True or result.get("grader_status") != "success"
                or type(result.get("resolved")) is not bool))
            or result.get("experiment_sha256") != _sha(_canonical(config))
            or result.get("bank_sha256") != cell["bank_sha256"]
            or result.get("container_digest") != cell["workspace_configuration"]["image"]
            or result.get("patch_sha256") != patch_reference["sha256"]
            or result.get("event_tail_sha256") != event_tail
            or recorded.get("status") != "SUBMITTED" or recorded.get("submission") != state["submission"]
            or recorded.get("budget", {}).get("requests_used") != state["actions"]):
        _fail("Public official grade is incomplete or differs from the sealed cell")
    audit_reference = _reference(path.parent / "execution-audit.json")
    audit = _checked(audit_reference)
    if (result.get("execution_audit_sha256") != audit_reference["sha256"]
            or audit.get("passed") is not True or audit.get("errors") != []
            or audit.get("task_id") != task_id or audit.get("arm") != arm
            or audit.get("configuration_sha256") != _sha(_canonical(config))
            or audit.get("event_tail_sha256") != event_tail
            or audit.get("patch_sha256") != patch_reference["sha256"]):
        _fail("Native execution audit does not authenticate the completed grade")
    workers = audit.get("workers")
    if (not isinstance(workers, list) or not workers or [w.get("number") for w in workers] != list(range(1, len(workers) + 1))
            or len(workers) != len(state["workers"]) or any("thread_id" not in w for w in state["workers"].values())
            or len({w["thread_id"] for w in workers}) != len(workers)):
        _fail("Native execution workers are incomplete or duplicated")
    native_root = _path(Path(config["native_control_root"]) / phase / target["instance_id"] / arm, kind="directory")
    for worker in workers:
        folder = native_root / f"worker-{worker['number']:03d}" / "output"
        completion_ref = _reference(folder / "completion.json")
        completion = _checked(completion_ref)
        if (completion_ref["sha256"] != worker["completion_sha256"]
                or _file_hash(folder / "events.jsonl") != worker["events_sha256"]
                or completion.get("events_sha256") != worker["events_sha256"]
                or completion.get("thread_id") != worker["thread_id"]
                or completion.get("admitted") is not True or completion.get("errors") != []
                or completion.get("outside_broker_tool_events") != [] or completion.get("transport_errors", [])
                or worker.get("outcome") not in {"COMPLETE", "BUDGET_TIMEOUT"}
                or (worker["outcome"] == "COMPLETE" and (completion.get("exit_code") != 0 or completion.get("timed_out") is not False))
                or (worker["outcome"] == "BUDGET_TIMEOUT" and completion.get("timed_out") is not True)
                or list(folder.glob("manager-error-*.json"))):
            _fail("Native completion differs from its successful execution audit")
    if (path.parent / "native-execution-failure.json").exists():
        _fail("Native execution failure prevents cleanup")
    if not undetermined:
        private = _reference(path.parent / "grader-private.json")
        if result.get("grader_private_sha256") != private["sha256"]:
            _fail("Private grader output bytes differ; contents are not decoded")
    preparation = {name: _reference(output / "control" / name) for name in
        ("checkout-preflight.json", "solver-sandbox-preflight.json", "public-python-preflight.json")}
    attestation = _checked(preparation["checkout-preflight.json"])
    if (attestation.get("head") != target["base_commit"] or attestation.get("initial_status") != ""
            or attestation.get("checkout_origin") != "FRESH_BASE_ONLY_FETCH"
            or not benchmark._valid_history_isolation_evidence(attestation.get("history_isolation"), expected_commit=target["base_commit"])
            or attestation.get("command_sandbox_content_hash") != cell["workspace_configuration"]["command_runner_sha256"]):
        _fail("Checkout lacks its exact fresh base-only preparation proof")
    for name in ("solver-sandbox-preflight.json", "public-python-preflight.json"):
        proof = _checked(preparation[name])
        if (proof.get("status") != "PASS"
                or proof.get("command_sandbox_content_hash") != attestation["command_sandbox_content_hash"]):
            _fail("Public sandbox preparation differs from the completed cell")
    capture_reference = registration.get("capture_reference")
    if capture_reference is None:
        _fail("Completed learning or evaluation capture receipt is required before cleanup")
    capture_refs = _capture(capture_reference, path, cell, native_root=native_root)
    if checkout.exists():
        snapshot = _workspace_snapshot(checkout, target["base_commit"])
        if snapshot["patch_sha256"] != patch_reference["sha256"]:
            _fail("Checkout changed after the sealed public patch")
        if prior is not None and snapshot != prior["checkout"]:
            _fail("Checkout changed after immutable cleanup intent")
    elif prior is not None:
        snapshot = prior["checkout"]
    else:
        _fail("Missing checkout has no earlier immutable cleanup intent")
    image = cell["workspace_configuration"]["image"]
    from trimem_skhynix_architecture_dataset import official_image_tag
    from trimem_skhynix_architecture_environment import load_image_index
    images, _ = load_image_index(config["image_index"]["path"], expected_sha256=config["image_index"]["sha256"])
    if images.get(target["instance_id"], {}).get("image") != image:
        _fail("Cell command image differs from the frozen registry index")
    tag = official_image_tag(target["instance_id"])
    if not re.fullmatch(re.escape(tag.removesuffix(":latest")) + r"@sha256:[0-9a-f]{64}", image):
        _fail("Cell command image is not its official frozen instance digest")
    owned = cell.get("owned_images")
    if (not isinstance(owned, dict) or set(owned) - {image}
            or any(tags not in ([], [tag]) for tags in owned.values())):
        _fail("Cell ownership evidence contains unrelated images or preexisting tags")
    refs = [*capture_refs, *_tree_references(path.parent), *_tree_references(output), *_tree_references(native_root)]
    return {"cell_path": str(path), "task_id": task_id, "phase": phase, "arm": arm,
        "source_commit": target["base_commit"], "repository": target["repository"],
        "result_reference": result_reference, "capture_reference": capture_reference,
        "patch_reference": patch_reference, "patch_sha256": patch_reference["sha256"],
        "event_tail_sha256": event_tail, "workspace_preparation_references": preparation,
        "checkout": snapshot, "owned_images": owned}, refs


def _intent_path(config, task_id):
    return Path(config["run_root"]) / "cleanup" / task_id / "intent.json"


def _build_plan(policy_reference, policy, config, target, cells, registrations, *, broker_locks=None):
    task_id = target["target_id"]
    intent_path = _intent_path(config, task_id)
    previous = _read(intent_path) if intent_path.exists() else None
    if previous is not None:
        for reference in previous["preserved_references"]:
            _checked(reference, decode=False)
    entries, references = [], [policy_reference, policy["experiment_reference"], config["dataset_manifest"], config["image_index"]]
    for arm in cells:
        registration = registrations[arm]
        if (registration["cell_path"] != str(cells[arm])
                or registration["experiment_reference"] != policy["experiment_reference"]):
            _fail("Cleanup registration differs from its frozen target")
        prior = next((entry for entry in previous["cells"] if entry["arm"] == arm), None) if previous else None
        entry, refs = _cell(config, target, arm, registration, prior=prior,
            broker_lock=(broker_locks or {}).get(cells[arm].parent / "broker" / "broker.lock"))
        entries.append(entry)
        references.extend(refs)
    by_path = {}
    for reference in references:
        if reference["path"] in by_path and by_path[reference["path"]] != reference:
            _fail("Retained evidence changed while cleanup was planned")
        by_path[reference["path"]] = reference
        for entry in entries:
            checkout = Path(entry["checkout"]["path"])
            retained = Path(reference["path"])
            if retained == checkout or checkout in retained.parents:
                _fail("A required retained artifact is inside a disposable checkout")
    owned = {}
    for entry in entries:
        for image, tags in entry["owned_images"].items():
            owned[image] = sorted(set(owned.get(image, [])) | set(tags))
    plan = {"schema": SCHEMA, "status": "VALIDATED_CLEANUP_INTENT", "task_id": task_id,
        "phase": target["role"], "policy_reference": policy_reference,
        "run_root": config["run_root"], "cells": entries, "owned_images": owned,
        "remove_checkouts": policy["remove_checkouts"], "release_owned_images": policy["release_owned_images"],
        "preserved_references": [by_path[path] for path in sorted(by_path)],
        "reproduction": "FETCH_REPOSITORY_AT_SOURCE_COMMIT_THEN_APPLY_RETAINED_BINARY_PATCH",
        "model_calls": 0, "official_grader_runs": 0}
    if previous is not None and previous != plan:
        _fail("Current target evidence differs from immutable cleanup intent")
    return plan


def plan_target_cleanup(policy_reference, task_id, *, registrations):
    """Read-only concrete removal plan; registrations map required arm to inputs."""
    policy, config, target, cells = _policy(policy_reference, task_id)
    if set(registrations) != set(cells):
        _fail("Cleanup requires every phase arm's completed registration")
    with _locked([path.parent / "broker" / "broker.lock" for path in cells.values()], exclusive=False) as broker_locks:
        return _build_plan(policy_reference, policy, config, target, cells, registrations, broker_locks=broker_locks)


def _remove_checkout(snapshot):
    """Linux fd-based rmtree; never follows a redirected checkout/parent path."""
    path = _path(snapshot["path"], kind="directory", missing=True)
    if not path.exists():
        return {"path": str(path), "status": "ABSENT_AFTER_RETAINED_INTENT"}
    if not getattr(shutil.rmtree, "avoids_symlink_attacks", False):
        _fail("Python lacks the required fd-based symlink-safe tree removal")
    parent = os.open(_path(path.parent, kind="directory"), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        observed = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if (not stat.S_ISDIR(observed.st_mode)
                or (observed.st_dev, observed.st_ino) != (snapshot["device"], snapshot["inode"])):
            _fail("Disposable checkout directory identity changed before removal")
        shutil.rmtree(path.name, dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(parent)
    if path.exists() or path.is_symlink():
        _fail("Disposable checkout removal did not complete")
    return {"path": str(path), "status": "REMOVED_GENERATED_CHECKOUT"}


def _release_owned_images(owned):
    from trimem_skhynix_environment import PreparedLocalEnvironment
    # Reuse the existing no-force ownership gate. Its implementation requires
    # only this map; it skips reassigned tags and never selects cached images.
    environment = object.__new__(PreparedLocalEnvironment)
    environment._owned_images = {image: list(tags) for image, tags in owned.items()}
    return environment.release_owned_images()


def _execute(policy_reference, task_id, registrations):
    policy, config, target, cells = _policy(policy_reference, task_id)
    if set(registrations) != set(cells):
        _fail("Cleanup requires both evaluation arms or the sole training PDF arm")
    with _locked([path.parent / "broker" / "broker.lock" for path in cells.values()], exclusive=True) as broker_locks:
        plan = _build_plan(policy_reference, policy, config, target, cells, registrations, broker_locks=broker_locks)
        intent = _retain(_intent_path(config, task_id), plan)
        checkouts = [_remove_checkout(entry["checkout"]) for entry in plan["cells"]] if plan["remove_checkouts"] else []
        images = _release_owned_images(plan["owned_images"]) if plan["release_owned_images"] else []
        success = all(row["removed"] for row in images)
        result = {"schema": SCHEMA, "status": "COMPLETE" if success else "INCOMPLETE_IMAGE_RELEASE",
            "intent_reference": intent, "task_id": task_id, "phase": target["role"],
            "checkouts": checkouts, "images": images, "preserved_references": plan["preserved_references"],
            "model_calls": 0, "official_grader_runs": 0}
        for reference in plan["preserved_references"]:
            _checked(reference, decode=False)
        folder = _intent_path(config, task_id).parent
        if not success:
            index = 1
            while (folder / f"attempt-{index:04d}.json").exists():
                index += 1
            _retain(folder / f"attempt-{index:04d}.json", result)
            _fail("Owned image release is incomplete; retained intent permits explicit retry")
        reference = _retain(folder / "completion.json", result)
        _retain(folder / "completion.ref.json", reference)
        return reference


def cleanup_completed_cell(cell_path, expected_result_reference, expected_capture_reference=None, *, policy_reference):
    """Register completion, then clean only when every required target arm is done.

    Call under the cohort manager's run lock. This function adds a separate
    cleanup lock and the brokers' exclusive locks; it launches no solver/grader.
    """
    _linux()
    cell_path = _path(cell_path, kind="file")
    cell = _read(cell_path)
    task_id = cell["task_public"]["task_id"]
    policy, config, target, cells = _policy(policy_reference, task_id)
    arm = cell["arm"]
    if arm not in cells or cells[arm] != cell_path:
        _fail("Completed cleanup cell is outside its exact required phase path")
    folder = _intent_path(config, task_id).parent
    completion = folder / "completion.json"
    if completion.exists():
        validate_completed_cleanup(cell_path, expected_result_reference, expected_capture_reference)
        return {"status": "COMPLETE", "cleanup_reference": _reference(completion)}
    if expected_capture_reference is None:
        _fail("Capture completion is required before registering cleanup")
    _checked(expected_result_reference)
    _checked(expected_capture_reference)
    folder.mkdir(parents=True, exist_ok=True)
    _path(folder, kind="directory")
    lock_path = folder / "cleanup.lock"
    _path(lock_path, kind="file", missing=True)
    with lock_path.open("ab"):
        pass
    with _locked([lock_path], exclusive=True):
        if completion.exists():
            validate_completed_cleanup(cell_path, expected_result_reference, expected_capture_reference)
            return {"status": "COMPLETE", "cleanup_reference": _reference(completion)}
        registration = {"schema": SCHEMA, "cell_path": str(cell_path),
            "experiment_reference": policy["experiment_reference"],
            "result_reference": expected_result_reference, "capture_reference": expected_capture_reference}
        previous = _read(_intent_path(config, task_id)) if _intent_path(config, task_id).exists() else None
        prior = next((entry for entry in previous["cells"] if entry["arm"] == arm), None) if previous else None
        with _locked([cell_path.parent / "broker" / "broker.lock"], exclusive=False) as broker_locks:
            _cell(config, target, arm, registration, prior=prior,
                broker_lock=broker_locks[cell_path.parent / "broker" / "broker.lock"])
        _retain(folder / (arm + ".completed.json"), registration)
        if any(not (folder / (name + ".completed.json")).exists() for name in cells):
            return {"status": "WAITING_FOR_PAIRED_COMPLETION", "cleanup_reference": None}
        registrations = {name: _read(folder / (name + ".completed.json")) for name in cells}
        reference = _execute(policy_reference, task_id, registrations)
        return {"status": "COMPLETE", "cleanup_reference": reference}


def validate_completed_cleanup(cell_path, expected_result_reference, expected_capture_reference=None):
    """Validate retained completion evidence without reopening deleted checkouts."""
    _linux()
    cell_path = _path(cell_path, kind="file")
    cell = _read(cell_path)
    task_id = _safe_task(cell["task_public"]["task_id"])
    root = cell_path.parents[4]
    folder = root / "cleanup" / task_id
    completion_reference = _read(folder / "completion.ref.json")
    if completion_reference["path"] != str(folder / "completion.json"):
        _fail("Cleanup completion reference is outside its target")
    completion = _checked(completion_reference)
    intent = _checked(completion["intent_reference"])
    policy, config, target, cells = _policy(intent["policy_reference"], task_id)
    if (completion.get("schema") != SCHEMA or completion.get("status") != "COMPLETE"
            or completion.get("task_id") != task_id or completion.get("phase") != target["role"]
            or completion["preserved_references"] != intent["preserved_references"]
            or intent.get("run_root") != str(root) or config["run_root"] != str(root)
            or set(entry["arm"] for entry in intent["cells"]) != set(cells)
            or any(not row.get("removed") for row in completion["images"])):
        _fail("Cleanup completion does not bind the completed target")
    expected_paths = [entry["checkout"]["path"] for entry in intent["cells"]] if policy["remove_checkouts"] else []
    if ([entry.get("path") for entry in completion.get("checkouts", ())] != expected_paths
            or any(entry.get("status") not in {"REMOVED_GENERATED_CHECKOUT", "ABSENT_AFTER_RETAINED_INTENT"}
                for entry in completion["checkouts"])
            or {entry.get("image") for entry in completion["images"]} !=
                (set(intent["owned_images"]) if policy["release_owned_images"] else set())
            or len(completion["images"]) != len({entry.get("image") for entry in completion["images"]})):
        _fail("Cleanup completion action inventory differs from its immutable intent")
    matches = [entry for entry in intent["cells"] if entry["cell_path"] == str(cell_path)]
    if (len(matches) != 1 or matches[0]["result_reference"] != expected_result_reference
            or (expected_capture_reference is not None and matches[0]["capture_reference"] != expected_capture_reference)):
        _fail("Cleanup completion differs from the cohort result or capture reference")
    for reference in intent["preserved_references"]:
        _checked(reference, decode=False)
    if policy["remove_checkouts"]:
        if any(_path(entry["checkout"]["path"], missing=True).exists() for entry in intent["cells"]):
            _fail("A completed cleanup checkout was recreated")
    registrations = {entry["arm"]: {"cell_path": entry["cell_path"],
        "experiment_reference": policy["experiment_reference"], "result_reference": entry["result_reference"],
        "capture_reference": entry["capture_reference"]} for entry in intent["cells"]}
    if plan_target_cleanup(intent["policy_reference"], task_id, registrations=registrations) != intent:
        _fail("Retained target prerequisites differ from the completed cleanup intent")
    return {**completion, "cleanup_reference": completion_reference,
        "cell": matches[0], "broker_status": _checked(expected_result_reference)["broker_status"]}
