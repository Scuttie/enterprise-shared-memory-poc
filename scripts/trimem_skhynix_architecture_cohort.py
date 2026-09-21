"""Sequential, resumable fixed-cohort execution without outcome-based retries.

This trusted manager delegates to the existing preparation, native-worker and
official-grading APIs. Evidence is retained; an optional separately frozen
cleanup policy delegates removal of completed generated resources. A disk
reserve stops execution before the next preparation.
Started operations are resumed only from specific durable completion evidence.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import trimem_skhynix_architecture_run as execution
from trimem_skhynix_architecture_broker import locked, write
from enterprise_memory.trimem.grader import GraderInvocationFailure

SCHEMA = "skhynix/native-architecture-cohort/1.0"
REVISION_SCHEMA = "skhynix/native-architecture-controller-revision/1.0"
EFFORT_SCHEMA = "skhynix/architecture-reasoning-effort-transition/1.0"
ZERO = "0" * 64
PHASE_ARMS = {"TRAINING": ("PDF_MEMORY",), "EVALUATION": ("BASELINE", "PDF_MEMORY")}
TRAINING_GRADE_HOLD_POLICY = "CAPTURE_KNOWN_TERMINAL_AMBIGUITY_AND_CONTINUE"


class CohortError(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    from enterprise_memory.trimem.accounting import strict_json_loads
    return strict_json_loads(Path(path).read_bytes())


def reference(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise CohortError("artifact reference must be a regular file")
    return {"path": str(path), "sha256": sha(path.read_bytes())}


def verify_reference(reference_value):
    if (not isinstance(reference_value, dict) or set(reference_value) != {"path", "sha256"}
            or not isinstance(reference_value["path"], str) or not Path(reference_value["path"]).is_absolute()
            or reference(reference_value["path"]) != reference_value):
        raise CohortError("frozen cohort artifact reference changed")
    return Path(reference_value["path"])


def checked(reference_value):
    verify_reference(reference_value)
    return read(reference_value["path"])


def _manifest(root):
    value = read(root / "cohort.json")
    if (value.get("schema") != SCHEMA or sha(canonical(value)) !=
            (root / "cohort.sha256").read_text(encoding="ascii").strip()):
        raise CohortError("immutable cohort definition changed")
    return value


def _stamp(path):
    try:
        value = Path(path).lstat()
    except FileNotFoundError:
        return None
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _event_chain(root, cache=None):
    events, previous = [], ZERO
    prior = cache.get("entries", []) if cache is not None else []
    entries = []
    with locked(root / "journal.lock"):
        paths = sorted((root / "events").glob("*.json"))
        if len(paths) < len(prior):
            raise CohortError("immutable cohort event chain changed or was truncated")
        for index, path in enumerate(paths):
            stamp = _stamp(path)
            if index < len(prior) and prior[index][0] == stamp:
                row = prior[index][1]
            else:
                row = read(path)
                if _stamp(path) != stamp or (index < len(prior) and row != prior[index][1]):
                    raise CohortError("immutable cohort event chain changed during observation")
            if path.name != f"{len(events) + 1:08d}.json":
                raise CohortError("cohort event sequence has a gap")
            body = {key: value for key, value in row.items() if key != "sha256"}
            if (row.get("sequence") != len(events) + 1 or row.get("previous_sha256") != previous
                    or row.get("sha256") != sha(canonical(body))):
                raise CohortError("immutable cohort event chain changed")
            events.append(row)
            entries.append((stamp, row))
            previous = row["sha256"]
    if cache is not None:
        cache["entries"] = entries
    return events


def _controller_revisions(root, manifest, events):
    source = manifest["cohort_source_reference"]
    verify_reference(source)
    revisions, previous = [], ZERO
    for path in sorted((root / "controller-revisions").glob("*.json")):
        row = read(path)
        body = {key: value for key, value in row.items() if key != "sha256"}
        count = row.get("event_count")
        if (path.name != f"{len(revisions) + 1:08d}.json" or row.get("schema") != REVISION_SCHEMA or
                row.get("sequence") != len(revisions) + 1 or row.get("previous_sha256") != previous or
                row.get("sha256") != sha(canonical(body)) or row.get("cohort_reference") != reference(root / "cohort.json") or
                row.get("previous_source_reference") != source or type(count) is not int or not 0 <= count <= len(events) or
                row.get("event_tail_sha256") != (events[count - 1]["sha256"] if count else ZERO) or
                row.get("model_calls") != 0 or row.get("official_grader_runs") != 0 or
                row.get("execution_configuration_changed") is not False):
            raise CohortError("controller revision does not bind the immutable cohort and event prefix")
        verify_reference(row["new_source_reference"])
        source, previous = row["new_source_reference"], row["sha256"]
        revisions.append(row)
    return source, revisions


def adopt_controller_revision(root, *, previous_source_reference, new_source_reference, reason):
    """Explicitly bind this controller revision without rewriting cohort/events/cells.

    Invoke from the reviewed frozen new module. The receipt authorizes only its
    controller bytes; preparation, execution, grading and cleanup pins stay fixed.
    """
    root = Path(root).resolve(strict=True)
    if not isinstance(reason, str) or not reason.strip() or len(reason.encode()) > 2000:
        raise CohortError("controller revision requires a bounded explicit reason")
    verify_reference(previous_source_reference)
    verify_reference(new_source_reference)
    if new_source_reference != reference(__file__):
        raise CohortError("new controller reference must identify this exact loaded module")
    with locked(root / "run.lock"):
        manifest, events = _manifest(root), _event_chain(root)
        for key in ("experiment_reference", "dataset_reference", "bank_reference", "cleanup_policy_reference", "cleanup_source_reference"):
            if manifest.get(key) is not None:
                verify_reference(manifest[key])
        active, revisions = _controller_revisions(root, manifest, events)
        if revisions and all(revisions[-1][key] == value for key, value in (
                ("previous_source_reference", previous_source_reference), ("new_source_reference", new_source_reference), ("reason", reason))):
            return reference(root / "controller-revisions" / f"{len(revisions):08d}.json")
        if active != previous_source_reference or active["sha256"] == new_source_reference["sha256"]:
            raise CohortError("controller revision must replace the exact currently active source")
        value = {"schema": REVISION_SCHEMA, "sequence": len(revisions) + 1,
            "previous_sha256": revisions[-1]["sha256"] if revisions else ZERO,
            "cohort_reference": reference(root / "cohort.json"), "previous_source_reference": previous_source_reference,
            "new_source_reference": new_source_reference, "reason": reason,
            "event_count": len(events), "event_tail_sha256": events[-1]["sha256"] if events else ZERO,
            "model_calls": 0, "official_grader_runs": 0, "execution_configuration_changed": False}
        value["sha256"] = sha(canonical(value))
        path = root / "controller-revisions" / f"{value['sequence']:08d}.json"
        if path.exists():
            raise CohortError("refusing to overwrite controller revision evidence")
        write(path, value)
        return reference(path)


def _retain_json(path, value):
    if path.exists():
        if read(path) != value:
            raise CohortError("refusing to replace immutable controller reconciliation evidence")
    else:
        write(path, value)
    return reference(path)


def _effort_partition(manifest, events, config):
    started = {event["ordinal"] for event in events if event["stage"] in {"PREPARE_STARTED", "PREPARED"}}
    ordinals = [row["ordinal"] for row in manifest["schedule"]]
    if not started <= set(ordinals) or sorted(started) != ordinals[:len(started)] or len(started) == len(ordinals):
        raise CohortError("effort transition requires a started prefix and an unstarted remainder")
    future, absent = [], []
    for row in manifest["schedule"]:
        if row["ordinal"] in started:
            continue
        future.append(row["ordinal"])
        task, arm = row["task_id"], row["arm"]
        absent.extend([str(Path(row["cell_config"]).parent),
            str(Path(config["run_root"]) / "workspaces" / arm / task),
            str(Path(config["run_root"]) / "environment" / "TRAINING" / "cells" / arm / task),
            str(Path(config["native_control_root"]) / "TRAINING" / row["target"]["instance_id"] / arm)])
    return sorted(started), future, sorted(absent)


def _validate_effort_payload(root, manifest, events, value, operations):
    fields = {"schema", "operation", "cohort_reference", "previous_experiment_reference", "experiment_reference",
        "previous_learning_enrollment_reference", "learning_enrollment_reference", "previous_cleanup_policy_reference",
        "cleanup_policy_reference", "event_count", "event_tail_reference", "preserved_ultra_ordinals", "high_ordinals",
        "absent_future_paths", "reason", "controller_source_reference", "model_calls", "official_grader_runs", "outcome_retries"}
    count = value.get("event_count")
    if (set(value) != fields or value.get("schema") != EFFORT_SCHEMA or
            value.get("operation") != "ADOPT_FORWARD_REASONING_EFFORT" or manifest["phase"] != "TRAINING" or
            type(count) is not int or not 1 <= count <= len(events) or
            value.get("cohort_reference") != reference(root / "cohort.json") or
            value.get("previous_experiment_reference") != manifest["experiment_reference"] or
            value.get("previous_cleanup_policy_reference") != manifest["cleanup_policy_reference"] or
            value.get("event_tail_reference") != reference(root / "events" / f"{count:08d}.json") or
            not isinstance(value.get("reason"), str) or not value["reason"].strip() or len(value["reason"].encode()) > 2000 or
            value.get("model_calls") != 0 or value.get("official_grader_runs") != 0 or value.get("outcome_retries") is not False):
        raise CohortError("reasoning effort transition does not bind the immutable training boundary")
    _, revisions = _controller_revisions(root, manifest, events)
    # Later controller revisions may follow this transition, but its exact source remains retained.
    verify_reference(value["controller_source_reference"])
    sources = [manifest["cohort_source_reference"]] + [row["new_source_reference"]
        for row in revisions if row["event_count"] <= count]
    if value["controller_source_reference"] not in sources:
        raise CohortError("effort transition controller differs from its enrolled boundary")
    old = checked(value["previous_experiment_reference"])
    new = checked(value["experiment_reference"])
    if old != operations.load_experiment(value["previous_experiment_reference"]["path"]) or new != operations.load_experiment(value["experiment_reference"]["path"]):
        raise CohortError("effort transition execution loader disagrees with retained configurations")
    allowed = {"reasoning_effort", "reasoning_source", "prelaunch_revision"}
    if (old.get("phase") != "TRAINING_RUNTIME" or new.get("phase") != "TRAINING_RUNTIME" or
            old.get("reasoning_effort") != "ultra" or new.get("reasoning_effort") != "high" or
            {key: item for key, item in old.items() if key not in allowed} !=
            {key: item for key, item in new.items() if key not in allowed} or
            not isinstance(new.get("reasoning_source"), str) or not new["reasoning_source"].strip()):
        raise CohortError("effort transition may change only ultra to high and explicit reasoning provenance")
    old_policy, new_policy = checked(value["previous_cleanup_policy_reference"]), checked(value["cleanup_policy_reference"])
    if (old_policy.get("experiment_reference") != value["previous_experiment_reference"] or
            new_policy != {**old_policy, "experiment_reference": value["experiment_reference"]}):
        raise CohortError("effort transition cleanup policy changes more than its execution binding")
    old_learning = reference(Path(manifest["learning_root"]) / "learning-enrollment.json")
    enrollment = checked(value["learning_enrollment_reference"])
    if (value["previous_learning_enrollment_reference"] != old_learning or
            Path(value["learning_enrollment_reference"]["path"]).name != "learning-enrollment.json" or
            Path(value["learning_enrollment_reference"]["path"]).parent == Path(old_learning["path"]).parent or
            checked(old_learning).get("learning_version") != 2 or
            checked(old_learning).get("execution_references") != [value["previous_experiment_reference"]] or
            enrollment != {**checked(old_learning), "execution_references":
                [value["previous_experiment_reference"], value["experiment_reference"]]}):
        raise CohortError("effort transition requires a new learning authority over both unchanged training sources")
    started, future, absent = _effort_partition(manifest, events[:count], old)
    if (value["preserved_ultra_ordinals"] != started or value["high_ordinals"] != future or value["absent_future_paths"] != absent):
        raise CohortError("effort transition changes the exact started ultra and future high partition")
    for row in manifest["schedule"]:
        path = Path(row["cell_config"])
        if not path.is_file():
            continue
        cell = read(path)
        expected = value["previous_experiment_reference"] if row["ordinal"] in started else value["experiment_reference"]
        if (cell.get("experiment_config") != expected["path"] or
                sha(canonical(cell)) != path.with_suffix(".sha256").read_text().strip()):
            raise CohortError("existing cell configuration violates the preserved ultra and future high boundary")
        prepared = next((event for event in events[:count] if event["ordinal"] == row["ordinal"] and event["stage"] == "PREPARED"), None)
        if prepared is not None and prepared["details"]["cell_reference"] != reference(path):
            raise CohortError("preserved prepared ultra cell differs from its original journal reference")
    return value


def validate_reasoning_effort_transition(root, transition_reference=None, *, operations=execution):
    """Validate the retained forward boundary; this never launches or retries work."""
    root = Path(root).resolve(strict=True)
    path, marker = root / "reasoning-effort-transition.json", root / "reasoning-effort-transition.ref.json"
    if path.is_symlink() or marker.is_symlink():
        raise CohortError("reasoning effort transition receipt path is redirected")
    if not path.exists() and not marker.exists() and transition_reference is None:
        return None
    retained = read(marker)
    if (retained != reference(path) or transition_reference is not None and retained != transition_reference):
        raise CohortError("reasoning effort transition reference differs")
    return _validate_effort_payload(root, _manifest(root), _event_chain(root), checked(retained), operations)


def adopt_reasoning_effort_transition(root, *, expected_event_tail_reference, high_experiment_reference,
        high_cleanup_policy_reference, learning_enrollment_reference, reason, operations=execution):
    """Enroll one explicit ultra-to-high boundary without changing prior cell evidence."""
    root = Path(root).resolve(strict=True)
    with locked(root / "run.lock"):
        manifest, events = _manifest(root), _event_chain(root)
        if not events or expected_event_tail_reference != reference(root / "events" / f"{len(events):08d}.json"):
            raise CohortError("cohort journal advanced after the requested effort boundary")
        source, _ = _controller_revisions(root, manifest, events)
        if source != reference(__file__):
            raise CohortError("adopt the reviewed controller before its reasoning effort transition")
        old = checked(manifest["experiment_reference"])
        started, future, absent = _effort_partition(manifest, events, old)
        value = {"schema": EFFORT_SCHEMA, "operation": "ADOPT_FORWARD_REASONING_EFFORT",
            "cohort_reference": reference(root / "cohort.json"), "previous_experiment_reference": manifest["experiment_reference"],
            "experiment_reference": high_experiment_reference, "previous_cleanup_policy_reference": manifest["cleanup_policy_reference"],
            "cleanup_policy_reference": high_cleanup_policy_reference,
            "previous_learning_enrollment_reference": reference(Path(manifest["learning_root"]) / "learning-enrollment.json"),
            "learning_enrollment_reference": learning_enrollment_reference, "event_count": len(events),
            "event_tail_reference": expected_event_tail_reference, "preserved_ultra_ordinals": started,
            "high_ordinals": future, "absent_future_paths": absent, "reason": reason,
            "controller_source_reference": source, "model_calls": 0, "official_grader_runs": 0, "outcome_retries": False}
        _validate_effort_payload(root, manifest, events, value, operations)
        path = root / "reasoning-effort-transition.json"
        if path.exists():
            if checked(reference(path)) != value:
                raise CohortError("refusing to replace a frozen reasoning effort transition")
        else:
            if any(Path(item).exists() or Path(item).is_symlink() for item in absent):
                raise CohortError("future high cell already has preparation, workspace, or native artifacts")
            write(path, value)
        result = reference(path)
        _retain_json(root / "reasoning-effort-transition.ref.json", result)
        return result


def _inspect_absent_owned_image(image):
    """Only an explicit missing-object daemon response proves digest absence."""
    argv = ["docker", "image", "inspect", image]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    missing = {f"Error response from daemon: No such {kind}: {image}" for kind in ("image", "object")}
    if result.returncode != 1 or result.stdout.strip() not in {"", "[]"} or result.stderr.strip() not in missing:
        return None
    proof = {"argv": argv, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
        "stdout_sha256": sha(result.stdout.encode()), "stderr_sha256": sha(result.stderr.encode())}
    return {**proof, "evidence_sha256": sha(canonical(proof))}


def _validate_reconciliation(completion):
    if "reconciliation_reference" not in completion:
        return
    receipt = checked(completion["reconciliation_reference"])
    intent = checked(completion["intent_reference"])
    failed = checked(receipt["failed_attempt_reference"])
    verify_reference(receipt["controller_source_reference"])
    if (receipt.get("schema") != "skhynix/architecture-cleanup-absence-reconciliation/1.0" or
            receipt.get("operation") != "RECONCILE_ABSENT_OWNED_IMAGES" or
            receipt.get("intent_reference") != completion["intent_reference"] or
            receipt.get("task_id") != completion["task_id"] or receipt.get("phase") != completion["phase"] or
            any(receipt.get(key) != 0 for key in ("delete_operations", "model_calls", "official_grader_runs")) or
            failed.get("status") != "INCOMPLETE_IMAGE_RELEASE" or failed.get("intent_reference") != completion["intent_reference"] or
            len(receipt["images"]) != len(intent["owned_images"]) or
            {item["image"] for item in receipt["images"]} != set(intent["owned_images"])):
        raise CohortError("cleanup reconciliation differs from its owned-image intent and failed attempt")
    _validate_absence_proofs(receipt["images"], set(intent["owned_images"]))


def _validate_absence_proofs(images, expected):
    if len(images) != len(expected) or {item["image"] for item in images} != expected:
        raise CohortError("owned-image absence evidence inventory differs")
    for item in images:
        image, proof = item["image"], item["inspect"]
        body = {key: value for key, value in proof.items() if key != "evidence_sha256"}
        missing = {f"Error response from daemon: No such {kind}: {image}" for kind in ("image", "object")}
        if (item.get("absent") is not True or proof.get("argv") != ["docker", "image", "inspect", image] or
                proof.get("returncode") != 1 or proof["stdout"].strip() not in {"", "[]"} or proof["stderr"].strip() not in missing or
                proof["stdout_sha256"] != sha(proof["stdout"].encode()) or proof["stderr_sha256"] != sha(proof["stderr"].encode()) or
                proof.get("evidence_sha256") != sha(canonical(body))):
            raise CohortError("cleanup reconciliation lacks exact immutable Docker absence evidence")


def _image_postcondition(completion, folder, *, required=False):
    images = {item["image"] for item in completion.get("images", [])}
    if not images:
        return True
    path = folder / "owned-image-postcondition.json"
    if not path.is_file():
        if required:
            raise CohortError("cleanup image removal lacks exact daemon absence postconditions")
        return False
    receipt = read(path)
    if (receipt.get("schema") != "skhynix/architecture-owned-image-postcondition/1.0" or
            receipt.get("completion_reference") != reference(folder / "completion.json") or
            receipt.get("intent_reference") != completion["intent_reference"] or
            any(receipt.get(key) != 0 for key in ("delete_operations", "model_calls", "official_grader_runs"))):
        raise CohortError("owned-image postcondition differs from its immutable completion")
    verify_reference(receipt["controller_source_reference"])
    _validate_absence_proofs(receipt["images"], images)
    return True


def _safe(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,256}", value):
        raise CohortError("invalid frozen target identifier")
    return value


def _descriptor(target):
    return {"task_id": target["target_id"], "repository": target["repository"],
            "commit": target["base_commit"], "instruction_sha256": target["instruction_sha256"]}


def available_storage_bytes(path):
    """WSL's sparse virtual disk must also fit on its physical Windows drive."""
    locations = [Path(path)]
    if Path("/mnt/c").is_dir():
        locations.append(Path("/mnt/c"))
    return min(shutil.disk_usage(location).free for location in locations)


