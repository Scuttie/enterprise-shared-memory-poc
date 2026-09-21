"""Read-only evaluation audit and separate private post-grade Gate A capture.

No grader/private gold row is read, no repository tool or model is executed,
and no evaluation record is admitted to the immutable training retrieval bank.
Native receipts are checked against their actual recorded event/prompt bytes.
The trusted manager remains the authentication boundary for these local files.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import fcntl

from enterprise_memory.trimem.accounting import canonical_bytes, strict_json_loads
from enterprise_memory.trimem.agent_runtime import CodingTask
from enterprise_memory.trimem.native_architecture_context import _public_copy
from enterprise_memory.trimem.working_graph import ACTIVE, COMPLETED, ShortTermWorkingGraph
import trimem_skhynix_architecture_memory as memory
from trimem_skhynix_architecture_broker import ArchitectureBroker, TOOLS
from trimem_skhynix_architecture_dataset import load_architecture_rows
from trimem_skhynix_architecture_native import outside_broker_item
from trimem_skhynix_architecture_run import load_experiment, native_completion_status, prompt_prefix, execution_enrollment, EMPTY_BANK_SHA

SCHEMA = "skhynix/architecture-evaluation-capture/1.0"
EVALUATION_COUNT = 500
PUBLIC_RESULT_FIELDS = frozenset("schema phase arm task_id official resolved grader_status grader_id container_digest grader_wall_time_ms patch_sha256 patch_bytes event_tail_sha256 broker_status grader_private_sha256 experiment_sha256 bank_sha256 execution_audit_sha256 requested_model separate_model_api_client_calls".split())


class QuarantineError(ValueError):
    pass


def _fail(message):
    raise QuarantineError(message)


def _ref(value):
    return {"path": str(memory._check_ref(value)), "sha256": value["sha256"]}


def _descriptor(target):
    return {"task_id": target["target_id"], "repository": target["repository"],
        "commit": target["base_commit"], "instruction_sha256": target["instruction_sha256"]}


def initialize_quarantine(root, *, execution_reference, bank_reference):
    """Bind the exact evaluation cohort; this creates no episodic memory records."""
    root = memory._path(root)
    execution_reference = _ref(execution_reference)
    bank_reference = _ref(bank_reference) if bank_reference is not None else None
    config = load_experiment(execution_reference["path"])
    targets, rows, dataset = load_architecture_rows(config["dataset_manifest"]["path"],
        expected_sha256=config["dataset_manifest"]["sha256"], role="EVALUATION")
    enrollment = execution_enrollment(config, dataset)
    if enrollment is None and (len(targets) != EVALUATION_COUNT or any(target["role"] != "EVALUATION" for target in targets)):
        _fail("Quarantine must bind every one of the 500 evaluation targets")
    if enrollment is not None:
        if enrollment["purpose"].startswith("TRAINING_") or enrollment["bank_reference"] != bank_reference:
            _fail("Quarantine bank or phase differs from authorized scale evaluation")
        targets = [target for target in targets if target["target_id"] in enrollment["task_ids"]]
        if {target["target_id"] for target in targets} != set(enrollment["task_ids"]):
            _fail("Quarantine must bind the entire exact development or final target subset")
    if bank_reference is None and not (enrollment is not None and enrollment["purpose"] == "DEVELOPMENT_BASELINE"):
        _fail("Only the explicitly authorized development baseline may use an empty bank")
    bank = memory.load_frozen_bank(bank_reference["path"], bank_reference["sha256"]) if bank_reference is not None else None
    try:
        if bank is not None and bank.manifest["scope"]["org_id"] != config["org_id"]:
            _fail("Frozen bank organisation differs from evaluation configuration")
        for role, key in (("TRAINING", "training_tasks"), ("EVALUATION", "evaluation_tasks")):
            expected = {row["target_id"]: _descriptor(row) for row in dataset["targets"] if row["role"] == role}
            if bank is not None and {row["task_id"]: row for row in bank.manifest["scope"][key]} != expected:
                _fail("Frozen bank source or evaluation scope differs from the public dataset")
        if bank is not None and any(type(count) is not int or count <= 0 for count in bank.manifest["layer_counts"].values()):
            _fail("Evaluation requires actual populated L1/L2 relations and verified L3")
        protected = ([memory._path(ref["path"]) for ref in (bank.reference, bank.manifest["authority"], bank.manifest["source_authority"])]
            if bank is not None else [])
        if any(path == root or root in path.parents for path in protected):
            _fail("Evaluation quarantine must be separate from frozen retrieval authority")
    finally:
        if bank is not None:
            bank.close()
    tasks = {}
    for target in targets:
        public = {"task_id": target["target_id"], "repository": target["repository"], "commit": target["base_commit"],
            "instruction": rows[target["instance_id"]]["problem_statement"].strip()}
        if memory._descriptor(public) != _descriptor(target):
            _fail("Evaluation public instruction differs from frozen target identity")
        tasks[target["target_id"]] = {"public": public, "instance_id": target["instance_id"],
            "owner_user_id": "architecture-contributor-" + str(config.get("training_owner_by_instance", {}).get(target["instance_id"], 1))}
    binding = {"schema": SCHEMA, "execution_reference": execution_reference, "bank_reference": bank_reference,
        "dataset_reference": _ref(config["dataset_manifest"]), "org_id": config["org_id"], "tasks": tasks,
        "source_sha256": {"quarantine": memory._file_hash(__file__), "memory": memory._file_hash(memory.__file__)}}
    if enrollment is not None:
        binding.update(scale_authority_reference=config["scale_authority_reference"], arms=enrollment["arms"], purpose=enrollment["purpose"])
    path = root / "quarantine-binding.json"
    if root.exists() and any(root.iterdir()):
        if path.is_file() and memory._read(path) == binding:
            return memory._ref(path)
        _fail("Quarantine requires a fresh or identically bound root")
    memory._write(path, binding, fresh=True)
    reference = memory._ref(path)
    memory._write(root / "quarantine-binding.ref.json", reference, fresh=True)
    return reference


@contextmanager
def _session(root):
    root = memory._path(root)
    with (root / "quarantine.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            reference = _ref(memory._read(root / "quarantine-binding.ref.json"))
            binding = memory._read(reference["path"])
            if binding["source_sha256"] != {"quarantine": memory._file_hash(__file__), "memory": memory._file_hash(memory.__file__)}:
                _fail("Quarantine implementation changed after binding")
            config = load_experiment(_ref(binding["execution_reference"])["path"])
            dataset = memory._read(_ref(binding["dataset_reference"])["path"])
            enrollment = execution_enrollment(config, dataset)
            if enrollment is not None and (binding.get("scale_authority_reference") != config["scale_authority_reference"]
                    or binding.get("arms") != enrollment["arms"] or binding.get("purpose") != enrollment["purpose"]
                    or set(binding["tasks"]) != set(enrollment["task_ids"]) or binding["bank_reference"] != enrollment["bank_reference"]):
                _fail("Quarantine scope differs from the frozen scale execution")
            if binding["bank_reference"] is None and not (enrollment is not None and enrollment["purpose"] == "DEVELOPMENT_BASELINE"):
                _fail("Empty bank is forbidden outside the authorized development baseline")
            bank = (memory.load_frozen_bank(binding["bank_reference"]["path"], binding["bank_reference"]["sha256"])
                if binding["bank_reference"] is not None else None)
            try:
                yield root, binding, config, bank
                if bank is not None:
                    bank._check()
            finally:
                if bank is not None:
                    bank.close()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _native_evidence(cell, config, broker, state, audit, refs):
    workers = sorted(state["workers"].items(), key=lambda item: item[1]["packet_file"])
    if not workers or len(audit["workers"]) != len(workers):
        _fail("Native audit requires every actually admitted evaluation worker")
    native_root = memory._path(Path(config["native_control_root"]) / "EVALUATION" / cell["target"]["instance_id"] / cell["arm"])
    thread_ids = []
    for number, ((worker_id, worker), observed) in enumerate(zip(workers, audit["workers"]), 1):
        folder = native_root / ("worker-" + str(number).zfill(3))
        output = folder / "output"
        if list(output.glob("manager-error-*.json")):
            _fail("Native evaluation worker has retained manager transport failures")
        paths = {"completion.json": output / "completion.json", "events.jsonl": output / "events.jsonl",
            "launch.json": output / "launch.json", "prompt.txt": folder / "prompt.txt", "packet.json": folder / "packet.json"}
        local_refs = {name: memory._ref(path) for name, path in paths.items()}
        completion, launch = memory._read(paths["completion.json"]), memory._read(paths["launch.json"])
        events = [strict_json_loads(line) for line in paths["events.jsonl"].read_bytes().splitlines()]
        threads = [event.get("thread_id") for event in events if event.get("type") == "thread.started"]
        outcome = native_completion_status(completion, completion["exit_code"])
        expected = {"number": number, "thread_id": completion["thread_id"], "completion_sha256": local_refs["completion.json"]["sha256"],
            "events_sha256": local_refs["events.jsonl"]["sha256"], "outcome": outcome}
        if (observed != expected or completion["events_sha256"] != expected["events_sha256"] or
                threads != [completion["thread_id"]] or worker.get("thread_id") != completion["thread_id"] or
                not worker.get("launch_receipt") or worker["launch_receipt"]["launch_evidence_sha256"] != memory._hash(launch)):
            _fail("Native evaluation audit differs from actual event/completion/admission bytes")
        packet = broker._packet(worker["packet_file"])
        native_packet = memory._read(paths["packet.json"])
        prompt = paths["prompt.txt"].read_bytes()
        if (launch.get("requested_model") != "gpt-6-astra" or launch.get("fresh_session") is not True or
                launch.get("resume_or_fork_used") is not False or launch.get("packet_sha256") != worker["packet_sha256"] or
                launch.get("prompt_sha256") != local_refs["prompt.txt"]["sha256"] or launch.get("prompt_bytes") != len(prompt) or
                native_packet != packet.public_dict() or packet.sha256 != worker["packet_sha256"] or
                packet.binding.worker_id != worker_id or packet.binding.arm != cell["arm"] or
                packet.binding.bank_sha256 != cell["bank_sha256"] or
                prompt != prompt_prefix("EVALUATION") + canonical_bytes(native_packet)):
            _fail("Native fresh-worker launch or actual prompt differs from bound evaluation handoff")
        if cell["arm"] == "BASELINE" and native_packet["body"]["memory_injections"]:
            _fail("BASELINE native prompt contained external memory")
        for event in events:
            item = event.get("item", {})
            if item and (outside_broker_item(item) or (item.get("type") == "mcp_tool_call" and item.get("error"))):
                _fail("Native evaluation stream has an undeclared tool or transport error")
        thread_ids.append(completion["thread_id"])
        refs.update({"native/worker-" + str(number) + "/" + name: ref for name, ref in local_refs.items()})
        refs["broker/packets/" + worker["packet_file"]] = memory._ref(broker.root / "packets" / worker["packet_file"])
    if len(set(thread_ids)) != len(thread_ids):
        _fail("Evaluation workers reused a native thread")


def _source(binding, config, bank, cell_path, public_result):
    path = memory._path(cell_path)
    choices = {memory._path(Path(config["run_root"]) / "cells" / "EVALUATION" / task_id / arm / "cell.json"): (task_id, arm)
        for task_id in binding["tasks"] for arm in binding.get("arms", ("BASELINE", "PDF_MEMORY"))}
    if path not in choices:
        _fail("Cell path is outside the frozen evaluation scope")
    task_id, arm = choices[path]
    target = binding["tasks"][task_id]
    cell = memory._read(path)
    if (memory._hash(cell) != path.with_suffix(".sha256").read_text().strip() or cell.get("phase") != "EVALUATION" or
            cell.get("arm") != arm or cell.get("task_public") != target["public"] or cell.get("org_id") != binding["org_id"] or
            cell.get("owner_user_id") != target["owner_user_id"] or cell.get("experiment_config") != binding["execution_reference"]["path"] or
            cell.get("bank_reference") != binding["bank_reference"] or cell.get("bank_sha256") !=
                (binding["bank_reference"]["sha256"] if binding["bank_reference"] is not None else EMPTY_BANK_SHA) or
            cell.get("broker_root") != str(path.parent / "broker") or cell.get("target", {}).get("instance_id") != target["instance_id"]):
        _fail("Evaluation cell task/owner/configuration/bank binding differs")
    task = CodingTask(task_id, cell["org_id"], cell["owner_user_id"], target["public"]["repository"], target["public"]["commit"], target["public"]["instruction"], {}, ())
    if bank is not None:
        bank.bind_task(task)
    elif arm != "BASELINE":
        _fail("Memory evaluation cannot run without its frozen bank")
    result_path, audit_path = path.parent / "public-result.json", path.parent / "execution-audit.json"
    result = _public_copy(memory._read(result_path))
    if set(result) != PUBLIC_RESULT_FIELDS or _public_copy(public_result) != result:
        _fail("Official public result has missing, forbidden, changed or unbound fields")
    if (result["schema"] != cell["schema"] or result["phase"] != "EVALUATION" or result["task_id"] != task_id or result["arm"] != arm or
            result["official"] is not True or result["grader_status"] != "success" or type(result["resolved"]) is not bool or
            result["requested_model"] != "gpt-6-astra" or result["experiment_sha256"] != memory._hash(config) or
            result["bank_sha256"] != cell["bank_sha256"] or type(result["separate_model_api_client_calls"]) is not int or
            result["separate_model_api_client_calls"] != 0 or type(result["patch_bytes"]) is not int or result["patch_bytes"] < 0):
        _fail("Public result is not the official completed grade for this evaluation cell")
    audit = memory._read(audit_path)
    if (set(audit) != {"schema", "task_id", "arm", "event_tail_sha256", "patch_sha256", "configuration_sha256", "workers", "errors", "passed"} or
            audit["schema"] != "skhynix/architecture-execution-audit/1.0" or audit["passed"] is not True or audit["errors"] != [] or
            audit["task_id"] != task_id or audit["arm"] != arm or audit["configuration_sha256"] != memory._hash(config) or
            result["execution_audit_sha256"] != memory._file_hash(audit_path)):
        _fail("Evaluation has no matching successful immutable native execution audit")
    if (path.parent / "native-execution-failure.json").exists():
        _fail("Evaluation has a retained native execution infrastructure failure")
    broker_root = path.parent / "broker"
    with (broker_root / "broker.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        try:
            if (broker_root / "pending.json").exists():
                _fail("Evaluation broker has unfinished or unrecovered operations")
            broker = ArchitectureBroker(broker_root, workspace=SimpleNamespace(), configuration_sha256=memory._hash(config), bank_sha256=cell["bank_sha256"])
            state, events = broker._load()
            tail = events[-1]["sha256"] if events else "0" * 64
            recorded = result["broker_status"]
            if (broker.task != cell["task_public"] or broker.arm != arm or state["status"] != "SUBMITTED" or
                    recorded["status"] != "SUBMITTED" or recorded["submission"] != state["submission"] or
                    recorded["budget"]["requests_used"] != state["actions"] or recorded["event_tail_sha256"] != tail or
                    result["event_tail_sha256"] != tail or audit["event_tail_sha256"] != tail or
                    result["patch_sha256"] != state["submission"]["patch_sha256"] or audit["patch_sha256"] != result["patch_sha256"] or
                    result["patch_bytes"] != state["submission"]["patch_utf8_bytes"]):
                _fail("Official grade no longer matches sealed patch and actual broker events")
            if arm == "BASELINE" and (state["memory_ledger"] or state["memory_checkpoint"] or any(row["injections"] for row in state["memory_queries"].values())):
                _fail("BASELINE recorded external memory use")
            graph = ShortTermWorkingGraph.from_snapshot(state["graph"])
            if graph.task_id != task_id or graph.repository != task.repository or graph.objective != task.instruction.strip():
                _fail("Evaluation graph public task binding differs")
            history = memory._public_trace(memory._descriptor(task), state["history"]) if state["history"] else []
            refs = {name: memory._ref(broker_root / name) for name in
                ("manifest.json", "manifest.sha256", "initial-state.json", "state.json", "events.jsonl", "submission.json", "submission.diff")}
            refs.update({"cell.json": memory._ref(path), "public-result.json": memory._ref(result_path), "execution-audit.json": memory._ref(audit_path)})
            _native_evidence(cell, config, broker, state, audit, refs)
            return cell, graph, history, state["submission"], refs
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _validate_cached(reference, public_result):
    value = memory._read(memory._check_ref(reference))
    if value["public_result_sha256"] != memory._hash(_public_copy(public_result)):
        _fail("Repeated evaluation capture has a different public result")
    for ref in (*value["source_references"].values(), *value["quarantine_references"]):
        _ref(ref)
    return value


def capture_cell(root, cell_config_path, public_result):
    """Audit BASELINE or quarantine PDF_MEMORY's actual public subgoal attempts."""
    with _session(root) as (root, binding, config, bank):
        cell_path = memory._path(cell_config_path)
        bank_sha = binding["bank_reference"]["sha256"] if binding["bank_reference"] is not None else EMPTY_BANK_SHA
        identity = memory._hash({"cell_path": str(cell_path), "bank_sha256": bank_sha})
        path = root / "receipts" / (identity + ".json")
        if path.exists():
            reference = memory._ref(path)
            _validate_cached(reference, public_result)
            return reference
        value = {"schema": SCHEMA, "operation": "CAPTURE_EVALUATION_CELL", "cell_path": str(cell_path),
            "task_id": None, "arm": None, "bank_sha256": bank_sha,
            "bank_reference": binding["bank_reference"],
            "admitted_to_frozen_bank": False, "source_references": {}, "quarantine_references": [],
            "captures": [], "audit_subgoals": [], "failures": [], "memory_records_written": 0,
            "public_result_sha256": memory._hash(_public_copy(public_result))}
        try:
            cell, graph, history, submission, refs = _source(binding, config, bank, cell_path, public_result)
            value.update(task_id=cell["task_public"]["task_id"], arm=cell["arm"], source_references=refs,
                public_grade_reference=refs["public-result.json"], source_execution_observed=True,
                public_tool_rows=sum(row["tool"] in TOOLS for row in history), agent_completed=submission["agent_completed"])
            private = root / "private" / identity
            stamp = datetime.fromtimestamp(submission["submitted_at"], timezone.utc).isoformat()
            for node in sorted(graph.nodes.values(), key=lambda item: item.node_id):
                selected = [row for row in history if row["active_node_id"] == node.node_id]
                if node.status not in (COMPLETED, ACTIVE) or not any(row["tool"] in TOOLS for row in selected):
                    continue
                completed = node.status == COMPLETED
                completions = [row for row in selected if row["tool"] == "complete_subtask" and row["status"] == "success"]
                summary = (completions[-1]["request_payload"]["arguments"]["evidence"] if completed and completions else
                    "Terminal partial attempt; semantic subgoal not completed. " + submission["summary"])
                commands = [row for row in selected if row["tool"] == "run_command"]
                verifier = commands[-1] if commands else None
                step = None
                if (verifier is not None and memory._test_outcome(verifier) in ("RED", "GREEN") and
                        not any(row["tool"] in memory.MUTATING and row["step_no"] > verifier["step_no"] for row in selected)):
                    step = verifier["step_no"]
                value["audit_subgoals"].append({"node_id": node.node_id, "semantic_completion": completed,
                    "public_steps": [row["step_no"] for row in selected], "verification_step": step})
                if cell["arm"] == "BASELINE":
                    continue
                try:
                    receipt = memory.capture_evaluation_trace(private, binding["bank_reference"]["path"], binding["bank_reference"]["sha256"],
                        cell["task_public"], history, owner_user_id=cell["owner_user_id"], active_node_id=node.node_id,
                        subgoal=node.objective + " (subgoal " + node.node_id + ")", summary=summary, verification_step=step, created_at=stamp)
                    value["captures"].append({"receipt": receipt, "semantic_completion": completed})
                except (ValueError, RuntimeError) as exc:
                    value["failures"].append({"node_id": node.node_id, "error_type": type(exc).__name__, "reason": str(exc)[:1000]})
            if value["captures"]:
                catalog = memory._read(private / "catalog.json")
                with memory._ReadOnlyStore(private / "authority.sqlite3") as store:
                    records = store._db.execute("SELECT * FROM memory_records").fetchall()
                    if any(row["kind"] != "episode" or row["owner_user_id"] != cell["owner_user_id"] for row in records):
                        _fail("Evaluation quarantine contains shared or incorrectly owned memory")
                    value["memory_records_written"] = len(records)
                memory._write(private / "frozen.json", {"schema": SCHEMA, "operation": "SEAL_PRIVATE_QUARANTINE_NOT_RETRIEVAL_BANK"}, fresh=True)
                value["quarantine_references"] = [memory._ref(private / name) for name in ("scope.json", "catalog.json", "authority.sqlite3", "frozen.json")]
                value["quarantine_references"].extend(catalog["captures"].values())
            value["status"] = ("PARTIAL_CAPTURE_FAILURE" if value["failures"] else "BASELINE_AUDIT_ONLY" if cell["arm"] == "BASELINE" else
                "CAPTURED" if value["captures"] else "NO_PUBLIC_ATTEMPTS")
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
            value["status"] = "INVALID_SOURCE"
            value["failures"].append({"error_type": type(exc).__name__, "reason": str(exc)[:1000]})
        if bank is not None:
            bank._check()
        memory._write(path, value, fresh=True)
        return memory._ref(path)


def make_quarantine_hook(root):
    def hook(cell_config_path, public_result, receipt_directory):
        capture = capture_cell(root, cell_config_path, public_result)
        value = {"schema": SCHEMA, "operation": "COHORT_CAPTURE", "capture_receipt": capture}
        path = memory._path(receipt_directory) / "learning-capture.json"
        if path.exists():
            if memory._read(path) != value:
                _fail("Existing evaluation capture mirror differs")
        else:
            memory._write(path, value, fresh=True)
        return memory._ref(path)
    return hook


make_capture_hook = make_quarantine_hook
