"""Clone a completed public learning authority for a separately recorded reflection.

This helper never captures a source again, solves a task, invokes a grader or
promotes a skill. Original evidence references remain original; only the new
SQLite authority and mutable registry/catalog receive subsequent learning writes.
Run with the predecessor's frozen scripts/src on PYTHONPATH (Python -P).
"""
from contextlib import contextmanager
from pathlib import Path
import argparse
import fcntl
import json
import shutil
import sqlite3
import sys

import trimem_skhynix_architecture_learning as learning
import trimem_skhynix_architecture_memory as memory
import trimem_skhynix_architecture_pipeline as core

SCHEMA = "skhynix/learning-authority-recovery/1.0"
METADATA = ("learning-enrollment.json", "learning-enrollment.ref.json", "scope.json",
            "catalog.json", "learning-state.json", "authority.sqlite3")


class RecoveryError(ValueError):
    pass


@contextmanager
def _lock(path, *, exclusive):
    # Existing locks only: an incorrect authority path must not create files.
    with Path(path).open("r+b") as stream:
        try:
            fcntl.flock(stream, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RecoveryError("Predecessor learning or controller is still active") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _references(value):
    if isinstance(value, dict):
        if set(value) == {"path", "sha256"}:
            yield value
        else:
            for child in value.values():
                yield from _references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _references(child)


def _check_references(references):
    unique = {}
    for reference in references:
        previous = unique.setdefault(reference["path"], reference)
        if previous != reference:
            raise RecoveryError("Original evidence has conflicting immutable references")
        memory._check_ref(reference)
    return [unique[key] for key in sorted(unique)]


def _module_bindings(pipeline):
    execution = core.check(pipeline["training_experiment_reference"])
    root = memory._path(execution["source_root"])
    modules = (learning, memory, core, sys.modules[learning.load_experiment.__module__])
    references = {}
    for module in modules:
        path = memory._path(module.__file__)
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise RecoveryError("Learning recovery imports escaped the original frozen runtime") from exc
        reference = memory._ref(path)
        if execution["source_sha256"].get(relative) != reference["sha256"]:
            raise RecoveryError("Learning recovery implementation differs from the original runtime")
        references[module.__name__] = reference
    return references


def _predecessor(pipeline_reference, tail_reference, source):
    pipeline = core.check(pipeline_reference)
    root = memory._path(pipeline["pipeline_root"])
    if core.read(root / "pipeline-binding.json") != {
            "schema": pipeline["schema"], "configuration_reference": pipeline_reference}:
        raise RecoveryError("Predecessor pipeline binding differs")
    if Path(pipeline_reference["path"]).with_suffix(".sha256").read_text().strip() != memory._hash(pipeline):
        raise RecoveryError("Predecessor pipeline configuration checksum differs")
    paths = sorted((root / "events").glob("*.json"))
    if not paths or memory._ref(paths[-1]) != tail_reference:
        raise RecoveryError("Predecessor pipeline advanced after recovery was declared")
    events = core.read_event_chain(root)
    tail = core.check(tail_reference)
    if tail != events[-1] or tail.get("stage") != "NO_READY_MEMORY_BANK":
        raise RecoveryError("Reflection recovery requires terminal NO_READY_MEMORY_BANK")
    if (tail.get("details", {}).get("gate_b_waived") is not False or
            tail["details"].get("final_evaluation_cells") != 0 or
            any(event["stage"] in {"EVALUATION_CONFIGURED", "EVALUATION_COMPLETE", "BANK_SELECTED", "PIPELINE_COMPLETE"}
                for event in events)):
        raise RecoveryError("Reflection recovery cannot consume an already evaluated pipeline")
    stages = [stage for stage in pipeline["training_stages"] if
              memory._path(stage.get("learning_root", root / ("learning-" + str(stage["size"])))) == source]
    if len(stages) != 1:
        raise RecoveryError("Learning authority is not an exact predecessor training stage")
    stage = stages[0]
    statuses = [row for row in tail["details"].get("banks", []) if row.get("size") == stage["size"]]
    if (len(statuses) != 1 or statuses[0].get("status") != "NOT_READY" or
            statuses[0].get("source_attempts") != stage["size"] or
            statuses[0].get("bank_reference") is not None or
            statuses[0].get("catalog_reference") != memory._ref(source / "catalog.json")):
        raise RecoveryError("Original NOT_READY bank no longer binds this learning catalog")
    return pipeline, stage


def _validate_learning(root, enrollment, registry):
    available = learning._available_captures(root, registry)
    receipts = [learning._checked_cell_receipt(ref) for ref in registry["cells"].values()]
    tasks = [row.get("task_id") for row in receipts]
    if (len(tasks) != len(set(tasks)) or set(tasks) != set(enrollment["training_tasks"]) or
            any(row.get("status") not in {"CAPTURED", "NO_PUBLIC_ATTEMPTS"} or
                not row.get("source_execution_observed") or row.get("failures") for row in receipts)):
        raise RecoveryError("Clone requires every original enrolled source and no capture failures")
    catalog, scope = memory._read(root / "catalog.json"), memory._read(root / "scope.json")
    evidence = list(_references(registry)) + list(_references(catalog))
    for receipt in receipts:
        evidence.extend(_references(receipt))
    for refs in registry["reflections"].values():
        public, private = core.check(refs["public"]), core.check(refs["private"])
        if (public["publisher_map_sha256"] != memory._hash(private) or
                private["enrollment_sha256"] != memory._file_hash(root / "learning-enrollment.json")):
            raise RecoveryError("Original reflection mapping differs from its enrollment")
        evidence.extend(_references(private))
    for reference in registry["ingestions"].values():
        ingestion = core.check(reference)
        evidence.extend(_references(ingestion))
        public = ingestion.get("reflection_reference")
        registered = registry["reflections"].get(public.get("sha256")) if isinstance(public, dict) else None
        if registered is None or registered["public"] != public:
            raise RecoveryError("Original ingestion has an unregistered reflection")
    evidence = _check_references(evidence)
    with memory._ReadOnlyStore(root / "authority.sqlite3") as store:
        counts = memory._validate_authority(store, catalog, scope)
    return {"training_sources": len(tasks), "captures": len(available),
            "L1_episodes": counts["episode"], "L2_nodes": counts["knowledge"],
            "L2_edges": len(catalog["edges"]), "L3_skills": counts["skill"]}, evidence


def clone_learning_authority(source_root, destination_root, *, predecessor_pipeline_reference,
                             predecessor_pipeline_event_tail_reference, request_reference=None):
    """Validate and copy an authority, retaining exact original evidence pointers.

    A failed partial destination is retained for diagnosis and never resumed or
    overwritten. The immutable receipt is written only after both authorities
    and the source snapshot pass final validation.
    """
    source, destination = memory._path(source_root), memory._path(destination_root)
    helper_reference = memory._ref(__file__)
    if request_reference is not None and core.check(request_reference) != {
            "source_root": str(source), "destination_root": str(destination),
            "predecessor_pipeline_reference": predecessor_pipeline_reference,
            "predecessor_pipeline_event_tail_reference": predecessor_pipeline_event_tail_reference}:
        raise RecoveryError("Clone request differs from its exact immutable arguments")
    if destination.exists() or source == destination or source in destination.parents or destination in source.parents:
        raise RecoveryError("Recovery destination must be fresh and separate from the original authority")
    pipeline = core.check(predecessor_pipeline_reference)
    pipeline_root = memory._path(pipeline["pipeline_root"])
    with _lock(pipeline_root / "run.lock", exclusive=True):
        pipeline, stage = _predecessor(predecessor_pipeline_reference,
                                      predecessor_pipeline_event_tail_reference, source)
        implementations = _module_bindings(pipeline)
        # Follow the writer's learning-then-operation lock order. _session's
        # additional shared descriptor is compatible with our shared lock.
        with _lock(source / "learning.lock", exclusive=False), _lock(source / "operation.lock", exclusive=False), learning._session(source, mutable=False) as (_, enrollment, registry, _):
            if any((source / name).exists() for name in ("learning-frozen.json", "frozen.json")):
                raise RecoveryError("Reflection recovery requires the original unpublished authority")
            snapshots = {name: memory._ref(source / name) for name in METADATA}
            memory._check_ref(snapshots["authority.sqlite3"], authority=True)
            counts, evidence = _validate_learning(source, enrollment, registry)
            if counts["training_sources"] != stage["size"] or counts["L3_skills"] != 0:
                raise RecoveryError("Original authority differs from the terminal empty-L3 bank")
            destination.mkdir(parents=True, exist_ok=False)
            initial = destination / "recovery-initial"
            initial.mkdir()
            for name in METADATA:
                if name == "authority.sqlite3":
                    continue
                raw = Path(snapshots[name]["path"]).read_bytes()
                (initial / name).write_bytes(raw)
                if name != "learning-enrollment.ref.json":
                    (destination / name).write_bytes(raw)
            # Backup uses the original database strictly read-only; it neither
            # initializes nor checkpoints nor writes to the predecessor.
            with sqlite3.connect((source / "authority.sqlite3").as_uri() + "?mode=ro", uri=True) as original:
                original.execute("PRAGMA query_only=ON")
                with sqlite3.connect(initial / "authority.sqlite3") as copied:
                    original.backup(copied)
            shutil.copyfile(initial / "authority.sqlite3", destination / "authority.sqlite3")
            memory._write(destination / "learning-enrollment.ref.json",
                          memory._ref(destination / "learning-enrollment.json"), fresh=True)
            with learning._session(destination, mutable=False) as (_, cloned_enrollment, cloned_registry, _):
                cloned_counts, cloned_evidence = _validate_learning(destination, cloned_enrollment, cloned_registry)
            if cloned_counts != counts or cloned_evidence != evidence:
                raise RecoveryError("Clone changed original evidence or memory contents")
            _check_references([*snapshots.values(), *evidence, *implementations.values(), helper_reference,
                               *([request_reference] if request_reference is not None else [])])
            _predecessor(predecessor_pipeline_reference, predecessor_pipeline_event_tail_reference, source)
            receipt = {"schema": SCHEMA, "operation": "CLONE_COMPLETED_PUBLIC_LEARNING_FOR_REFLECTION",
                "source_root": str(source), "destination_root": str(destination),
                "predecessor_pipeline_reference": predecessor_pipeline_reference,
                "predecessor_pipeline_event_tail_reference": predecessor_pipeline_event_tail_reference,
                "stage_execution_reference": stage["execution_reference"],
                "source_snapshot_references": snapshots,
                "clone_initial_references": {name: memory._ref(initial / name) for name in METADATA},
                "learning_enrollment_reference": memory._ref(destination / "learning-enrollment.json"),
                "recovery_helper_reference": helper_reference, "request_reference": request_reference,
                "implementation_references": implementations, "original_evidence_references": evidence,
                "counts": counts, "original_evidence_paths_preserved": True,
                "official_outcomes_used_for_training": False, "gate_b_waived": False,
                "model_calls": 0, "solver_runs": 0, "official_grader_runs": 0, "source_recaptures": 0}
            return core.retain(destination / "learning-recovery.json", receipt)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, help="JSON with the four clone_learning_authority arguments")
    arguments = parser.parse_args()
    print(json.dumps(clone_learning_authority(**core.read(arguments.request),
                                              request_reference=core.ref(arguments.request))))