def validate_evaluation_bank(bank_reference, dataset, config):
    """Validate real authority, enrollment and positive L1/L2/KG/L3 contents."""
    from trimem_skhynix_architecture_memory import load_frozen_bank
    bank = load_frozen_bank(bank_reference["path"], bank_reference["sha256"])
    try:
        manifest = bank.manifest
        if manifest["scope"]["org_id"] != config["org_id"]:
            raise CohortError("evaluation bank organisation differs")
        for role, key in (("TRAINING", "training_tasks"), ("EVALUATION", "evaluation_tasks")):
            expected = {_descriptor(row)["task_id"]: _descriptor(row) for row in dataset["targets"] if row["role"] == role}
            actual = {row["task_id"]: row for row in manifest["scope"][key]}
            if actual != expected:
                raise CohortError("frozen bank enrollment differs from the fixed cohort")
        if any(type(value) is not int or value <= 0 for value in manifest["layer_counts"].values()):
            raise CohortError("full architecture evaluation requires populated L1, L2 nodes/edges and verified L3")
        return manifest["layer_counts"]
    finally:
        bank.close()


def _scale_scope(config, dataset):
    if config.get("scale_authority_reference") is None and dataset.get("schema") != "skhynix/pdf-architecture-scale-dataset/1.0":
        return None
    return execution.execution_enrollment(config, dataset)


