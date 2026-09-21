"""Immutable preparation contract for a full PDF architecture ON/OFF comparison.

This module consumes public inventory JSON and hashes source files as opaque
bytes. It never decodes benchmark rows, runs training, promotes skills, launches
workers or grades tasks. Binding a receipt is not verification of live runtime
integration: the separate inspector deliberately cannot declare evaluation ready.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

SCHEMA = "skhynix/pdf-architecture-preparation/1.0"
INVENTORY_SCHEMA = "skhynix/architecture-public-task-inventory/1.0"
READINESS_SCHEMA = "skhynix/pdf-architecture-readiness/1.0"
STATUS = "NOT_EVALUATION_READY"
EVALUATION_COUNT = 500
EVALUATION_TASKS_SHA256 = "3e6fd75c680f7ecb07f659ced6019da4ccfa1e2695d025d71757814506c30dd2"
EVALUATION_SOURCE = {
    "dataset_id": "princeton-nlp/SWE-bench_Verified",
    "revision": "78f471bf655a3137b2e8a75af1501690ec009ec3", "split": "test",
    "sha256": "030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25",
    "bytes": 6304616,
}
DEFAULT_CONTEXT_BYTES = 196608
MAX_JSON_BYTES = 32_000_000
REQUIREMENTS = {
    "native_context_handoff": "Bind live fresh-worker handoff receipts for both arms, the same accepted subgoal-transition rule, exact delivered context bytes and task-wide accounting across workers. Packet assembly tests alone do not prove native delivery.",
    "live_l1": "Bind actual owner-scoped private Gate A writes and retrieval traces, including isolation checks and evaluation writes quarantined from the frozen training retrieval bank.",
    "l2_edges": "Bind actual source-supported repository relations and PPR retrieval traces using the active subgoal query, with no score override or forced delivery.",
    "gate_b": "Bind actual successful Gate B promotion with more than zero verified parameterized skills and validated supporting episodes; declared counts are insufficient.",
    "trained_bank": "Bind the immutable trained bank and actual execution evidence for the allowed, fully disjoint training sources. A public candidate inventory is not a trained bank.",
    "training_enrollment": "Bind the exact executed training task and original source-instance identities, all disjoint from every evaluation instance, plus the stable private-memory owner scopes.",
    "generic_runtime_manifest": "Bind the actual generic two-arm runtime and full task manifest, common request/time/context limits, native worker lifecycle and end-to-end integration evidence.",
    "full_target_inventory": "Bind the entire byte-pinned public Verified inventory and exactly all 500 evaluation identities without omissions or duplicates.",
}


class ArchitecturePlanError(ValueError):
    pass


def _fail(message):
    raise ArchitecturePlanError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _fields(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        _fail(f"{label} contains missing or forbidden fields")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("Duplicate JSON fields are forbidden")
        result[key] = value
    return result


def _json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
            parse_constant=lambda _: _fail("Nonfinite JSON values are forbidden"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ArchitecturePlanError("Invalid public contract JSON") from exc


def _text(value, label, maximum=256):
    if (not isinstance(value, str) or not value or value.strip() != value or
            len(value.encode()) > maximum or "\x00" in value):
        _fail(f"Invalid {label}")
    return value


def _digest(value, label, size=64):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{%d}" % size, value):
        _fail(f"Invalid {label} digest")
    return value


def _path(value, *, exists=True):
    if not isinstance(value, (str, Path)) or not str(value) or ".." in Path(value).parts:
        _fail("Invalid contract path")
    path = Path(value)
    if not path.is_absolute():
        _fail("Contract paths must be absolute")
    if (path.resolve() != path or any(item.is_symlink() or getattr(item, "is_junction", lambda: False)()
            for item in (path, *path.parents))):
        _fail("Linked contract paths are forbidden")
    if exists and not path.is_file():
        _fail("Referenced contract file is missing")
    return path


def _reference(reference):
    _fields(reference, "path sha256", "Frozen reference")
    _digest(reference["sha256"], "frozen reference")
    path = _path(reference["path"])
    if file_sha(path) != reference["sha256"]:
        _fail("Frozen reference bytes changed")
    return {"path": str(path), "sha256": reference["sha256"]}


def _read_reference(reference):
    reference = _reference(reference)
    path = Path(reference["path"])
    if path.stat().st_size > MAX_JSON_BYTES:
        _fail("Public inventory or design JSON exceeds its byte bound")
    value = _json(path.read_bytes())
    _reference(reference)
    return reference, value


def load_public_inventory(reference, *, evaluation=False):
    """Read only the strict public descriptor view; never parse its source parquet."""
    reference, value = _read_reference(reference)
    _fields(value, "schema dataset tasks", "Public inventory")
    if value["schema"] != INVENTORY_SCHEMA:
        _fail("Unsupported public inventory schema")
    dataset = value["dataset"]
    _fields(dataset, "dataset_id revision split path sha256 bytes", "Public dataset binding")
    _text(dataset["dataset_id"], "dataset id")
    _digest(dataset["revision"], "dataset revision", 40)
    _text(dataset["split"], "dataset split")
    _digest(dataset["sha256"], "dataset source")
    if type(dataset["bytes"]) is not int or dataset["bytes"] <= 0:
        _fail("Public dataset source size must be a positive integer")
    if evaluation and any(dataset[key] != expected for key, expected in EVALUATION_SOURCE.items()):
        _fail("Evaluation dataset differs from the pinned full Verified source")
    source = _path(dataset["path"])
    if source.stat().st_size != dataset["bytes"] or file_sha(source) != dataset["sha256"]:
        _fail("Public dataset source size or byte hash differs")
    tasks = value["tasks"]
    if not isinstance(tasks, list) or not tasks or len(tasks) > 100000:
        _fail("Public inventory requires a bounded nonempty task list")
    if evaluation and len(tasks) != EVALUATION_COUNT:
        _fail("Evaluation inventory must contain exactly all 500 public tasks")
    identities = []
    for task in tasks:
        _fields(task, "instance_id repository base_commit created_at instruction_sha256", "Public task descriptor")
        identity = _text(task["instance_id"], "source instance id")
        repository = _text(task["repository"], "repository")
        if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or
                not re.fullmatch(re.escape(repository.replace("/", "__")) + r"-[0-9]+", identity)):
            _fail("Public task and original repository instance identity differ")
        _digest(task["base_commit"], "public base commit", 40)
        _digest(task["instruction_sha256"], "public instruction")
        try:
            stamp = datetime.fromisoformat(_text(task["created_at"], "public creation timestamp", 64).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                _fail("Public creation timestamp requires a timezone")
        except ValueError as exc:
            if isinstance(exc, ArchitecturePlanError):
                raise
            raise ArchitecturePlanError("Invalid public creation timestamp") from exc
        identities.append(identity)
    if len(set(identities)) != len(identities) or identities != sorted(identities):
        _fail("Public task identities must be unique and sorted")
    if evaluation and sha(canonical(tasks)) != EVALUATION_TASKS_SHA256:
        _fail("Evaluation public descriptor projection differs from the pinned exact 500-task inventory")
    return reference, value


def _task_rows(inventory, *, evaluation):
    prefix = "swebench_verified--" if evaluation else "swebench--"
    return [{"task_id": prefix + row["instance_id"], **row} for row in inventory["tasks"]]


def _training_references(value):
    if value is None:
        return []
    refs = value if isinstance(value, list) else [value]
    if not 1 <= len(refs) <= 16:
        _fail("Training candidate references must be a bounded nonempty list when supplied")
    return refs


def _architecture(context_bytes):
    if type(context_bytes) is not int or not 4096 <= context_bytes <= DEFAULT_CONTEXT_BYTES:
        _fail("Common context byte cap must be an integer from 4096 to 196608")
    limits = {"requests_per_task": 120, "wall_seconds_per_task": 1200, "context_utf8_bytes": context_bytes,
        "history_utf8_bytes": 48000, "trace_utf8_bytes": 48000,
        "memory_utf8_bytes": 12000, "memory_injections": 3,
        "accounting_scope": "WHOLE_TASK_ACROSS_ALL_WORKERS", "reset_on_worker_transition": False}
    workers = {"launch": "FRESH_NATIVE_WORKER_AT_TASK_START_AND_EACH_ACCEPTED_SUBGOAL_TRANSITION",
        "fork_turns": "none", "transition_rule": "COMMON_MANAGER_ACCEPTED_SUBGOAL_TRANSITION_RULE",
        "same_transition_rule_in_both_arms": True, "implicit_prior_worker_context": False}
    baseline = {"name": "BASELINE", "limits": deepcopy(limits), "worker_policy": deepcopy(workers),
        "context": "FLAT_BOUNDED_PUBLIC_HISTORY", "external_memory": "DISABLED"}
    pdf = {"name": "PDF_MEMORY", "limits": deepcopy(limits), "worker_policy": deepcopy(workers),
        "context": "ACTIVE_SUBGOAL_CONTEXT_WITH_EXACT_PUBLIC_TRACE_RECALL",
        "external_memory": "ENABLED", "retrieval_order": ["SKILL", "REPOSITORY_KG", "EPISODE"],
        "l1": {"gate_a": "LIVE_PRIVATE_EPISODE_CAPTURE", "scope": ["org_id", "owner_user_id", "repository"],
            "owner_stable_across_task_workers": True, "cross_owner_retrieval": False},
        "l2": {"relations": "EXPLICIT_SOURCE_BOUND_KNOWLEDGE_EDGES", "ranking": "PPR",
            "query": "CURRENT_ACTIVE_SUBGOAL_TRACE", "normal_eligibility_and_provenance_gates": True},
        "l3": {"gate_b": "ACTUAL_VERIFIED_PARAMETERIZED_SKILL_PROMOTION", "minimum_verified_skill_count": 1,
            "private_support_provenance_required": True},
        "score_override": False, "forced_delivery": False, "manual_lesson_assignment": False,
        "exact_task_diagnostic_route": False}
    return limits, {"A": baseline, "C": pdf}


def _derive(evaluation_inventory, training_inventory, context_bytes):
    evaluation_ref, evaluation = load_public_inventory(evaluation_inventory, evaluation=True)
    evaluation_rows = _task_rows(evaluation, evaluation=True)
    evaluation_ids = {row["instance_id"] for row in evaluation_rows}
    training_refs, training_rows = [], []
    for reference in _training_references(training_inventory):
        normalized, inventory = load_public_inventory(reference)
        training_refs.append(normalized)
        training_rows.extend(_task_rows(inventory, evaluation=False))
    training_instances = [row["instance_id"] for row in training_rows]
    training_task_ids = [row["task_id"] for row in training_rows]
    if (len(set(training_instances)) != len(training_instances) or len(set(training_task_ids)) != len(training_task_ids) or
            evaluation_ids.intersection(training_instances) or
            {row["task_id"] for row in evaluation_rows}.intersection(training_task_ids)):
        _fail("All training task and original source-instance IDs must be unique and disjoint from every one of the 500 evaluation tasks")
    if {row["instruction_sha256"] for row in evaluation_rows}.intersection(
            row["instruction_sha256"] for row in training_rows):
        _fail("Training public instruction hashes must also be disjoint from every evaluation task")
    training_rows.sort(key=lambda row: row["instance_id"])
    limits, arms = _architecture(context_bytes)
    return {"schema": SCHEMA, "phase": "PREPARATION", "status": STATUS, "frozen": True,
        "scientific_role": "FULL_PDF_CORE_ARCHITECTURE_ON_OFF",
        "implementation_sha256": file_sha(Path(__file__)),
        "model": {"requested": "gpt-6-astra", "actual_snapshot_attested": False,
            "actual_tokens": None, "actual_cost": None},
        "common_limits": limits, "arms": arms,
        "evaluation": {"inventory": evaluation_ref, "dataset": evaluation["dataset"],
            "selection": "EXACT_ENTIRE_PINNED_PUBLIC_VERIFIED_500_INVENTORY",
            "task_count": EVALUATION_COUNT, "tasks": evaluation_rows,
            "task_ids_sha256": sha(canonical([row["task_id"] for row in evaluation_rows])),
            "paired_cells": EVALUATION_COUNT * 2},
        "training": {"candidate_inventories": training_refs, "role": "CANDIDATES_ONLY_NOT_ENROLLED_OR_EXECUTED",
            "candidate_task_count": len(training_rows), "candidates": training_rows,
            "all_evaluation_ids_excluded": True, "source_instance_ids_disjoint": True,
            "public_instruction_hashes_disjoint": True,
            "training_execution": "NOT_BOUND", "trained_bank": "NOT_BOUND"},
        "evaluation_gate_a": {"destination": "EVALUATION_PRIVATE_QUARANTINE",
            "admit_to_frozen_retrieval_bank": False, "cross_target_retrieval": False},
        "frozen_retrieval_bank": {"source": "DISJOINT_EXECUTED_TRAINING_ONLY", "evaluation_updates": False},
        "readiness_requirements": dict(REQUIREMENTS),
        "readiness_policy": "DESIGN_SWITCHES_AND_HASH_BOUND_RECEIPTS_DO_NOT_PROVE_LIVE_INTEGRATION",
        "model_calls": 0, "grader_calls": 0, "training_runs": 0,
        "public_input_policy": "STRICT_PUBLIC_DESCRIPTOR_JSON_ONLY_SOURCE_FILES_HASHED_AS_OPAQUE_BYTES"}


def build_architecture_design(evaluation_inventory, *, training_inventory=None, output,
                              context_budget_bytes=DEFAULT_CONTEXT_BYTES):
    """Freeze a preparation-only design from explicit {path, sha256} inventories."""
    path = _path(output, exists=False)
    if path.exists():
        _fail("Refusing to overwrite a frozen architecture design")
    design = _derive(evaluation_inventory, training_inventory, context_budget_bytes)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(design) + b"\n")
    return {"path": str(path), "sha256": file_sha(path), "status": STATUS,
        "evaluation_tasks": design["evaluation"]["task_count"], "planned_cells": 1000,
        "training_candidate_tasks": design["training"]["candidate_task_count"]}


def load_architecture_design(path, expected_sha256):
    _, design = _read_reference({"path": str(path), "sha256": expected_sha256})
    if not isinstance(design, dict) or design.get("schema") != SCHEMA:
        _fail("Unsupported architecture design schema")
    try:
        expected = _derive(design["evaluation"]["inventory"], design["training"]["candidate_inventories"] or None,
            design["common_limits"]["context_utf8_bytes"])
        if canonical(design) != canonical(expected):
            _fail("Architecture design differs from its immutable public inventory, two-arm policy, equal budgets or preparation status")
    except (KeyError, TypeError) as exc:
        raise ArchitecturePlanError("Malformed architecture design contract") from exc
    return design


def inspect_readiness(design, evidence_refs=None):
    """Inspect bound evidence without claiming an unimplemented live verifier exists.

    Public inventory scope is verifiable here. Other receipt files are hashed,
    never trusted for their declared switches, counts, success or ready flags.
    A future live runtime verifier is required to substantiate those mechanisms.
    """
    reference = _reference(design)
    value = load_architecture_design(reference["path"], reference["sha256"])
    if evidence_refs is None:
        evidence_refs = {}
    if not isinstance(evidence_refs, dict) or set(evidence_refs) - set(REQUIREMENTS):
        _fail("Readiness evidence contains unknown requirements or declared switches")
    evidence = {name: _reference(ref) for name, ref in evidence_refs.items()}
    inventory_ref = value["evaluation"]["inventory"]
    if "full_target_inventory" in evidence and evidence["full_target_inventory"] != inventory_ref:
        _fail("Readiness target inventory differs from the fixed full 500-task source")
    checks = []
    for name, requirement in REQUIREMENTS.items():
        if name == "full_target_inventory":
            checks.append({"requirement": name, "status": "VERIFIED_PUBLIC_INVENTORY_BINDING",
                "evidence": inventory_ref, "detail": "Exactly 500 unique sorted public evaluation identities and the pinned source file bytes were verified."})
        else:
            reason = requirement
            if name == "training_enrollment" and not value["training"]["candidate_inventories"]:
                reason = "No training candidate inventory is bound. " + reason
            checks.append({"requirement": name, "status": "HASH_BOUND_UNVERIFIED" if name in evidence else "MISSING_EVIDENCE",
                "evidence": evidence.get(name), "detail": reason,
                "pending_reason": "A hash-bound receipt is not live integration verification. " + reason if name in evidence else reason})
    return {"schema": READINESS_SCHEMA, "design": reference, "status": STATUS,
        "design_status": value["status"], "checks": checks,
        "pending_reasons": [{"requirement": row["requirement"], "reason": row["pending_reason"]}
            for row in checks if "pending_reason" in row],
        "evaluation_tasks": EVALUATION_COUNT, "planned_cells": EVALUATION_COUNT * 2,
        "training_candidate_tasks": value["training"]["candidate_task_count"],
        "live_integration_verified": False, "actual_tokens": None, "actual_cost": None,
        "model_calls": 0, "grader_calls": 0, "training_runs": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--evaluation-inventory", type=Path, required=True)
    build.add_argument("--evaluation-sha256", required=True)
    build.add_argument("--training-inventory", type=Path, action="append", default=[])
    build.add_argument("--training-sha256", action="append", default=[])
    build.add_argument("--context-budget-bytes", type=int, default=DEFAULT_CONTEXT_BYTES)
    build.add_argument("--output", type=Path, required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--design", type=Path, required=True)
    inspect.add_argument("--design-sha256", required=True)
    inspect.add_argument("--evidence-refs", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        if len(args.training_inventory) != len(args.training_sha256):
            parser.error("Each training inventory requires its own --training-sha256")
        result = build_architecture_design({"path": str(args.evaluation_inventory.absolute()), "sha256": args.evaluation_sha256},
            training_inventory=[{"path": str(path.absolute()), "sha256": digest}
                for path, digest in zip(args.training_inventory, args.training_sha256)] or None,
            context_budget_bytes=args.context_budget_bytes, output=args.output.absolute())
    else:
        evidence = _json(args.evidence_refs.read_bytes()) if args.evidence_refs else None
        result = inspect_readiness({"path": str(args.design.absolute()), "sha256": args.design_sha256}, evidence)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
