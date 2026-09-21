"""Trusted public-trace capture, reflection export and verified bank publication.

This module never executes a repository command, launches a model, or invokes a
grader. The manager authenticates native execution. Hashes bind its immutable
records; they do not independently prove native worker freshness. Reflection
JSON is an untrusted proposal, never verification evidence.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import fcntl

from enterprise_memory.trimem.accounting import canonical_bytes
from enterprise_memory.trimem.native_architecture_context import _public_copy
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph, COMPLETED, ACTIVE
import trimem_skhynix_architecture_memory as memory
import trimem_skhynix_architecture_broker as broker_module
from trimem_skhynix_architecture_dataset import load_architecture_rows
from trimem_skhynix_architecture_run import load_experiment, EMPTY_BANK_SHA
import trimem_skhynix_host_profile as host_profile

SCHEMA = "skhynix/native-architecture-learning/1.0"
REFLECTION_SCHEMA = "skhynix/native-architecture-public-reflection/2.0"
PROPOSALS_SCHEMA = "skhynix/native-architecture-reflection-proposals/1.0"
LEARNING_VERSION = 2
CAPTURE_POLICY = "ALL_PUBLIC_RED_GREEN_AND_SEMANTIC_COMPLETION_AND_TERMINAL_ACTIVE_GLOBAL_PREFIXES"
PROJECTION_POLICY = "SHARED_ROWS_EXACT_REQUESTS_AND_MUTATING_RESULTS_OMIT_NONCERTIFYING_READ_OUTPUTS"
CLAIM_SCOPE = "THEN_OBSERVED_PUBLIC_WORKFLOW_AT_CHECKPOINT_NOT_FINAL_OR_OFFICIAL_REPAIR"
TRAINING_COUNT, EVALUATION_COUNT = 24, 500
SCALE_TRAINING_COUNTS = (24, 120, 240)
SCALE_DEVELOPMENT_COUNT, SCALE_FINAL_COUNT = 60, 500
SCALE_DATASET_SCHEMA = "skhynix/pdf-architecture-scale-dataset/1.0"
MAX_PROPOSALS, MAX_REFLECTION_BYTES = 24, 196608


class LearningError(ValueError):
    pass


def _fail(message):
    raise LearningError(message)


def _fields(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        _fail(label + " fields differ")


def _reference(value):
    path = memory._check_ref(value)
    return {"path": str(path), "sha256": value["sha256"]}


def _execution(reference):
    reference = _reference(reference)
    config = load_experiment(reference["path"])
    if (config.get("phase") != "TRAINING_RUNTIME" or
            config.get("training_memory_policy") != "COLD_START_NATIVE_TRACES_THEN_OFFLINE_GATE_A_AND_GATE_B"):
        _fail("Only explicitly frozen cold-start training execution may feed learning")
    return reference, config


def _public_dataset(reference):
    reference = _reference(reference)
    if memory._read(reference["path"]).get("schema") == SCALE_DATASET_SCHEMA:
        from trimem_skhynix_architecture_scale_dataset import load_scale_rows
        return load_scale_rows(reference["path"], expected_sha256=reference["sha256"])
    return load_architecture_rows(reference["path"], expected_sha256=reference["sha256"])


def _public_tasks(targets, rows):
    tasks = {}
    for target in targets:
        statement = rows[target["instance_id"]]["problem_statement"].strip()
        public = {"task_id": target["target_id"], "repository": target["repository"],
            "commit": target["base_commit"], "instruction": statement}
        if (public["task_id"] in tasks or
                memory._descriptor(public)["instruction_sha256"] != target["instruction_sha256"]):
            _fail("Public task identity or instruction binding differs")
        tasks[public["task_id"]] = public
    return tasks


def _scale_enrollment(dataset, references, configs):
    targets, rows, manifest = _public_dataset(dataset)
    train = [row for row in targets if row["role"] == "TRAINING"]
    evaluation = [row for row in targets if row["role"] == "EVALUATION"]
    if (manifest.get("schema") != SCALE_DATASET_SCHEMA or len(train) not in SCALE_TRAINING_COUNTS or
            len(evaluation) != SCALE_DEVELOPMENT_COUNT + SCALE_FINAL_COUNT or len(targets) != len(train) + len(evaluation) or
            manifest.get("training_count") != len(train) or manifest.get("evaluation_count") != len(evaluation) or
            sum(row.get("evaluation_scope") == "DEVELOPMENT" for row in evaluation) != SCALE_DEVELOPMENT_COUNT or
            sum(row.get("evaluation_scope") == "FINAL" for row in evaluation) != SCALE_FINAL_COUNT):
        _fail("Scale learning requires an exact cumulative 24/120/240 and disjoint dev60/final500 authority")
    tasks = _public_tasks(targets, rows)
    train_ids = {row["target_id"] for row in train}
    eval_ids = {row["target_id"] for row in evaluation}
    owners, membership, source_datasets, covered = {}, {}, {}, set()
    for reference, config in zip(references, configs):
        if any(config.get(key) != configs[0].get(key) for key in
                ("org_id", "model", "authentication", "limits", "training_memory_policy")):
            _fail("Cumulative source organisation, model or task budget differs")
        source_ref = _reference(config["dataset_manifest"])
        if source_ref["sha256"] not in source_datasets:
            source_datasets[source_ref["sha256"]] = _public_dataset(source_ref)
        source_targets, source_rows, source_manifest = source_datasets[source_ref["sha256"]]
        source_tasks = _public_tasks(source_targets, source_rows)
        source_train = [row for row in source_targets if row["role"] == "TRAINING"]
        source_eval = [row for row in source_targets if row["role"] == "EVALUATION"]
        ids = {row["target_id"] for row in source_train}
        ranks = config.get("training_owner_by_instance")
        if (not ids or not ids <= train_ids or not {row["target_id"] for row in source_eval} <= eval_ids or
                any(task_id not in tasks or task != tasks[task_id] for task_id, task in source_tasks.items()) or
                not isinstance(ranks, dict) or set(ranks) != {row["instance_id"] for row in source_train} or
                any(type(rank) is not int or rank not in (1, 2) for rank in ranks.values())):
            _fail("Prior execution descriptors or owners are not an exact cumulative scope subset")
        for row in source_train:
            owner = "architecture-contributor-" + str(ranks[row["instance_id"]])
            if row["target_id"] in owners and owners[row["target_id"]] != owner:
                _fail("Stable source owner changed across cumulative executions")
            owners[row["target_id"]] = owner
        eligible = ids
        if config.get("scale_authority_reference") is not None:
            from trimem_skhynix_architecture_run import execution_enrollment
            authority = execution_enrollment(config, source_manifest)
            if authority is None or not authority["purpose"].startswith("TRAINING_"):
                _fail("Cumulative source execution lacks its exact training subset authority")
            eligible = set(authority["task_ids"])
            if not eligible <= ids:
                _fail("Execution training subset is outside its public dataset")
        membership[reference["sha256"]] = sorted(eligible)
        covered.update(eligible)
    if covered != train_ids:
        _fail("Cumulative learning sources are not all enrolled in the bound executions")
    return targets, tasks, owners, membership


def initialize_learning(root, *, execution_references, dataset_reference=None):
    """Bind default 24/500 or an explicit cumulative source/dev/final authority.

    Earlier execution scopes may be exact subsets. Their task identity, stable
    owner and original execution configuration are retained during capture.
    """
    root = memory._path(root)
    if not isinstance(execution_references, (list, tuple)) or not 1 <= len(execution_references) <= 24:
        _fail("Learning requires a bounded explicit list of frozen execution configurations")
    references, configs = zip(*(_execution(ref) for ref in execution_references))
    if len({ref["path"] for ref in references}) != len(references):
        _fail("Duplicate training execution configuration")
    first = configs[0]
    if dataset_reference is not None:
        dataset = _reference(dataset_reference)
        targets, tasks, source_owners, membership = _scale_enrollment(dataset, references, configs)
        return _initialize_enrollment(root, references, first, dataset, targets, tasks, source_owners,
            extra={"scale_authority": {"training_count": len(source_owners),
                "development_count": SCALE_DEVELOPMENT_COUNT, "final_evaluation_count": SCALE_FINAL_COUNT,
                "execution_training_tasks": membership}})
    if any(any(config.get(key) != first.get(key) for key in
            ("dataset_manifest", "org_id", "training_owner_by_instance")) for config in configs):
        _fail("Training configurations disagree on dataset, organisation or stable owners")
    dataset = _reference(first["dataset_manifest"])
    targets, rows, manifest = load_architecture_rows(dataset["path"], expected_sha256=dataset["sha256"])
    train = [row for row in targets if row["role"] == "TRAINING"]
    evaluation = [row for row in targets if row["role"] == "EVALUATION"]
    if (len(train) != TRAINING_COUNT or len(evaluation) != EVALUATION_COUNT or
            len(targets) != TRAINING_COUNT + EVALUATION_COUNT):
        _fail("Learning scope must preserve exactly enrolled 24 sources and every one of the 500 targets")
    owners = first.get("training_owner_by_instance")
    if (not isinstance(owners, dict) or set(owners) != {row["instance_id"] for row in train} or
            any(type(rank) is not int or rank not in (1, 2) for rank in owners.values())):
        _fail("Training needs the exact frozen source-to-contributor mapping")
    tasks = _public_tasks(targets, rows)
    source_owners = {row["target_id"]: "architecture-contributor-" + str(owners[row["instance_id"]]) for row in train}
    return _initialize_enrollment(root, references, first, dataset, targets, tasks, source_owners)


def _initialize_enrollment(root, references, first, dataset, targets, tasks, source_owners, *, extra=None):
    train = [row for row in targets if row["role"] == "TRAINING"]
    evaluation = [row for row in targets if row["role"] == "EVALUATION"]
    training_tasks = [tasks[row["target_id"]] for row in train]
    evaluation_tasks = [tasks[row["target_id"]] for row in evaluation]
    enrollment = {"schema": SCHEMA, "learning_version": LEARNING_VERSION,
        "capture_policy": CAPTURE_POLICY, "reflection_projection_policy": PROJECTION_POLICY,
        "claim_scope": CLAIM_SCOPE, "dataset_reference": dataset, "execution_references": list(references),
        "org_id": first["org_id"], "source_owners": source_owners,
        "training_tasks": {task["task_id"]: task for task in training_tasks},
        "evaluation_descriptors": [memory._descriptor(task) for task in evaluation_tasks],
        "implementation_sha256": {"learning": memory._file_hash(__file__), "memory": memory._file_hash(memory.__file__)},
        "reflection_worker_freshness": "MANAGER_ATTESTATION_REQUIRED_NOT_PROVEN_BY_DECLARED_FLAGS"}
    if extra:
        enrollment.update(extra)
    if (root / "learning-enrollment.json").exists():
        if memory._read(root / "learning-enrollment.json") != enrollment:
            _fail("Learning enrollment is immutable")
        return memory._ref(root / "learning-enrollment.json")
    memory.initialize_training_memory(root, org_id=first["org_id"], training_tasks=training_tasks, evaluation_tasks=evaluation_tasks)
    memory._write(root / "learning-enrollment.json", enrollment, fresh=True)
    reference = memory._ref(root / "learning-enrollment.json")
    memory._write(root / "learning-enrollment.ref.json", reference, fresh=True)
    memory._write(root / "learning-state.json", {"cells": {}, "reflections": {}, "ingestions": {}}, fresh=True)
    return reference


@contextmanager
def _session(root, *, mutable=True):
    root = memory._path(root)
    with (root / "learning.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX if mutable else fcntl.LOCK_SH)
        try:
            reference = _reference(memory._read(root / "learning-enrollment.ref.json"))
            enrollment = memory._read(reference["path"])
            if (enrollment.get("learning_version") != LEARNING_VERSION or enrollment.get("capture_policy") != CAPTURE_POLICY or
                    enrollment.get("reflection_projection_policy") != PROJECTION_POLICY or enrollment.get("claim_scope") != CLAIM_SCOPE):
                _fail("Learning version or checkpoint policy differs; initialize a separate v2 authority")
            if enrollment["implementation_sha256"] != {"learning": memory._file_hash(__file__), "memory": memory._file_hash(memory.__file__)}:
                _fail("Learning or memory implementation changed after enrollment")
            if mutable and (root / "learning-frozen.json").exists():
                _fail("Published learning authority is immutable")
            _reference(enrollment["dataset_reference"])
            configs = [_execution(ref)[1] for ref in enrollment["execution_references"]]
            if "scale_authority" in enrollment:
                scale = enrollment["scale_authority"]
                membership = scale.get("execution_training_tasks", {})
                if (set(membership) != {ref["sha256"] for ref in enrollment["execution_references"]} or
                        scale.get("training_count") != len(enrollment["training_tasks"]) or
                        scale.get("training_count") not in SCALE_TRAINING_COUNTS or
                        scale.get("development_count") != SCALE_DEVELOPMENT_COUNT or
                        scale.get("final_evaluation_count") != SCALE_FINAL_COUNT or
                        any(not isinstance(ids, list) or ids != sorted(set(ids)) or
                            not set(ids) <= set(enrollment["training_tasks"]) for ids in membership.values()) or
                        set().union(*(set(ids) for ids in membership.values())) != set(enrollment["training_tasks"])):
                    _fail("Cumulative execution membership or counts differ from enrollment")
            scope = memory._read(root / "scope.json")
            memory._validate_scope(scope)
            if (scope["org_id"] != enrollment["org_id"] or scope["phase"] != "TRAINING" or
                    scope["training_tasks"] != sorted((memory._descriptor(task) for task in enrollment["training_tasks"].values()), key=lambda row: row["task_id"]) or
                    scope["evaluation_tasks"] != sorted(enrollment["evaluation_descriptors"], key=lambda row: row["task_id"])):
                _fail("Private memory authority scope differs from learning enrollment")
            state = memory._read(root / "learning-state.json")
            _fields(state, "cells reflections ingestions", "Learning state")
            yield root, enrollment, state, configs
            if mutable:
                memory._write(root / "learning-state.json", state)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _source(root, enrollment, configs, cell_path):
    path = memory._path(cell_path)
    choices = {memory._path(Path(config["run_root"]) / "cells" / "TRAINING" / task_id / arm / "cell.json"): (task_id, arm)
        for ref, config in zip(enrollment["execution_references"], configs)
        for task_id in enrollment.get("scale_authority", {}).get("execution_training_tasks", {}).get(ref["sha256"], enrollment["training_tasks"])
        for arm in ("BASELINE", "PDF_MEMORY")}
    if path not in choices:
        _fail("Cell path is outside every explicitly enrolled training execution")
    task_id, arm = choices[path]
    cell = memory._read(path)
    if memory._hash(cell) != path.with_suffix(".sha256").read_text().strip():
        _fail("Training cell configuration changed")
    if (cell.get("schema") != "skhynix/pdf-architecture-execution/1.0" or cell.get("phase") != "TRAINING" or
            cell.get("arm") != arm or cell.get("task_public") != enrollment["training_tasks"][task_id] or
            cell.get("org_id") != enrollment["org_id"] or cell.get("owner_user_id") != enrollment["source_owners"][task_id] or
            cell.get("bank_sha256") != EMPTY_BANK_SHA or cell.get("bank_reference") is not None or
            str(memory._path(cell.get("broker_root"))) != str(path.parent / "broker")):
        _fail("Training cell task, owner, cold-start bank or broker binding differs")
    config_ref = next((ref for ref in enrollment["execution_references"] if ref["path"] == cell.get("experiment_config")), None)
    if config_ref is None:
        _fail("Cell execution configuration is not an enrolled immutable execution")
    if ("scale_authority" in enrollment and
            task_id not in enrollment["scale_authority"]["execution_training_tasks"][config_ref["sha256"]]):
        _fail("Source task was never enrolled in its original smaller execution scope")
    config = _execution(config_ref)[1]
    if path != memory._path(Path(config["run_root"]) / "cells" / "TRAINING" / task_id / arm / "cell.json"):
        _fail("Cell is outside its bound execution root")
    broker_root = path.parent / "broker"
    # No recovery or source mutation is allowed during post-run capture.
    with (broker_root / "broker.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        try:
            if (broker_root / "pending.json").exists():
                _fail("Training broker has an unfinished or unrecovered action")
            broker = broker_module.ArchitectureBroker(broker_root, workspace=SimpleNamespace(),
                configuration_sha256=memory._hash(config), bank_sha256=EMPTY_BANK_SHA)
            state, events = broker._load()
            if broker.task != cell["task_public"] or broker.arm != arm or state["status"] != "SUBMITTED" or state["submission"] is None:
                _fail("Capture requires the bound sealed public training task")
            graph = ShortTermWorkingGraph.from_snapshot(state["graph"])
            if graph.task_id != task_id or graph.repository != broker.task["repository"] or graph.objective != broker.task["instruction"].strip():
                _fail("Terminal graph differs from public training task")
            history = memory._public_trace(memory._descriptor(broker.task), state["history"]) if state["history"] else []
            _public_copy(state["submission"])
            refs = {name: memory._ref(broker_root / name) for name in
                ("manifest.json", "manifest.sha256", "initial-state.json", "state.json", "events.jsonl", "submission.json", "submission.diff")}
            refs["cell.json"] = memory._ref(path)
            execution_observed = any("thread_id" in worker for worker in state["workers"].values())
            return cell, graph, history, events, state["submission"], refs, execution_observed
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _checked_cell_receipt(reference):
    value = memory._read(memory._check_ref(reference))
    if value.get("learning_version") != LEARNING_VERSION or value.get("capture_policy") != CAPTURE_POLICY:
        _fail("Captured source belongs to a different learning version or checkpoint policy")
    for ref in value.get("source_references", {}).values():
        _reference(ref)
    return value


def _checkpoint_specs(graph, history, events, submission):
    """Enumerate all actual checkpoints; outcomes never select which attempts survive."""
    specs, empty = [], []
    for node in sorted(graph.nodes.values(), key=lambda item: item.node_id):
        selected = [row for row in history if row["active_node_id"] == node.node_id]
        completions = [row for row in selected if row["tool"] == "complete_subtask" and row["status"] == "success"]
        if node.status == COMPLETED:
            if len(completions) != 1:
                _fail("Completed subgoal must bind exactly one actual semantic completion")
            completion = completions[0]
            matching = [event for event in events if event.get("history_row") == completion]
            if len(matching) != 1:
                _fail("Semantic completion has no unique original broker event")
            event = matching[0]
            request = event.get("request", {}).get("request", {})
            summary = completion["request_payload"]["arguments"].get("evidence")
            prior = {row["step_no"]: row for row in selected if row["step_no"] < completion["step_no"]}
            steps = request.get("evidence_steps")
            if (event["kind"] != "WORKER_ACTION" or request.get("op") != "complete_subgoal" or
                    event["response"].get("ok") is not True or event["response"].get("step_no") != completion["step_no"] or
                    event["response"].get("result", {}).get("completed") is not True or
                    completion["result_payload"].get("completed") is not True or
                    summary != completion["result_payload"].get("evidence") or request.get("summary") != summary or
                    not isinstance(steps, list) or not steps or any(type(step) is not int or step not in prior for step in steps) or
                    len(steps) != len(set(steps)) or any(row["step_no"] > completion["step_no"] for row in selected)):
                _fail("Semantic completion differs from its actual successful broker transition")
            support = [{"step_no": step, "result_sha256": prior[step]["result"]["sha256"]} for step in steps]
            if not any(item.supports_completion and item.kind == "PUBLIC_TOOL_REFERENCES" and
                    item.summary == summary and item.payload_hash == memory._hash(support) for item in node.completion_evidence):
                _fail("Semantic completion evidence differs from the terminal graph")
        elif completions:
            _fail("Successful semantic completion differs from terminal node status")
        for row in selected:
            outcome = memory._test_outcome(row)
            if outcome in ("RED", "GREEN"):
                specs.append((node, row["step_no"], "PUBLIC_TEST_OBSERVATION", False,
                    "Public test observation for " + node.objective + "; step " + str(row["step_no"]) + ": " + outcome +
                    ". This describes only the observed checkpoint, not semantic completion or a final repair.", outcome))
        if node.status == COMPLETED:
            specs.append((node, completion["step_no"], "COMPLETED_SUBGOAL", True,
                "Semantic completion at step " + str(completion["step_no"]) + ": " + summary +
                ". Public verification is limited to this checkpoint; no final repair is certified.", None))
        elif node.status == ACTIVE:
            if not selected:
                empty.append({"node_id": node.node_id, "kind": "TERMINAL_ACTIVE", "status": "NO_PUBLIC_ATTEMPTS"})
            else:
                specs.append((node, history[-1]["step_no"], "TERMINAL_ACTIVE", False,
                    "Terminal partial attempt; semantic subgoal not completed. " + submission["summary"], None))
    return sorted(specs, key=lambda item: (item[1], item[0].node_id, item[2])), empty


def _checkpoint(spec, history, events):
    node, cutoff, kind, completed, summary, outcome = spec
    prefix = [row for row in history if row["step_no"] <= cutoff]
    boundary = [event for event in events if event.get("history_row") == prefix[-1]]
    if len(boundary) != 1:
        _fail("Checkpoint must bind an exact original public broker event")
    event = events[-1] if kind == "TERMINAL_ACTIVE" else boundary[0]
    later = [row for row in history if row["step_no"] > cutoff]
    commands = [row for row in prefix if row["active_node_id"] == node.node_id and row["tool"] == "run_command"]
    verifier = commands[-1] if commands else None
    verification_step = None
    if (verifier is not None and memory._test_outcome(verifier) in ("RED", "GREEN") and
            not any(row["tool"] in memory.MUTATING and row["step_no"] > verifier["step_no"] for row in prefix)):
        verification_step = verifier["step_no"]
    value = {"kind": kind, "node_id": node.node_id, "cutoff_step": cutoff, "semantic_completion": completed,
        "public_test_outcome": outcome, "verification_step": verification_step, "claim_scope": CLAIM_SCOPE,
        "prefix_row_count": len(prefix), "prefix_sha256": memory._hash(prefix),
        "full_history_row_count": len(history), "full_history_sha256": memory._hash(history),
        "later_row_count": len(later), "later_history_sha256": memory._hash(later),
        "later_mutating_steps": [{"step_no": row["step_no"], "active_node_id": row["active_node_id"],
            "tool": row["tool"], "status": row["status"], "request": row["request"], "result": row["result"]}
            for row in later if row["tool"] in memory.MUTATING],
        "event_sequence": event["sequence"], "event_sha256": event["sha256"],
        "event_state_after_sha256": event["state_after_sha256"], "sealed_event_tail_sha256": events[-1]["sha256"]}
    stamp = datetime.fromtimestamp(event["at"], timezone.utc).isoformat()
    return value, prefix, summary, stamp


def capture_cell(root, cell_config_path):
    """Capture terminal public attempts, independent of any official outcome."""
    with _session(root) as (root, enrollment, registry, configs):
        identity = memory._hash({"cell_path": str(memory._path(cell_config_path))})
        if identity in registry["cells"]:
            _checked_cell_receipt(registry["cells"][identity])
            return dict(registry["cells"][identity])
        path = root / "learning-cells" / (identity + ".json")
        if path.exists():
            reference = memory._ref(path)
            recovered = _checked_cell_receipt(reference)
            if recovered.get("cell_path") != str(memory._path(cell_config_path)):
                _fail("Interrupted capture receipt belongs to a different source")
            registry["cells"][identity] = reference
            return reference
        value = {"schema": SCHEMA, "learning_version": LEARNING_VERSION, "capture_policy": CAPTURE_POLICY,
            "operation": "CAPTURE_CELL", "cell_path": str(memory._path(cell_config_path)),
            "source_references": {}, "captures": [], "empty_checkpoints": [], "failures": [], "gate_b_promotions": 0}
        try:
            cell, graph, history, events, submission, refs, execution_observed = _source(root, enrollment, configs, cell_config_path)
            value.update(source_references=refs, task_id=cell["task_public"]["task_id"], owner_user_id=cell["owner_user_id"],
                agent_completed=submission["agent_completed"], public_tool_rows=sum(row["tool"] in broker_module.TOOLS for row in history),
                source_execution_observed=execution_observed, terminal_reason=submission["reason"])
            if "INFRASTRUCTURE" in submission["reason"] or "COMMISSIONING" in submission["reason"]:
                value["source_execution_observed"] = False
            specs, value["empty_checkpoints"] = _checkpoint_specs(graph, history, events, submission)
            for spec in specs:
                node = spec[0]
                try:
                    checkpoint, prefix, summary, stamp = _checkpoint(spec, history, events)
                    receipt = memory.capture_training_trace(root, cell["task_public"], prefix,
                        owner_user_id=cell["owner_user_id"], active_node_id=node.node_id,
                        subgoal=node.objective + " (subgoal " + node.node_id + "; " + spec[2] + " at step " + str(spec[1]) + ")", summary=summary,
                        verification_step=checkpoint["verification_step"], created_at=stamp)
                    value["captures"].append({"receipt": receipt, "semantic_completion": spec[3],
                        "verification_step": checkpoint["verification_step"], "checkpoint": checkpoint})
                except (ValueError, RuntimeError) as exc:
                    value["failures"].append({"node_id": node.node_id, "cutoff_step": spec[1], "kind": spec[2],
                        "error_type": type(exc).__name__, "reason": str(exc)[:1000]})
            value["status"] = "PARTIAL_CAPTURE_FAILURE" if value["failures"] else "CAPTURED" if value["captures"] else "NO_PUBLIC_ATTEMPTS"
        except (ValueError, RuntimeError, OSError, KeyError) as exc:
            value["status"] = "INVALID_SOURCE"
            value["failures"].append({"error_type": type(exc).__name__, "reason": str(exc)[:1000]})
        memory._write(path, value, fresh=True)
        registry["cells"][identity] = memory._ref(path)
        return dict(registry["cells"][identity])


def make_capture_hook(learning_root):
    """Cohort hook. public_result is intentionally never inspected or persisted."""
    def hook(cell_config_path, public_result, receipt_directory):
        reference = capture_cell(learning_root, cell_config_path)
        value = {"schema": SCHEMA, "operation": "COHORT_CAPTURE", "capture_receipt": reference}
        path = memory._path(receipt_directory) / "learning-capture.json"
        if path.exists():
            if memory._read(path) != value:
                _fail("Existing cohort learning receipt differs")
        else:
            memory._write(path, value, fresh=True)
        return memory._ref(path)
    return hook


def capture_existing_sources(root, *, cell_references, output_path):
    """Revalidate retained sealed public traces into a new authority; never solve or grade."""
    references = [_reference(ref) for ref in cell_references]
    if not references or len({ref["path"] for ref in references}) != len(references):
        _fail("Existing sources must be unique immutable cell configurations")
    references.sort(key=lambda ref: ref["path"])
    output = memory._path(output_path)
    enrollment = memory._ref(memory._path(root) / "learning-enrollment.json")
    if output.exists():
        prior = memory._read(output)
        if prior.get("cell_references") != references or prior.get("enrollment_reference") != enrollment:
            _fail("Existing source import receipt belongs to another immutable input")
        for item in prior["sources"]:
            _checked_cell_receipt(item["capture_reference"])
        return memory._ref(output)
    sources = []
    for reference in references:
        captured = capture_cell(root, reference["path"])
        receipt = _checked_cell_receipt(captured)
        sources.append({"cell_reference": reference, "capture_reference": captured,
            "status": receipt["status"], "task_id": receipt.get("task_id"), "failures": receipt["failures"]})
    value = {"schema": SCHEMA, "operation": "CAPTURE_EXISTING_SOURCES", "enrollment_reference": enrollment,
        "cell_references": references, "sources": sources,
        "status": "COMPLETE" if all(item["status"] in {"CAPTURED", "NO_PUBLIC_ATTEMPTS"} for item in sources) else "CAPTURE_FAILURE",
        "model_calls": 0, "solver_runs": 0, "official_grader_runs": 0, "official_outcomes_read": False}
    memory._write(output, value, fresh=True)
    return memory._ref(output)


def import_captured_sources(root, *, source_receipt_references, output_path):
    """Use original capture references only to locate fully revalidated public cells."""
    receipts = [_checked_cell_receipt(_reference(ref)) for ref in source_receipt_references]
    return capture_existing_sources(root, cell_references=[row["source_references"]["cell.json"] for row in receipts],
        output_path=output_path)


def _available_captures(root, registry):
    catalog = memory._read(root / "catalog.json")
    available = {}
    for ref in registry["cells"].values():
        source = _checked_cell_receipt(ref)
        if source["status"] == "INVALID_SOURCE":
            if source["captures"]:
                _fail("Invalid source contains untrusted captures")
            continue
        state = memory._read(source["source_references"]["state.json"]["path"])
        graph = ShortTermWorkingGraph.from_snapshot(state["graph"])
        cell = memory._read(source["source_references"]["cell.json"]["path"])
        history = memory._public_trace(memory._descriptor(cell["task_public"]), state["history"]) if state["history"] else []
        with Path(source["source_references"]["events.jsonl"]["path"]).open("rb") as stream:
            events = [broker_module.strict_json_loads(line) for line in stream if line.strip()]
        specs, empty = _checkpoint_specs(graph, history, events, state["submission"])
        if source["failures"] or len(specs) != len(source["captures"]) or source.get("empty_checkpoints") != empty:
            _fail("Captured checkpoint set differs from every actual test, completion and terminal attempt")
        for spec, item in zip(specs, source["captures"]):
            identity = item["receipt"]["capture_id"]
            capture_ref = catalog["captures"][identity]
            capture = memory._read(memory._check_ref(capture_ref))
            checkpoint, prefix, summary, stamp = _checkpoint(spec, history, events)
            if (item.get("checkpoint") != checkpoint or item["semantic_completion"] != spec[3] or
                    item["verification_step"] != checkpoint["verification_step"] or capture["history"] != prefix or
                    capture["task"] != memory._descriptor(cell["task_public"]) or capture["active_node_id"] != spec[0].node_id or
                    capture["owner_user_id"] != source["owner_user_id"] or capture["receipt"] != item["receipt"] or
                    capture["subgoal"] != spec[0].objective + " (subgoal " + spec[0].node_id + "; " + spec[2] + " at step " + str(spec[1]) + ")" or
                    capture["summary"] != summary or capture["created_at"] != stamp or
                    capture["verification_step"] != checkpoint["verification_step"]):
                _fail("Capture differs from its exact original checkpoint prefix")
            available[identity] = (capture_ref, capture, item, ref)
    return available


def _reflection_documents(root, enrollment, available, selected):
    """Pure public projection; original prefixes remain the verification authority."""
    owners, tasks, aliases, sources, trace_rows, mutations = {}, {}, {}, [], [], []
    row_indices, mutation_indices = {}, {}
    for number, identity in enumerate(selected, 1):
        ref, capture, item, cell_ref = available[identity]
        owner = capture["owner_user_id"]
        owners.setdefault(owner, "contributor-" + str(len(owners) + 1))
        task_id = capture["task"]["task_id"]
        tasks.setdefault(task_id, "task-" + str(len(tasks) + 1))
        task_alias = tasks[task_id]
        alias = "source-" + str(number)
        aliases[alias] = {"capture_id": identity, "capture_reference": ref,
            "cell_receipt_reference": cell_ref, "checkpoint_sha256": memory._hash(item["checkpoint"]),
            "task_id": task_id, "owner_user_id": owner}
        rows, omitted = [], []
        for original in capture["history"]:
            digest = memory._hash(original)
            if digest not in row_indices:
                row = {**original, "task_id": task_alias, "original_row_sha256": digest}
                if original["tool"] in {"read_file", "list_files", "search"}:
                    del row["result_payload"]
                    row["result_payload_omission"] = {"reason": "NONCERTIFYING_READ_OUTPUT_FULL_RESULT_RETAINED_IN_ORIGINAL_PREFIX",
                        "sha256": original["result"]["sha256"], "bytes": original["result"]["bytes"]}
                row_indices[digest] = len(trace_rows)
                trace_rows.append(row)
            rows.append(row_indices[digest])
            if "result_payload_omission" in trace_rows[rows[-1]]:
                omitted.append({"step_no": original["step_no"], **original["result"]})
        checkpoint = dict(item["checkpoint"])
        later = []
        for mutation in checkpoint.pop("later_mutating_steps"):
            digest = memory._hash({"task_id": task_id, **mutation})
            if digest not in mutation_indices:
                mutation_indices[digest] = len(mutations)
                mutations.append({"task_group": task_alias, **mutation})
            later.append(mutation_indices[digest])
        checkpoint["later_mutating_row_indices"] = later
        source_receipt = _checked_cell_receipt(cell_ref)
        sources.append({"source_alias": alias, "task_group": task_alias, "contributor_group": owners[owner],
            "repository": capture["task"]["repository"], "source_revision": capture["task"]["commit"],
            "active_node_id": capture["active_node_id"], "subgoal": capture["subgoal"],
            "summary": capture["summary"], "semantic_completion": item["semantic_completion"],
            "public_test_pass_observed": capture["receipt"]["succeeded"], "history_row_indices": rows,
            "checkpoint": checkpoint, "checkpoint_reference": {"capture_sha256": ref["sha256"],
                "cell_receipt_sha256": cell_ref["sha256"], "checkpoint_sha256": memory._hash(item["checkpoint"]),
                "sealed_state_sha256": source_receipt["source_references"]["state.json"]["sha256"],
                "broker_event_chain_sha256": source_receipt["source_references"]["events.jsonl"]["sha256"]},
            "omitted_read_outputs": {"count": len(omitted), "bytes": sum(row["bytes"] for row in omitted),
                "manifest_sha256": memory._hash(omitted)}})
    mapping = {"schema": SCHEMA, "learning_version": LEARNING_VERSION,
        "enrollment_sha256": memory._file_hash(root / "learning-enrollment.json"), "sources": aliases}
    public = {"schema": REFLECTION_SCHEMA, "publisher_map_sha256": memory._hash(mapping),
        "learning_version": LEARNING_VERSION, "claim_scope": CLAIM_SCOPE,
        "purpose": "Propose a common parameterized edit procedure only when actual independent public RED/edit/GREEN traces support the then-observed workflow; otherwise return proposals: []. Checkpoints from one task are not independent sources. No subgoal or final repair is certified by a test observation.",
        "worker_launch_requirement": {"fresh_native_worker": True, "fork_turns": "none", "model": host_profile.solver()["model"], "tools": []},
        "origin_attestation": "The manager must bind actual fresh-worker launch evidence separately; these requirements are not proof of execution.",
        "proposal_schema": PROPOSALS_SCHEMA, "required_preconditions": [memory.PRECONDITION],
        "proposal_fields": {"template": ["subgoal_signature", "parameters", "preconditions", "steps", "verification_command", "language"],
            "observations": ["source_alias", "bindings", "step_numbers", "red_step"]},
        "action_encoding": {"read_file": "read_file PATH", "replace_text": "replace_text PATH\nold_text: EXACT_OLD\nnew_text: EXACT_NEW",
            "write_file": "write_file PATH\ncontent: EXACT_CONTENT", "run_command": "run_command CANONICAL_JSON_ARGV"},
        "projection": {"policy": PROJECTION_POLICY,
            "history_encoding": "Each source history_row_indices selects exact ordered entries in shared trace_rows; indices are zero-based.",
            "later_mutations_encoding": "Checkpoint later_mutating_row_indices selects disclosure-only entries in later_mutations outside that prefix.",
            "verification_authority": "Original hash-bound complete prefix files, never this projection or a reflection claim.",
            "requests": "Every action request remains exact, including reads; all command and mutation results remain complete with original failure/truncation flags.",
            "omissions": "Only noncertifying read/search/list outputs are omitted. Their exact hashes and byte counts remain; no original prefix is changed.",
            "unique_trace_rows": len(trace_rows)},
        "trace_rows": _public_copy(trace_rows), "later_mutations": _public_copy(mutations), "sources": _public_copy(sources)}
    return public, mapping


def _retain_reflection(root, registry, public, mapping, output_path, max_bytes):
    if len(canonical_bytes(public)) + 1 > max_bytes:
        _fail("Exact projected command/action evidence exceeds reflection context cap; select fewer captures, never truncate certifying evidence")
    output = memory._path(output_path)
    private_path = root / "reflection-maps" / (memory._hash(mapping) + ".json")
    if not private_path.exists():
        memory._write(private_path, mapping, fresh=True)
    if output.exists():
        if memory._read(output) != public:
            _fail("Existing reflection export differs")
    else:
        memory._write(output, public, fresh=True)
    reference = memory._ref(output)
    registry["reflections"][reference["sha256"]] = {"public": reference, "private": memory._ref(private_path)}
    return reference


def export_reflection(root, output_path, *, capture_ids=None, max_bytes=MAX_REFLECTION_BYTES):
    """Share deterministic public rows; full original prefixes alone verify proposals."""
    if type(max_bytes) is not int or not 1024 <= max_bytes <= MAX_REFLECTION_BYTES:
        _fail("Reflection byte cap must stay within the common native context bound")
    with _session(root) as (root, enrollment, registry, configs):
        available = _available_captures(root, registry)
        selected = sorted(available) if capture_ids is None else sorted(capture_ids)
        if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(available):
            _fail("Reflection must select unique actual captured source attempts")
        public, mapping = _reflection_documents(root, enrollment, available, selected)
        return _retain_reflection(root, registry, public, mapping, output_path, max_bytes)


def ingest_proposals(root, proposal_reference, *, reflection_reference):
    """Treat reflection output as proposals; record every real verification failure."""
    with _session(root) as (root, enrollment, registry, configs):
        available = _available_captures(root, registry)
        proposal_reference, reflection_reference = _reference(proposal_reference), _reference(reflection_reference)
        identity = memory._hash({"proposal": proposal_reference, "reflection": reflection_reference})
        if identity in registry["ingestions"]:
            _reference(registry["ingestions"][identity])
            return dict(registry["ingestions"][identity])
        receipt_path = root / "learning-ingestions" / (identity + ".json")
        if receipt_path.exists():
            recovered = memory._read(receipt_path)
            if recovered.get("proposal_reference") != proposal_reference or recovered.get("reflection_reference") != reflection_reference:
                _fail("Interrupted proposal receipt belongs to different immutable inputs")
            registry["ingestions"][identity] = memory._ref(receipt_path)
            return dict(registry["ingestions"][identity])
        frozen_export = registry["reflections"].get(reflection_reference["sha256"])
        if frozen_export is None or frozen_export["public"] != reflection_reference:
            _fail("Proposal reflection export is not registered in this learning scope")
        reflection = memory._read(reflection_reference["path"])
        mapping = memory._read(memory._check_ref(frozen_export["private"]))
        if reflection["publisher_map_sha256"] != memory._hash(mapping):
            _fail("Reflection source alias mapping changed")
        response = {"schema": SCHEMA, "operation": "INGEST_PROPOSALS", "proposal_reference": proposal_reference,
            "reflection_reference": reflection_reference, "outcomes": [], "failures": [], "promotions_added": 0,
            "proposal_origin": "MANAGER_SUPPLIED_NATIVE_ORIGIN_NOT_ATTESTED_BY_THIS_HELPER"}
        before = set(memory._read(root / "catalog.json")["skills"])
        try:
            if Path(proposal_reference["path"]).stat().st_size > MAX_REFLECTION_BYTES:
                _fail("Reflection proposal exceeds the bounded JSON size")
            value = _public_copy(memory._read(proposal_reference["path"]))
            _fields(value, "schema reflection_sha256 proposals", "Reflection response")
            if (value["schema"] != PROPOSALS_SCHEMA or value["reflection_sha256"] != reflection_reference["sha256"] or
                    not isinstance(value["proposals"], list) or len(value["proposals"]) > MAX_PROPOSALS):
                _fail("Reflection schema, source binding or proposal count differs")
            for index, proposal in enumerate(value["proposals"]):
                try:
                    _fields(proposal, "template observations", "Parameterized proposal")
                    _fields(proposal["template"], "subgoal_signature parameters preconditions steps verification_command language", "Procedure template")
                    observations = proposal["observations"]
                    if not isinstance(observations, list) or not 2 <= len(observations) <= len(enrollment["training_tasks"]):
                        _fail("Promotion needs at least two actual independent source observations")
                    resolved = []
                    for observation in observations:
                        _fields(observation, "source_alias bindings step_numbers red_step", "Source observation")
                        source = mapping["sources"].get(observation["source_alias"])
                        if source is None or source["capture_id"] not in available or source["capture_reference"] != available[source["capture_id"]][0]:
                            _fail("Proposed observation is outside its immutable reflection source scope")
                        resolved.append(source)
                    if min(len({source["task_id"] for source in resolved}), len({source["owner_user_id"] for source in resolved})) < 2:
                        _fail("Promotion requires different captured source tasks and stable owners")
                    declaration = memory.declare_skill_proposal(root, proposal["template"], training_task_ids=sorted({source["task_id"] for source in resolved}))
                    verified = [memory.verify_skill_observation(root, declaration["proposal_id"], source["capture_id"],
                        bindings=observation["bindings"], step_numbers=observation["step_numbers"], red_step=observation["red_step"])
                        for source, observation in zip(resolved, observations)]
                    promoted = memory.promote_verified_skill(root, declaration["proposal_id"], [row["observation_id"] for row in verified])
                    response["outcomes"].append({"index": index, "status": "ALREADY_PROMOTED" if promoted["skill_id"] in before else "PROMOTED",
                        "promotion": promoted, "observations": verified})
                except (ValueError, RuntimeError, KeyError, TypeError) as exc:
                    response["outcomes"].append({"index": index, "status": "REJECTED", "error_type": type(exc).__name__, "reason": str(exc)[:1000]})
        except (ValueError, RuntimeError, KeyError, TypeError) as exc:
            response["failures"].append({"error_type": type(exc).__name__, "reason": str(exc)[:1000]})
        response["promotions_added"] = len(set(memory._read(root / "catalog.json")["skills"]) - before)
        response["status"] = "VALIDATION_FAILURE" if response["failures"] else "PROCESSED"
        path = receipt_path
        memory._write(path, response, fresh=True)
        registry["ingestions"][identity] = memory._ref(path)
        return dict(registry["ingestions"][identity])


def freeze_published_bank(root, output_path):
    """Account for every source, including legitimate empty attempts; require Gate B > 0."""
    with _session(root) as (root, enrollment, registry, configs):
        _available_captures(root, registry)
        receipts = [_checked_cell_receipt(ref) for ref in registry["cells"].values()]
        attempted = {row.get("task_id") for row in receipts if row["status"] in ("CAPTURED", "NO_PUBLIC_ATTEMPTS") and row.get("source_execution_observed")}
        captured = {row.get("task_id") for row in receipts if row["status"] == "CAPTURED" and row["captures"]}
        if attempted != set(enrollment["training_tasks"]):
            _fail("Publication requires validated actual attempts from all enrolled training sources")
        if not registry["ingestions"]:
            _fail("Publication requires actual reflection proposal validation receipts")
        for group in (registry["reflections"].values(),):
            for references in group:
                _reference(references["public"])
                _reference(references["private"])
        for ref in registry["ingestions"].values():
            record = memory._read(memory._check_ref(ref))
            _reference(record["proposal_reference"])
            _reference(record["reflection_reference"])
        path = memory._path(output_path).with_name(Path(output_path).name + ".learning.json")
        if path.exists():
            _fail("Refusing to overwrite an existing learning publication")
        if "scale_authority" in enrollment:
            with memory._writer(root) as (_, scope, catalog, store):
                counts = memory._validate_authority(store, catalog, scope)
                if not counts["skill"]:
                    _fail("The frozen bank requires at least one actually promoted Gate B skill")
                if not all((counts["episode"], counts["knowledge"], len(catalog["edges"]))):
                    _fail("Scale bank publication requires actual L1 episodes and L2 nodes and edges")
        bank = memory.freeze_training_bank(root, output_path, require_verified_skill=True)
        publication = {"schema": SCHEMA, "learning_version": LEARNING_VERSION, "capture_policy": CAPTURE_POLICY,
            "claim_scope": CLAIM_SCOPE, "operation": "PUBLISH_TRAINED_BANK", "bank": bank,
            "enrollment_reference": memory._ref(root / "learning-enrollment.json"),
            "cell_receipts": list(registry["cells"].values()), "reflection_exports": list(registry["reflections"].values()),
            "ingestion_receipts": list(registry["ingestions"].values()), "actual_training_sources": len(attempted),
            "sources_with_captures": len(captured), "sources_without_public_tool_evidence": len(attempted - captured),
            "official_grader_payloads_read": 0, "reflection_origin_attestation": "MANAGER_RESPONSIBILITY_SEPARATE_FROM_VERIFIED_PUBLIC_TOOL_SUPPORT"}
        memory._write(path, publication, fresh=True)
        reference = memory._ref(path)
        memory._write(root / "learning-frozen.json", reference, fresh=True)
        return {**bank, "publication_reference": reference}