class CohortRunner:
    def __init__(self, root, *, operations=execution, learning_hook: Callable | None = None,
                 quarantine_hook: Callable | None = None, cleanup_operations=None,
                 disk_free: Callable | None = None, clock=time.time):
        self.root = Path(root).resolve()
        self.operations, self.clock = operations, clock
        self.learning_hook, self.quarantine_hook = learning_hook, quarantine_hook
        self.cleanup_operations = cleanup_operations
        self.disk_free = disk_free or available_storage_bytes
        self._journal_cache, self._journal_depth = {}, 0
        self._journal_events, self._events_by_ordinal = None, {}
        self._terminal_cache, self._authority_token, self._terminal_audit_tail = {}, None, None
        self.manifest = _manifest(self.root)
        self._check_controller_source()
        self.config = self.operations.load_experiment(self.manifest["experiment_reference"]["path"])
        self._check_training_grade_policy(self.config, self.manifest["phase"])
        self._transition, self._high_config, self._transition_hook = None, None, None
        self._refresh_effort_transition()
        self._check_execution_api()
        checked(self.manifest["experiment_reference"])
        self.dataset = checked(self.manifest["dataset_reference"])
        self.scale_scope = _scale_scope(self.config, self.dataset)
        if self.manifest.get("scale_authority_reference") != self.config.get("scale_authority_reference"):
            raise CohortError("cohort scale authority differs from its frozen execution")
        if self.scale_scope is not None:
            if (self.manifest["arms"] != self.scale_scope["arms"] or
                    list(dict.fromkeys(row["task_id"] for row in self.manifest["schedule"])) != self.scale_scope["task_ids"] or
                    self.manifest["bank_reference"] != self.scale_scope["bank_reference"]):
                raise CohortError("cohort schedule, arms, or bank differs from its explicit scale authority")
        if self.manifest["bank_reference"] is not None:
            checked(self.manifest["bank_reference"])
        if self.manifest["cleanup_policy_reference"] is not None:
            checked(self.manifest["cleanup_policy_reference"])
            if self.cleanup_operations is None:
                import trimem_skhynix_architecture_cleanup
                self.cleanup_operations = trimem_skhynix_architecture_cleanup
            if self.manifest["cleanup_source_reference"] is not None:
                verify_reference(self.manifest["cleanup_source_reference"])
                if reference(self.cleanup_operations.__file__) != self.manifest["cleanup_source_reference"]:
                    raise CohortError("cleanup implementation differs from the frozen cohort helper")
        for item in self.manifest["outside_cohort"]:
            self._validate_outside(item)
        self.schedule = self.manifest["schedule"]

    def _refresh_effort_transition(self):
        value = validate_reasoning_effort_transition(self.root, operations=self.operations)
        if self._transition is not None and value != self._transition:
            raise CohortError("frozen reasoning effort transition changed")
        if value != self._transition:
            self._transition_hook = None
        self._transition = value
        self._high_config = checked(value["experiment_reference"]) if value is not None else None

    @property
    def reasoning_effort_transition_reference(self):
        return reference(self.root / "reasoning-effort-transition.json") if self._transition is not None else None

    @property
    def active_learning_root(self):
        return (str(Path(self._transition["learning_enrollment_reference"]["path"]).parent)
            if self._transition is not None else self.manifest["learning_root"])

    def _row_experiment_reference(self, row):
        if self._transition is not None and row["ordinal"] in self._transition["high_ordinals"]:
            return self._transition["experiment_reference"]
        return self.manifest["experiment_reference"]

    def _row_config(self, row):
        return self._high_config if self._row_experiment_reference(row) != self.manifest["experiment_reference"] else self.config

    def _row_cleanup_policy_reference(self, row):
        if self._row_experiment_reference(row) != self.manifest["experiment_reference"]:
            return self._transition["cleanup_policy_reference"]
        return self.manifest["cleanup_policy_reference"]

    @staticmethod
    def _check_training_grade_policy(config, phase):
        policy = config.get("training_grade_hold_policy")
        if policy is not None and (policy != TRAINING_GRADE_HOLD_POLICY or phase != "TRAINING"
                or config.get("phase") != "TRAINING_RUNTIME"):
            raise CohortError("terminal ambiguous grade continuation is explicitly training-only")

    def _training_grade_hold_enabled(self, row):
        return (self.manifest["phase"] == "TRAINING" and self.manifest["capture_enabled"]
            and self._row_config(row).get("training_grade_hold_policy") == TRAINING_GRADE_HOLD_POLICY)

    def _check_controller_source(self, events=None):
        if _manifest(self.root) != self.manifest:
            raise CohortError("immutable cohort definition changed")
        active, revisions = _controller_revisions(self.root, self.manifest, self._events() if events is None else events)
        if reference(__file__)["sha256"] != active["sha256"]:
            raise CohortError("loaded controller differs; explicitly adopt its reviewed controller revision")
        return active, revisions

    def _check_execution_api(self):
        module_path = getattr(self.operations, "__file__", None)
        if module_path is not None:
            expected = self.config["source_sha256"].get("scripts/trimem_skhynix_architecture_run.py")
            if expected is None or sha(Path(module_path).read_bytes()) != expected:
                raise CohortError("imported execution API differs from the frozen runtime source")

    @classmethod
    def create(cls, root, *, experiment_path, phase, target_ids=None, bank_reference=None,
               learning_root=None, quarantine_root=None, adopt_existing=(), outside_cohort=(),
               cleanup_policy_reference=None, cleanup_operations=None,
               min_free_bytes=10 * 1024**3, operations=execution, bank_validator=validate_evaluation_bank,
               learning_hook=None, quarantine_hook=None, disk_free=None, clock=time.time):
        root = Path(root).resolve()
        if root.exists():
            raise CohortError("refusing to overwrite an existing cohort")
        if phase not in PHASE_ARMS or type(min_free_bytes) is not int or min_free_bytes < 0:
            raise CohortError("invalid phase or disk reserve")
        config = operations.load_experiment(experiment_path)
        cls._check_training_grade_policy(config, phase)
        if config.get("phase") != phase + "_RUNTIME":
            raise CohortError("execution configuration phase differs from the requested cohort")
        if phase == "EVALUATION" and config.get("evaluation_status") != "EVALUATION_READY":
            raise CohortError("evaluation configuration has not been frozen as EVALUATION_READY")
        dataset = checked(config["dataset_manifest"])
        scale_scope = _scale_scope(config, dataset)
        if scale_scope is None and (dataset.get("training_count") != 24 or dataset.get("evaluation_count") != 500
                or len([row for row in dataset["targets"] if row["role"] == "TRAINING"]) != 24
                or len([row for row in dataset["targets"] if row["role"] == "EVALUATION"]) != 500):
            raise CohortError("cohort requires the fixed 24 training and 500 evaluation enrollment")
        all_targets = dataset["targets"]
        if len({row["target_id"] for row in all_targets}) != len(all_targets):
            raise CohortError("dataset contains duplicate target identities")
        full = sorted((row for row in all_targets if row["role"] == phase), key=lambda row: row["order_index"])
        for row in full:
            _safe(row["target_id"])
        arms = PHASE_ARMS[phase] if scale_scope is None else tuple(scale_scope["arms"])
        if scale_scope is not None:
            if target_ids is not None and list(target_ids) != scale_scope["task_ids"]:
                raise CohortError("scale cohort requires the entire exact authorized task subset")
            by_id = {row["target_id"]: row for row in full}
            if not set(scale_scope["task_ids"]) <= set(by_id):
                raise CohortError("scale authority tasks differ from the requested runtime phase")
            selected = [by_id[identity] for identity in scale_scope["task_ids"]]
            if bank_reference != scale_scope["bank_reference"]:
                raise CohortError("scale cohort bank differs from its authorized frozen candidate")
        elif target_ids is None:
            selected = full
        else:
            if (not isinstance(target_ids, (tuple, list)) or not target_ids
                    or len(set(target_ids)) != len(target_ids)
                    or not set(target_ids) <= {row["target_id"] for row in full}):
                raise CohortError("commissioning subset must contain unique predeclared phase targets")
            selected = [row for row in full if row["target_id"] in target_ids]
        if phase == "TRAINING" and bank_reference is not None:
            raise CohortError("training cohort must start before the frozen evaluation bank")
        if phase == "TRAINING" and (quarantine_root is not None or quarantine_hook is not None):
            raise CohortError("evaluation quarantine cannot be used for training capture")
        if phase == "EVALUATION":
            baseline_development = scale_scope is not None and scale_scope["purpose"] == "DEVELOPMENT_BASELINE"
            if bank_reference is None and not baseline_development:
                raise CohortError("evaluation requires a frozen trained memory bank")
            if bank_reference is not None:
                checked(bank_reference)
                layer_counts = bank_validator(bank_reference, dataset, config)
            else:
                layer_counts = None
            if learning_root is not None or learning_hook is not None:
                raise CohortError("evaluation cannot update the frozen training memory")
        else:
            layer_counts = None
        cleanup_source_reference = None
        capture_enabled = any(value is not None for value in (learning_root, learning_hook, quarantine_root, quarantine_hook))
        if cleanup_policy_reference is not None:
            policy = checked(cleanup_policy_reference)
            if policy["experiment_reference"] != reference(experiment_path):
                raise CohortError("cleanup policy differs from the frozen execution configuration")
            if not capture_enabled:
                raise CohortError("cleanup requires configured post-grade capture evidence")
            if cleanup_operations is None:
                import trimem_skhynix_architecture_cleanup
                cleanup_operations = trimem_skhynix_architecture_cleanup
            if getattr(cleanup_operations, "__file__", None):
                cleanup_source_reference = reference(cleanup_operations.__file__)
        run_root = Path(config["run_root"]).resolve()
        schedule = []
        for target in selected:
            for arm in arms:
                cell_root = (run_root / "cells" / phase / target["target_id"] / arm).resolve()
                if run_root not in cell_root.parents:
                    raise CohortError("cell directory escaped the frozen run root")
                schedule.append({"ordinal": len(schedule) + 1, "task_id": target["target_id"],
                    "arm": arm, "target": target, "cell_config": str(cell_root / "cell.json")})
        adoption = [reference(path) for path in adopt_existing]
        if len({item["path"] for item in adoption}) != len(adoption) or not {item["path"] for item in adoption} <= {row["cell_config"] for row in schedule}:
            raise CohortError("adopted cells must be unique exact scheduled cell paths")
        exclusions = [reference(path) for path in outside_cohort]
        manifest = {"schema": SCHEMA, "phase": phase,
            "cohort_source_reference": reference(__file__),
            "scope": "FULL_AUTHORIZED_SCALE_COHORT" if scale_scope is not None else "FULL_FIXED_COHORT" if target_ids is None else "PREDECLARED_COMMISSIONING_SUBSET",
            "experiment_reference": reference(experiment_path), "dataset_reference": config["dataset_manifest"],
            "bank_reference": bank_reference, "bank_layer_counts_at_enrollment": layer_counts,
            "full_phase_task_count": len(full), "selected_task_count": len(selected),
            "arms": list(arms), "schedule": schedule,
            "arm_order": "BASELINE_THEN_PDF_MEMORY_PER_EVALUATION_TASK",
            "outcome_retries": False, "adopted_existing_cells": adoption, "outside_cohort": exclusions,
            "learning_root": str(Path(learning_root).resolve()) if learning_root is not None else None,
            "learning_enabled": learning_root is not None or learning_hook is not None,
            "quarantine_root": str(Path(quarantine_root).resolve()) if quarantine_root is not None else None,
            "capture_enabled": capture_enabled,
            "capture_mode": "TRAINING_MEMORY" if phase == "TRAINING" else "SEPARATE_EVALUATION_QUARANTINE",
            "cleanup_policy_reference": cleanup_policy_reference,
            "cleanup_source_reference": cleanup_source_reference,
            "min_free_bytes": min_free_bytes,
            "cleanup_policy": "EXPLICIT_COMPLETED_TARGET_POLICY" if cleanup_policy_reference else "NONE_RETAIN_ALL_CHECKOUTS_PATCHES_EVENTS_RESULTS",
            "created_at": clock()}
        if scale_scope is not None:
            manifest.update(scale_authority_reference=config["scale_authority_reference"], scale_purpose=scale_scope["purpose"],
                cumulative_training_count=scale_scope["cumulative_training_count"],
                adopted_training_source_count=len(scale_scope["adopted_source_task_ids"]))
        # Validate exclusions before creating the immutable cohort directory.
        for item in exclusions:
            cls._validate_outside_static(item, schedule)
        root.mkdir(parents=True)
        write(root / "cohort.json", manifest)
        (root / "cohort.sha256").write_text(sha(canonical(manifest)) + "\n", encoding="ascii")
        (root / "events").mkdir()
        runner = cls(root, operations=operations, learning_hook=learning_hook, quarantine_hook=quarantine_hook,
            cleanup_operations=cleanup_operations, disk_free=disk_free, clock=clock)
        for item in adoption:
            row = next(row for row in schedule if row["cell_config"] == item["path"])
            runner._validate_cell(row)
            runner._record("PREPARED", row, {"cell_reference": item, "adopted_existing": True})
        return runner

    @staticmethod
    def _validate_outside_static(item, schedule):
        receipt = checked(item)
        if (receipt.get("schema") != "skhynix/architecture-outside-cohort/1.0"
                or receipt.get("classification") != "PREFLIGHT_ABORTED_ZERO_ACTION"
                or type(receipt.get("actions")) is not int or receipt["actions"] != 0
                or not isinstance(receipt.get("reason"), str) or not receipt["reason"].strip()):
            raise CohortError("outside-cohort trial requires an explicit zero-action preflight receipt")
        cell_root = Path(receipt["cell_root"]).resolve(strict=True)
        state = read(cell_root / "broker" / "state.json")
        if type(state.get("actions")) is not int or state["actions"] != 0:
            raise CohortError("outside-cohort trial contains actual solver actions")
        if cell_root in {Path(row["cell_config"]).parent for row in schedule}:
            raise CohortError("outside-cohort trial cannot reuse a scheduled cell directory")

    def _validate_outside(self, item):
        self._validate_outside_static(item, self.manifest["schedule"])

    def _events(self):
        if self._journal_depth:
            return self._journal_events
        return deepcopy(_event_chain(self.root, self._journal_cache))

    @contextmanager
    def _journal_snapshot(self):
        if self._journal_depth:
            self._journal_depth += 1
            try:
                yield
            finally:
                self._journal_depth -= 1
            return
        self._journal_events = _event_chain(self.root, self._journal_cache)
        self._events_by_ordinal = {}
        for event in self._journal_events:
            self._events_by_ordinal.setdefault(event["ordinal"], []).append(event)
        self._journal_depth = 1
        try:
            token = self._authority_stamps()
            if token != self._authority_token:
                self._terminal_cache.clear()
                self._terminal_audit_tail = None
                if self.operations.load_experiment(self.manifest["experiment_reference"]["path"]) != self.config:
                    raise CohortError("frozen execution configuration changed")
                self._refresh_effort_transition()
                if _scale_scope(self.config, self.dataset) != self.scale_scope:
                    raise CohortError("frozen scale execution enrollment changed")
                token = self._authority_stamps()
            self._authority_token = token
            yield
        finally:
            self._journal_depth = 0
            self._journal_events = None
            self._events_by_ordinal = {}

    def _authority_stamps(self):
        paths = {self.root / "cohort.json", self.root / "cohort.sha256", Path(__file__)}
        paths.update(self.root / name for name in ("reasoning-effort-transition.json", "reasoning-effort-transition.ref.json"))
        if self._transition is not None:
            for key, value in self._transition.items():
                if key.endswith("_reference"):
                    paths.add(Path(value["path"]))
            paths.add(Path(self._transition["experiment_reference"]["path"]).with_suffix(".sha256"))
        if self.scale_scope is not None:
            paths.add(Path(self.config["scale_authority_reference"]["path"]))
            def refs(value):
                if isinstance(value, dict):
                    if set(value) == {"path", "sha256"}:
                        paths.add(Path(value["path"]))
                    else:
                        for item in value.values():
                            refs(item)
                elif isinstance(value, list):
                    for item in value:
                        refs(item)
            refs(self.dataset)
            refs(self.scale_scope)
            if self.scale_scope["source_adoption_reference"] is not None:
                refs(checked(self.scale_scope["source_adoption_reference"]))
        for key in ("experiment_reference", "dataset_reference", "bank_reference", "cohort_source_reference", "cleanup_policy_reference", "cleanup_source_reference"):
            if self.manifest.get(key) is not None:
                paths.add(Path(self.manifest[key]["path"]))
        for key in ("dataset_manifest", "image_index"):
            if self.config.get(key):
                paths.add(Path(self.config[key]["path"]))
        if self.config.get("loader_preflight_path"):
            paths.add(Path(self.config["loader_preflight_path"]))
        paths.add(Path(self.manifest["experiment_reference"]["path"]).with_suffix(".sha256"))
        if self.config.get("source_root"):
            paths.update(Path(self.config["source_root"]) / name for name in self.config.get("source_sha256", {}))
        paths.update((self.root / "controller-revisions").glob("*.json"))
        return tuple((str(path), _stamp(path)) for path in sorted(paths))

    def _record(self, stage, row, details):
        events = self._events()
        event = {"sequence": len(events) + 1, "previous_sha256": events[-1]["sha256"] if events else ZERO,
            "stage": stage, "ordinal": row["ordinal"] if row is not None else None,
            "task_id": row["task_id"] if row is not None else None,
            "arm": row["arm"] if row is not None else None, "at": self.clock(), "details": details}
        event["sha256"] = sha(canonical(event))
        with locked(self.root / "journal.lock"):
            path = self.root / "events" / f"{event['sequence']:08d}.json"
            if path.exists():
                raise CohortError("cohort event writer conflict")
            write(path, event)
            if self._journal_depth:
                self._journal_events.append(event)
                self._events_by_ordinal.setdefault(event["ordinal"], []).append(event)
                self._journal_cache["entries"].append((_stamp(path), event))
                self._terminal_audit_tail = None
        return event

    def _cell_events(self, row):
        if self._journal_depth:
            return self._events_by_ordinal.get(row["ordinal"], [])
        return [event for event in self._events() if event["ordinal"] == row["ordinal"]]

    def _validate_cell(self, row):
        path = Path(row["cell_config"])
        cell = read(path)
        if sha(canonical(cell)) != path.with_suffix(".sha256").read_text(encoding="ascii").strip():
            raise CohortError("cell configuration checksum differs")
        task, target = cell["task_public"], row["target"]
        if (cell["phase"] != self.manifest["phase"] or cell["arm"] != row["arm"]
                or Path(cell["experiment_config"]).resolve() != Path(self._row_experiment_reference(row)["path"])
                or task["task_id"] != row["task_id"] or task["repository"] != target["repository"]
                or task["commit"] != target["base_commit"]
                or sha(task["instruction"].strip().encode()) != target["instruction_sha256"]
                or cell["bank_reference"] != self.manifest["bank_reference"]
                or cell["bank_sha256"] != (self.manifest["bank_reference"]["sha256"]
                    if self.manifest["bank_reference"] is not None else execution.EMPTY_BANK_SHA)):
            raise CohortError("cell identity, phase, public issue, or bank differs from enrollment")
        return cell

    def _terminal_paths(self, row):
        if self.manifest["cleanup_policy_reference"] is None:
            return None
        stages = {event["stage"] for event in self._cell_events(row)}
        if not {"CELL_COMPLETE", "CLEANED"} <= stages:
            return None
        folder = Path(self.config["run_root"]) / "cleanup" / row["task_id"]
        if not (folder / "completion.ref.json").is_file() or not (folder / "intent.json").is_file():
            return None
        if not _image_postcondition(read(folder / "completion.json"), folder):
            return None
        intent = read(folder / "intent.json")
        paths = {Path(ref["path"]) for ref in intent["preserved_references"]}
        paths.update(Path(entry["checkout"]["path"]) for entry in intent["cells"])
        roots = {folder}
        for entry in intent["cells"]:
            cell_path = Path(entry["cell_path"])
            cell = read(cell_path)
            roots.add(cell_path.parent)
            if cell.get("prepared_output_root"):
                roots.add(Path(cell["prepared_output_root"]))
            target = next(item["target"] for item in self.schedule if item["task_id"] == entry["task_id"] and item["arm"] == entry["arm"])
            roots.add(Path(self.config["native_control_root"]) / entry["phase"] / target["instance_id"] / entry["arm"])
        for root in roots:
            paths.add(root)
            paths.update(root.rglob("*"))
        for event in self._cell_events(row):
            for value in event["details"].values():
                if isinstance(value, dict) and set(value) == {"path", "sha256"}:
                    paths.add(Path(value["path"]))
        return tuple(sorted(str(path) for path in paths))

    def _cached_terminal(self, row):
        cached = self._terminal_cache.get(row["ordinal"])
        if cached is None:
            return None
        if (cached["event_hashes"] != tuple(event["sha256"] for event in self._cell_events(row)) or
                cached["stamps"] != tuple(_stamp(path) for path in cached["paths"])):
            self._terminal_cache.pop(row["ordinal"], None)
            self._terminal_audit_tail = None
            return None
        return deepcopy(cached["result"])

    def _validate_result(self, row, *, full_audit=False):
        if not full_audit:
            cached = self._cached_terminal(row)
            if cached is not None:
                return cached
        paths = self._terminal_paths(row)
        before = tuple(_stamp(path) for path in paths) if paths is not None else None
        result = self._validate_result_uncached(row)
        if paths is not None:
            if before != tuple(_stamp(path) for path in paths) or self._authority_stamps() != self._authority_token:
                raise CohortError("retained terminal evidence changed during full validation")
            self._terminal_cache[row["ordinal"]] = {"paths": paths, "stamps": before,
                "event_hashes": tuple(event["sha256"] for event in self._cell_events(row)), "result": deepcopy(result)}
        return result

    def _validate_result_uncached(self, row):
        cell = self._validate_cell(row)
        path = Path(row["cell_config"]).parent / "public-result.json"
        undetermined = Path(row["cell_config"]).parent / "training-grade-undetermined.json"
        if undetermined.exists():
            if not self._training_grade_hold_enabled(row) or path.exists():
                raise CohortError("unscored training outcome conflicts with official result or policy")
            outcome = self.operations.training_grade_undetermined(Path(row["cell_config"]), create=False)
            if outcome is None or outcome[1] != reference(undetermined):
                raise CohortError("unscored training outcome lacks its immutable terminal evidence")
            result, _ = outcome
            path = undetermined
        else:
            result = read(path)
        required = {"task_id", "arm", "phase", "official", "resolved", "grader_status", "patch_sha256",
                    "event_tail_sha256", "experiment_sha256", "bank_sha256", "broker_status", "execution_audit_sha256"}
        if not required <= set(result):
            raise CohortError("public result is missing official completion fields")
        if (result["task_id"] != row["task_id"] or result["arm"] != row["arm"]
                or result["phase"] != self.manifest["phase"]
                or (path == undetermined and (result["official"] is not False or result["resolved"] is not None
                    or result["grader_status"] != "undetermined" or result.get("official_outcome") != "UNDETERMINED"))
                or (path != undetermined and (result["official"] is not True
                    or result["grader_status"] != "success" or type(result["resolved"]) is not bool))
                or result["experiment_sha256"] != sha(canonical(self._row_config(row)))
                or result["bank_sha256"] != cell["bank_sha256"]):
            raise CohortError("result is not an official completed grade for the enrolled cell")
        cleanup_folder = Path(self.config["run_root"]) / "cleanup" / row["task_id"]
        cleaned = (cleanup_folder / "completion.ref.json").is_file()
        retained_cleanup = cleaned or (cleanup_folder / "intent.json").is_file()
        if retained_cleanup:
            if self.manifest["cleanup_policy_reference"] is None:
                raise CohortError("cell was cleaned outside the cohort's frozen cleanup policy")
            captured = next((event for event in self._cell_events(row) if event["stage"] == "LEARNED"), None)
            if captured is None:
                raise CohortError("cleaned cell has no cohort capture receipt")
            if cleaned:
                cleanup = self.cleanup_operations.validate_completed_cleanup(Path(row["cell_config"]),
                    reference(path), captured["details"]["capture_reference"])
                _validate_reconciliation(cleanup)
                _image_postcondition(cleanup, cleanup_folder)
                status = cleanup["broker_status"]
            else:
                status = self._pending_cleanup_status(row, reference(path))
        else:
            status = self._broker_status(Path(row["cell_config"]))
        patch = Path(cell["broker_root"]) / "submission.diff"
        recorded = result["broker_status"]
        if (status["status"] != "SUBMITTED" or recorded["status"] != "SUBMITTED"
                or recorded["submission"] != status["submission"]
                or recorded["budget"]["requests_used"] != status["budget"]["requests_used"]
                or result["event_tail_sha256"] != status["event_tail_sha256"]
                or result["patch_sha256"] != sha(patch.read_bytes())):
            raise CohortError("official result no longer matches the sealed patch and broker events")
        if not retained_cleanup:
            self.operations.execution_audit(Path(row["cell_config"]))
        audit_path = path.parent / "execution-audit.json"
        audit = read(audit_path)
        if (sha(audit_path.read_bytes()) != result["execution_audit_sha256"] or audit.get("passed") is not True
                or audit.get("errors") != [] or audit["event_tail_sha256"] != result["event_tail_sha256"]
                or audit["patch_sha256"] != result["patch_sha256"]):
            raise CohortError("official result does not have a matching successful native execution audit")
        return result, reference(path)

    def _pending_cleanup_status(self, row, result_reference):
        """Revalidate immutable intent after partial removal, without retrying cleanup."""
        policy_reference = self._row_cleanup_policy_reference(row)
        checked(policy_reference)
        if self.manifest["cleanup_source_reference"] is not None:
            verify_reference(self.manifest["cleanup_source_reference"])
            if reference(self.cleanup_operations.__file__) != self.manifest["cleanup_source_reference"]:
                raise CohortError("cleanup implementation differs from the frozen cohort helper")
        folder = Path(self.config["run_root"]) / "cleanup" / row["task_id"]
        if folder.resolve() != folder:
            raise CohortError("pending cleanup directory is redirected outside its canonical path")
        intent = read(folder / "intent.json")
        if (intent.get("status") != "VALIDATED_CLEANUP_INTENT" or intent.get("policy_reference") != policy_reference
                or intent.get("task_id") != row["task_id"] or intent.get("phase") != self.manifest["phase"]
                or intent.get("run_root") != self.config["run_root"]):
            raise CohortError("pending cleanup intent differs from the frozen cohort policy")
        registrations = {}
        for arm in self.manifest["arms"]:
            enrolled = next((item for item in self.schedule if item["task_id"] == row["task_id"] and item["arm"] == arm), None)
            if enrolled is None:
                raise CohortError("pending cleanup includes an unenrolled target arm")
            events = self._cell_events(enrolled)
            graded = next((event for event in events if event["stage"] in {"GRADED", "GRADE_UNDETERMINED"}), None)
            captured = next((event for event in events if event["stage"] == "LEARNED"), None)
            if graded is None or captured is None or not any(event["stage"] == "CELL_COMPLETE" for event in events):
                raise CohortError("pending cleanup requires every arm's completed grade and capture")
            checked(graded["details"]["result_reference"])
            checked(captured["details"]["mirror_reference"])
            capture_reference, _ = self._capture_receipt(enrolled, Path(captured["details"]["mirror_reference"]["path"]))
            if capture_reference != captured["details"]["capture_reference"]:
                raise CohortError("pending cleanup capture differs from the journal")
            registrations[arm] = {"cell_path": enrolled["cell_config"],
                "experiment_reference": self._row_experiment_reference(enrolled),
                "result_reference": graded["details"]["result_reference"], "capture_reference": capture_reference}
        if registrations[row["arm"]]["result_reference"] != result_reference:
            raise CohortError("pending cleanup public result differs from the journal")
        # The unchanged helper rechecks broker chains, native audit, sealed patch,
        # captures and every retained file, and accepts absence only under intent.
        plan = self.cleanup_operations.plan_target_cleanup(policy_reference, row["task_id"], registrations=registrations)
        if plan != intent:
            raise CohortError("pending cleanup no longer matches its immutable retained intent")
        return checked(result_reference)["broker_status"]

    def _broker_status(self, path):
        _, _, broker = self.operations.open_cell(path)
        return broker.status()

    def _resume_native_safe(self, row, status):
        if status["status"] == "SUBMITTED":
            return True
        if status["status"] != "WAITING_HANDOFF":
            return False
        if status["workers_issued"] == 0:
            return True
        if (status["workers_issued"] != status["workers_admitted"]
                or (Path(row["cell_config"]).parent / "native-execution-failure.json").exists()):
            return False
        from trimem_skhynix_architecture_native import outside_broker_item
        threads = set()
        for number in range(1, status["workers_issued"] + 1):
            output = (Path(self.config["native_control_root"]) / self.manifest["phase"] /
                row["target"]["instance_id"] / row["arm"] / f"worker-{number:03d}" / "output")
            try:
                completion = read(output / "completion.json")
                raw = (output / "events.jsonl").read_bytes()
                events = [json.loads(line) for line in raw.splitlines()]
                identities = [event["thread_id"] for event in events if event.get("type") == "thread.started"]
                if (sha(raw) != completion["events_sha256"] or identities != [completion["thread_id"]]
                        or completion["thread_id"] in threads or list(output.glob("manager-error-*.json"))
                        or execution.native_completion_status(completion, completion["exit_code"]) != "COMPLETE"):
                    return False
                for event in events:
                    item = event.get("item", {})
                    if item and (outside_broker_item(item) or (item.get("type") == "mcp_tool_call" and item.get("error"))):
                        return False
                threads.add(completion["thread_id"])
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                return False
        return True

    def _capture_receipt(self, row, mirror):
        payload = checked(reference(mirror))
        training = self.manifest["phase"] == "TRAINING"
        schema = "skhynix/native-architecture-learning/1.0" if training else "skhynix/architecture-evaluation-capture/1.0"
        if (set(payload) != {"schema", "operation", "capture_receipt"}
                or payload["schema"] != schema
                or payload["operation"] != "COHORT_CAPTURE"):
            raise CohortError("training capture mirror does not match the learning hook schema")
        capture = checked(payload["capture_receipt"])
        if (capture.get("schema") != schema
                or capture.get("operation") != ("CAPTURE_CELL" if training else "CAPTURE_EVALUATION_CELL")
                or Path(capture["cell_path"]).resolve() != Path(row["cell_config"])
                or capture.get("task_id") != row["task_id"]):
            raise CohortError("training capture is bound to a different enrolled cell")
        if not training and (capture.get("arm") != row["arm"]
                or capture.get("bank_sha256") != (self.manifest["bank_reference"]["sha256"]
                    if self.manifest["bank_reference"] is not None else execution.EMPTY_BANK_SHA)
                or capture.get("admitted_to_frozen_bank") is not False):
            raise CohortError("evaluation quarantine differs from the arm or frozen memory bank")
        for source_reference in capture["source_references"].values():
            if reference(source_reference["path"]) != source_reference:
                raise CohortError("training capture source evidence changed")
        allowed = {"BASELINE_AUDIT_ONLY"} if not training and row["arm"] == "BASELINE" else {"CAPTURED", "NO_PUBLIC_ATTEMPTS"}
        if capture.get("status") not in allowed or capture.get("failures") != []:
            raise CohortError("training capture did not complete successfully; no automatic retry")
        return payload["capture_receipt"], capture["status"]

    def _learning(self, row, result):
        receipt_dir = self.root / "learning-receipts" / f"{row['ordinal']:04d}"
        mirror = receipt_dir / "learning-capture.json"
        events = self._cell_events(row)
        if any(event["stage"] == "LEARNED" for event in events):
            event = next(event for event in events if event["stage"] == "LEARNED")
            checked(event["details"]["mirror_reference"])
            checked(event["details"]["capture_reference"])
            self._capture_receipt(row, mirror)
            return
        if mirror.is_file():
            capture_reference, capture_status = self._capture_receipt(row, mirror)
            self._record("LEARNED", row, {"mirror_reference": reference(mirror),
                "capture_reference": capture_reference, "capture_status": capture_status,
                "recovered_durable_capture": True})
            return
        if any(event["stage"] == "LEARN_STARTED" for event in events):
            raise CohortError("interrupted learning hook has no durable capture receipt; no automatic retry")
        hook = self.learning_hook if self.manifest["phase"] == "TRAINING" else self.quarantine_hook
        if self._transition is not None:
            if self._transition_hook is None:
                from trimem_skhynix_architecture_learning import make_capture_hook
                self._transition_hook = make_capture_hook(self.active_learning_root)
            hook = self._transition_hook
        if hook is None:
            raise CohortError("this cohort requires its configured training capture hook")
        self._record("LEARN_STARTED", row, {})
        mirror_reference = hook(Path(row["cell_config"]), result, receipt_dir)
        checked(mirror_reference)
        if not mirror.exists() or reference(mirror) != mirror_reference:
            raise CohortError("learning hook did not write the matching durable capture mirror")
        capture_reference, capture_status = self._capture_receipt(row, mirror)
        self._record("LEARNED", row, {"mirror_reference": mirror_reference,
            "capture_reference": capture_reference, "capture_status": capture_status})

    def _advance(self, row):
        events = self._cell_events(row)
        stages = {event["stage"] for event in events}
        if "CELL_COMPLETE" in stages:
            self._validate_result(row)
            return
        path = Path(row["cell_config"])
        if "PREPARED" not in stages:
            if "PREPARE_STARTED" in stages:
                if not path.is_file():
                    raise CohortError("interrupted preparation has no completed cell config; no automatic retry")
                self._validate_cell(row)
                self._record("PREPARED", row, {"cell_reference": reference(path), "recovered_completed_preparation": True})
            else:
                if path.parent.exists():
                    raise CohortError("unregistered existing cell; explicitly adopt or classify it outside the cohort")
                self._record("PREPARE_STARTED", row, {})
                actual = Path(self.operations.prepare_cell(self._row_experiment_reference(row)["path"],
                    row["task_id"], row["arm"], bank_reference=self.manifest["bank_reference"])).resolve()
                if actual != path:
                    raise CohortError("preparation returned a different enrolled cell path")
                self._validate_cell(row)
                self._record("PREPARED", row, {"cell_reference": reference(path)})
        self._validate_cell(row)
        events = self._cell_events(row)
        stages = {event["stage"] for event in events}
        if "SOLVE_COMPLETE" not in stages:
            status = self._broker_status(path)
            if not self._resume_native_safe(row, status):
                raise CohortError("native worker is active, unaudited, or terminated; no automatic fresh retry")
            if status["status"] != "SUBMITTED":
                self._record("SOLVE_STARTED" if "SOLVE_STARTED" not in stages else "SOLVE_CONTINUED", row,
                    {"workers_issued_before": status["workers_issued"], "same_cell_only": True})
                status = self.operations.run_workers(path)
                if status["status"] != "SUBMITTED":
                    raise CohortError("native execution returned without a sealed submission")
            self.operations.execution_audit(path)
            self._record("SOLVE_COMPLETE", row, {"broker_event_tail_sha256": status["event_tail_sha256"],
                "patch_sha256": status["submission"]["patch_sha256"],
                "execution_audit_reference": reference(path.parent / "execution-audit.json")})
        stages = {event["stage"] for event in self._cell_events(row)}
        result_path = path.parent / "public-result.json"
        if not {"GRADED", "GRADE_UNDETERMINED"} & stages:
            if not result_path.exists():
                if "GRADE_STARTED" in stages or (path.parent / "grader-pending.json").exists():
                    if not self._training_grade_hold_enabled(row) or self.operations.training_grade_undetermined(path, create=True) is None:
                        raise CohortError("prior grading invocation has no completed public result; no automatic retry")
                else:
                    self._record("GRADE_STARTED", row, {})
                    try:
                        self.operations.grade_cell(path)
                    except GraderInvocationFailure:
                        # The proof helper accepts only a completed, sealed, known
                        # aggregate; it never invokes a solver or grader itself.
                        if (not self._training_grade_hold_enabled(row)
                                or self.operations.training_grade_undetermined(path, create=True) is None):
                            raise
            result, result_reference = self._validate_result(row)
            self._record("GRADED" if result["official"] else "GRADE_UNDETERMINED", row,
                {"result_reference": result_reference, "official_resolved": result["resolved"]})
        result, _ = self._validate_result(row)
        if self.manifest["capture_enabled"]:
            self._learning(row, result)
        self._record("CELL_COMPLETE", row, {"official_resolved": result["resolved"],
            "capture_mode": self.manifest["capture_mode"] if self.manifest["capture_enabled"] else "NOT_CONFIGURED"})

    def _cleanup(self, row):
        if self.manifest["cleanup_policy_reference"] is None:
            return
        if self._cached_terminal(row) is not None:
            return
        checked(self._row_cleanup_policy_reference(row))
        if self.manifest["cleanup_source_reference"] is not None:
            verify_reference(self.manifest["cleanup_source_reference"])
        events = self._cell_events(row)
        graded = next(event for event in events if event["stage"] in {"GRADED", "GRADE_UNDETERMINED"})
        captured = next(event for event in events if event["stage"] == "LEARNED")
        previous = next((event for event in events if event["stage"] == "CLEANED"), None)
        if previous:
            checked(previous["details"]["cleanup_reference"])
            completion = self.cleanup_operations.validate_completed_cleanup(Path(row["cell_config"]),
                graded["details"]["result_reference"], captured["details"]["capture_reference"])
            _validate_reconciliation(completion)
            self._require_image_postcondition(row, completion)
            return
        # Cleanup helper owns validated idempotent recovery. No solve/grade operation is repeated.
        folder = Path(self.config["run_root"]) / "cleanup" / row["task_id"]
        incomplete = any(folder.glob("attempt-[0-9][0-9][0-9][0-9].json")) and not (folder / "completion.ref.json").exists()
        if incomplete:
            outcome = self._reconcile_absent_owned_images(row, graded["details"]["result_reference"],
                captured["details"]["capture_reference"])
            if outcome is None:
                raise CohortError("pending cleanup lacks explicit owned-image absence; removal is not retried")
        else:
            try:
                outcome = self.cleanup_operations.cleanup_completed_cell(Path(row["cell_config"]),
                    graded["details"]["result_reference"], captured["details"]["capture_reference"],
                    policy_reference=self._row_cleanup_policy_reference(row))
            except Exception:
                outcome = self._reconcile_absent_owned_images(row, graded["details"]["result_reference"],
                    captured["details"]["capture_reference"])
                if outcome is None:
                    raise
        if outcome["status"] == "COMPLETE":
            checked(outcome["cleanup_reference"])
            completion = self.cleanup_operations.validate_completed_cleanup(Path(row["cell_config"]),
                graded["details"]["result_reference"], captured["details"]["capture_reference"])
            _validate_reconciliation(completion)
            self._require_image_postcondition(row, completion)
            self._record("CLEANED", row, outcome)
        elif outcome != {"status": "WAITING_FOR_PAIRED_COMPLETION", "cleanup_reference": None}:
            raise CohortError("cleanup returned an unrecognised completion status")
        elif not any(event["stage"] == "CLEANUP_WAITING" for event in events):
            self._record("CLEANUP_WAITING", row, outcome)

    def _require_image_postcondition(self, row, completion):
        folder = Path(self.config["run_root"]) / "cleanup" / row["task_id"]
        if _image_postcondition(completion, folder):
            return
        proofs = []
        for image in sorted(item["image"] for item in completion["images"]):
            proof = _inspect_absent_owned_image(image)
            if proof is None:
                raise CohortError("cleanup image absence is ambiguous; owned-image postcondition remains pending")
            proofs.append({"image": image, "absent": True, "inspect": proof})
        controller, _ = self._check_controller_source()
        value = {"schema": "skhynix/architecture-owned-image-postcondition/1.0",
            "completion_reference": reference(folder / "completion.json"), "intent_reference": completion["intent_reference"],
            "controller_source_reference": controller, "images": proofs,
            "delete_operations": 0, "model_calls": 0, "official_grader_runs": 0}
        _retain_json(folder / "owned-image-postcondition.json", value)
        _image_postcondition(completion, folder, required=True)

    def _reconcile_absent_owned_images(self, row, result_reference, capture_reference):
        """Complete only already-performed removals; this path never deletes anything."""
        folder = Path(self.config["run_root"]) / "cleanup" / row["task_id"]
        attempts = sorted(folder.glob("attempt-[0-9][0-9][0-9][0-9].json"))
        if not attempts or (folder / "completion.ref.json").exists():
            return None
        with locked(folder / "cleanup.lock"):
            self._pending_cleanup_status(row, result_reference)
            intent_reference = reference(folder / "intent.json")
            intent = checked(intent_reference)
            attempt_reference = reference(attempts[-1])
            attempt = checked(attempt_reference)
            expected_paths = [cell["checkout"]["path"] for cell in intent["cells"]] if intent["remove_checkouts"] else []
            images = attempt.get("images", [])
            if (attempt.get("schema") != intent["schema"] or attempt.get("status") != "INCOMPLETE_IMAGE_RELEASE" or
                    attempt.get("intent_reference") != intent_reference or attempt.get("task_id") != row["task_id"] or
                    attempt.get("phase") != self.manifest["phase"] or attempt.get("preserved_references") != intent["preserved_references"] or
                    attempt.get("model_calls") != 0 or attempt.get("official_grader_runs") != 0 or
                    not intent["release_owned_images"] or not images or
                    [item.get("path") for item in attempt.get("checkouts", [])] != expected_paths or
                    any(item.get("status") not in {"REMOVED_GENERATED_CHECKOUT", "ABSENT_AFTER_RETAINED_INTENT"} for item in attempt["checkouts"]) or
                    any(Path(path).exists() or Path(path).is_symlink() for path in expected_paths) or
                    len(images) != len(intent["owned_images"]) or {item.get("image") for item in images} != set(intent["owned_images"]) or
                    any(type(item.get("removed")) is not bool for item in images) or all(item["removed"] for item in images)):
                return None
            proofs = []
            for image in sorted(intent["owned_images"]):
                proof = _inspect_absent_owned_image(image)
                if proof is None:
                    return None
                proofs.append({"image": image, "absent": True, "inspect": proof})
            # Recheck retained bytes after Docker observation, before writing receipts.
            self._pending_cleanup_status(row, result_reference)
            if reference(attempts[-1]) != attempt_reference or reference(folder / "intent.json") != intent_reference:
                raise CohortError("cleanup attempt changed during absence reconciliation")
            controller, _ = self._check_controller_source()
            reconciliation = {"schema": "skhynix/architecture-cleanup-absence-reconciliation/1.0",
                "operation": "RECONCILE_ABSENT_OWNED_IMAGES", "task_id": row["task_id"], "phase": self.manifest["phase"],
                "intent_reference": intent_reference, "failed_attempt_reference": attempt_reference,
                "controller_source_reference": controller, "images": proofs,
                "delete_operations": 0, "model_calls": 0, "official_grader_runs": 0}
            reconciliation_reference = _retain_json(folder / "absence-reconciliation.json", reconciliation)
            completion = {**attempt, "status": "COMPLETE", "images": [{"image": item["image"], "removed": True} for item in images],
                "reconciliation_reference": reconciliation_reference}
            completed = _retain_json(folder / "completion.json", completion)
            _retain_json(folder / "completion.ref.json", completed)
            _validate_reconciliation(self.cleanup_operations.validate_completed_cleanup(Path(row["cell_config"]), result_reference, capture_reference))
            return {"status": "COMPLETE", "cleanup_reference": completed}

    def run(self, *, cell_limit=None):
        if cell_limit is not None and (type(cell_limit) is not int or cell_limit < 1):
            raise CohortError("cell limit must be a positive integer")
        with locked(self.root / "run.lock"), self._journal_snapshot():
            self.operations.load_experiment(self.manifest["experiment_reference"]["path"])
            self._check_execution_api()
            checked(self.manifest["experiment_reference"])
            self._check_controller_source()
            if self.manifest["bank_reference"] is not None:
                checked(self.manifest["bank_reference"])
            advanced = 0
            for row in self.schedule:
                events = self._cell_events(row)
                if any(event["stage"] == "CELL_COMPLETE" for event in events):
                    try:
                        self._cleanup(row)
                    except Exception as exc:
                        self._record("INFRA_ERROR", row, {"operation": "CLEANUP", "error_type": type(exc).__name__,
                            "error": str(exc)[:2000], "solver_retry": False})
                        break
                    continue
                if cell_limit is not None and advanced >= cell_limit:
                    break
                storage_root = Path(self.config["run_root"])
                while not storage_root.exists():
                    storage_root = storage_root.parent
                free = self.disk_free(storage_root)
                if free < self.manifest["min_free_bytes"]:
                    self._record("DISK_BLOCK", row, {"free_bytes": free,
                        "minimum_bytes": self.manifest["min_free_bytes"], "operation_started": False})
                    break
                try:
                    self._advance(row)
                    self._cleanup(row)
                except Exception as exc:
                    self._record("INFRA_ERROR", row, {"error_type": type(exc).__name__, "error": str(exc)[:2000],
                        "automatic_retry": False, "result_is_not_a_solver_failure": True})
                    break
                advanced += 1
            result = self.status()
            result["cells_advanced_this_invocation"] = advanced
            return result

    def status(self, *, full_audit=False):
        """Use metadata-coherent process-local caches; a fresh runner starts empty."""
        if type(full_audit) is not bool:
            raise CohortError("full_audit must be a boolean")
        with self._journal_snapshot():
            return self._status(full_audit=full_audit)

    def full_audit(self):
        """Rehash/revalidate all original retained authorities, never a persisted cache."""
        return self.status(full_audit=True)

    def _status(self, *, full_audit):
        events = self._events()
        tail = events[-1]["sha256"] if events else ZERO
        required = {"CELL_COMPLETE"} if self.manifest["cleanup_policy_reference"] is None else {"CELL_COMPLETE", "CLEANED"}
        if not full_audit and self._terminal_audit_tail != tail and all(
                required <= {event["stage"] for event in self._cell_events(row)} for row in self.schedule):
            full_audit = True
        if full_audit and _event_chain(self.root) != events:
            raise CohortError("journal changed during full cohort audit")
        if full_audit:
            self._refresh_effort_transition()
        controller_source, controller_revisions = self._check_controller_source(events)
        cells, by_arm, public = [], {}, {}
        for arm in self.manifest["arms"]:
            by_arm[arm] = {"planned": sum(row["arm"] == arm for row in self.schedule),
                          "official_complete": 0, "resolved": 0, "infra_errors": 0, "missing": 0, "undetermined": 0}
        for row in self.schedule:
            history = self._cell_events(row)
            stages = {event["stage"] for event in history}
            state = "COMPLETE" if "CELL_COMPLETE" in stages else "INFRA_ERROR" if history and history[-1]["stage"] == "INFRA_ERROR" else "PENDING"
            resolved = None
            graded = next((event for event in history if event["stage"] == "GRADED"), None)
            unscored = next((event for event in history if event["stage"] == "GRADE_UNDETERMINED"), None)
            if graded is not None and unscored is not None:
                raise CohortError("a task cannot have both official and undetermined grade events")
            if graded is not None:
                result, result_reference = self._validate_result(row, full_audit=full_audit)
                if result_reference != graded["details"]["result_reference"]:
                    raise CohortError("frozen cohort artifact reference changed")
                resolved = result["resolved"]
                public[(row["task_id"], row["arm"])] = resolved
                by_arm[row["arm"]]["official_complete"] += 1
                by_arm[row["arm"]]["resolved"] += int(resolved)
            elif unscored is not None:
                result, result_reference = self._validate_result(row, full_audit=full_audit)
                if (result_reference != unscored["details"]["result_reference"]
                        or result.get("official") is not False or result.get("resolved") is not None):
                    raise CohortError("undetermined outcome was counted as a completed official grade")
                by_arm[row["arm"]]["undetermined"] += 1
            else:
                by_arm[row["arm"]]["missing"] += 1
            if state == "INFRA_ERROR":
                by_arm[row["arm"]]["infra_errors"] += 1
            folder = Path(self.config["run_root"]) / "cleanup" / row["task_id"]
            cleanup_state = ("NOT_CONFIGURED" if self.manifest["cleanup_policy_reference"] is None else
                "COMPLETE" if (folder / "completion.ref.json").is_file() and
                    _image_postcondition(checked(read(folder / "completion.ref.json")), folder) else
                "PENDING" if (folder / "intent.json").is_file() else "NOT_STARTED")
            cells.append({"ordinal": row["ordinal"], "task_id": row["task_id"], "arm": row["arm"],
                "state": state, "official_resolved": resolved, "cleanup_state": cleanup_state,
                "experiment_reference": deepcopy(self._row_experiment_reference(row)),
                "reasoning_effort": self._row_config(row).get("reasoning_effort"),
                "last_stage": history[-1]["stage"] if history else "NOT_STARTED"})
        for counts in by_arm.values():
            counts["completed_cell_solve_rate"] = counts["resolved"] / counts["official_complete"] if counts["official_complete"] else None
            counts["full_enrollment_solve_rate"] = counts["resolved"] / counts["planned"] if counts["official_complete"] == counts["planned"] else None
        paired = None
        if self.manifest["phase"] == "EVALUATION" and self.manifest["arms"] == list(PHASE_ARMS["EVALUATION"]):
            ids = sorted({row["task_id"] for row in self.schedule})
            complete = [identity for identity in ids if all((identity, arm) in public for arm in PHASE_ARMS["EVALUATION"])]
            a = sum(public[(identity, "BASELINE")] for identity in complete)
            c = sum(public[(identity, "PDF_MEMORY")] for identity in complete)
            paired = {"planned_pairs": len(ids), "completed_pairs": len(complete), "missing_pairs": len(ids) - len(complete),
                "baseline_resolved": a, "pdf_memory_resolved": c,
                "completed_pair_delta_percentage_points": 100 * (c - a) / len(complete) if complete else None,
                "full_cohort_delta_percentage_points": 100 * (c - a) / len(ids) if len(complete) == len(ids) else None}
        complete = all(row["state"] == "COMPLETE" and row["cleanup_state"] in {"COMPLETE", "NOT_CONFIGURED"} for row in cells)
        if complete and not full_audit and self._terminal_audit_tail != tail:
            return self._status(full_audit=True)
        if full_audit:
            if self._authority_stamps() != self._authority_token or _event_chain(self.root) != events:
                raise CohortError("cohort authority changed during terminal full audit")
            for row in self.schedule:
                if row["ordinal"] in self._terminal_cache and self._cached_terminal(row) is None:
                    raise CohortError("retained evidence changed during terminal full audit")
            self._terminal_audit_tail = tail if complete else None
        blocked = bool(events and events[-1]["stage"] in {"INFRA_ERROR", "DISK_BLOCK"})
        return {"schema": SCHEMA, "phase": self.manifest["phase"], "scope": self.manifest["scope"],
            "status": "BLOCKED" if blocked else "COMPLETE" if complete else "IN_PROGRESS",
            "planned_cells": len(cells), "completed_cells": sum(row["state"] == "COMPLETE" for row in cells),
            "by_arm": by_arm, "paired_comparison": paired, "cells": cells,
            "event_count": len(events), "event_tail_sha256": events[-1]["sha256"] if events else ZERO,
            "outside_cohort_trials": len(self.manifest["outside_cohort"]),
            "execution_config_exclusion_references": self.config.get("exclusion_references", []),
            "cleanup_policy": self.manifest["cleanup_policy"], "capture_mode": self.manifest["capture_mode"],
            "cleanup_pending_cells": sum(row["cleanup_state"] == "PENDING" for row in cells),
            "controller_source_reference": controller_source, "controller_revision_count": len(controller_revisions),
            "reasoning_effort_transition_reference": self.reasoning_effort_transition_reference,
            "active_learning_root": self.active_learning_root,
            "scale_purpose": self.manifest.get("scale_purpose"),
            "adopted_training_source_count": self.manifest.get("adopted_training_source_count", 0),
            "validation_mode": "FULL_AUDIT" if full_audit else "COHERENT_IN_PROCESS_CACHE",
            "terminal_full_audit_complete": complete and self._terminal_audit_tail == tail,
            "frozen_evaluation_bank_updates": False, "outcome_retries": False}


def _open(root):
    manifest = read(Path(root) / "cohort.json")
    hook = None
    quarantine_hook = None
    if manifest["learning_root"] is not None:
        from trimem_skhynix_architecture_learning import make_capture_hook
        hook = make_capture_hook(manifest["learning_root"])
    if manifest["quarantine_root"] is not None:
        from trimem_skhynix_architecture_quarantine import make_quarantine_hook
        quarantine_hook = make_quarantine_hook(manifest["quarantine_root"])
    return CohortRunner(root, learning_hook=hook, quarantine_hook=quarantine_hook)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "run", "status"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--experiment-config", type=Path)
    parser.add_argument("--phase", choices=tuple(PHASE_ARMS))
    parser.add_argument("--task-id", action="append")
    parser.add_argument("--bank-reference", type=Path, help="JSON containing an immutable path/sha256 reference")
    parser.add_argument("--learning-root", type=Path)
    parser.add_argument("--quarantine-root", type=Path)
    parser.add_argument("--cleanup-policy-reference", type=Path)
    parser.add_argument("--adopt-existing", action="append", type=Path, default=[])
    parser.add_argument("--outside-cohort-receipt", action="append", type=Path, default=[])
    parser.add_argument("--min-free-bytes", type=int, default=10 * 1024**3)
    parser.add_argument("--cell-limit", type=int)
    args = parser.parse_args()
    if args.command == "create":
        if args.experiment_config is None or args.phase is None:
            parser.error("create requires --experiment-config and --phase")
        runner = CohortRunner.create(args.root, experiment_path=args.experiment_config, phase=args.phase,
            target_ids=args.task_id, bank_reference=read(args.bank_reference) if args.bank_reference else None,
            learning_root=args.learning_root, quarantine_root=args.quarantine_root,
            cleanup_policy_reference=read(args.cleanup_policy_reference) if args.cleanup_policy_reference else None,
            adopt_existing=args.adopt_existing,
            outside_cohort=args.outside_cohort_receipt, min_free_bytes=args.min_free_bytes)
        result = runner.status()
    else:
        runner = _open(args.root)
        result = runner.run(cell_limit=args.cell_limit) if args.command == "run" else runner.status()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
