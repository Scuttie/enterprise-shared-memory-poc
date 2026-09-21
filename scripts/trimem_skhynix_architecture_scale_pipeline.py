"""Frozen 24/120/240 memory collection, disjoint development, then final500.

This controller never selects training sources from grading outcomes. Completed
source attempts are adopted as immutable public evidence, not solved again.
Development alone chooses the bank. Final outcomes cannot change that choice.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import trimem_skhynix_architecture_pipeline as core
from trimem_skhynix_architecture_broker import locked
from enterprise_memory.trimem.accounting import canonical_bytes

SCHEMA = "skhynix/architecture-scale-pipeline/1.0"
SELECTION_POLICY = "MAX_DEVELOPMENT_RESOLVED_THEN_SMALLEST_SOURCE_COUNT"
SIZES = (24, 120, 240)
REPLACEMENT_SCHEMA = "skhynix/architecture-scale-infrastructure-replacement/1.0"
INHERITANCE_SCHEMA = "skhynix/architecture-scale-bank-inheritance/1.0"
CONTINUATION_SCHEMA = "skhynix/architecture-scale-grading-continuation/1.0"
CHAINED_CONTINUATION_SCHEMA = "skhynix/architecture-scale-grading-continuation/2.0"
TRAINING_CONTINUATION_SCHEMA = "skhynix/architecture-scale-grading-continuation/3.0"
TRAINING_GRADE_HOLD_POLICY = "CAPTURE_KNOWN_TERMINAL_AMBIGUITY_AND_CONTINUE"


def _grading_lineage(config):
    """Return bounded, immutable continuation ancestry, newest first."""
    lineage, seen = [], set()
    while config.get("grading_continuation_reference") is not None:
        reference = config["grading_continuation_reference"]
        identity = (reference["path"], reference["sha256"])
        if identity in seen or len(lineage) >= 16:
            raise core.PipelineError("grading continuation ancestry is cyclic or exceeds its bounded depth")
        seen.add(identity)
        receipt = core.check(reference)
        lineage.append((config, receipt))
        config = core.check(receipt["predecessor_pipeline_reference"])
    return lineage


def _stage_adoptions(config, through_size):
    """Keep the original pilot adoption separate from later increment sources."""
    references = [config["source_adoption_reference"]]
    for stage in config["training_stages"]:
        if stage["size"] > through_size:
            break
        experiment = core.check(stage["execution_reference"])
        authority = core.check(experiment["scale_authority_reference"])
        reference = authority.get("source_adoption_reference")
        if reference is not None and reference not in references:
            references.append(reference)
    return [(reference, core.check(reference)) for reference in references]


def _event_reference(reference, root, *, tail=False):
    path = core.absolute(reference["path"])
    root = core.absolute(root)
    if path.parent != root / "events":
        raise core.PipelineError("recovery event is outside its original journal")
    core.check(reference)
    events = core.read_event_chain(root)
    sequence = int(path.stem)
    if (not 0 < sequence <= len(events) or core.read(path) != events[sequence - 1]
            or (tail and sequence != len(events))):
        raise core.PipelineError("recovery journal advanced or event binding differs")
    return events[sequence - 1]


def _inherited_bank(config, stage):
    reference = stage.get("inherited_bank_reference")
    if reference is None:
        return None
    receipt = core.check(reference)
    old = core.check(receipt["predecessor_pipeline_reference"])
    replacement = core.check(config["infrastructure_replacement_reference"])
    prior = next(item for item in old["training_stages"] if item["size"] == stage["size"])
    old_learning = prior.get("learning_root", str(Path(old["pipeline_root"]) / ("learning-" + str(stage["size"]))))
    if (receipt.get("schema") != INHERITANCE_SCHEMA or stage["size"] != 24
            or receipt["predecessor_pipeline_reference"] != replacement["predecessor_pipeline_reference"]
            or stage["execution_reference"] != prior["execution_reference"]
            or stage.get("learning_root") != old_learning
            or config["source_adoption_reference"] != old["source_adoption_reference"]
            or config["protocol_reference"] != old["protocol_reference"]):
        raise core.PipelineError("inherited pilot must retain its exact source and learning authority")
    event = _event_reference(receipt["event_reference"], old["pipeline_root"])
    result = core.check(receipt["result_reference"])
    enrollment = core.check(receipt["learning_enrollment_reference"])
    experiment = core.check(stage["execution_reference"])
    if (event.get("stage") != "BANK_NOT_READY" or event.get("job") != "bank-24"
            or event.get("details", {}).get("reference") != receipt["result_reference"]
            or receipt["result_reference"]["path"] != str(Path(old["pipeline_root"]) / "bank-24/bank-status.json")
            or receipt["learning_enrollment_reference"]["path"] != str(Path(old_learning) / "learning-enrollment.json")
            or enrollment.get("dataset_reference") != experiment["dataset_manifest"]
            or result.get("status") != "NOT_READY" or result.get("size") != 24
            or result.get("source_attempts") != 24 or result.get("bank_reference") is not None):
        raise core.PipelineError("inherited pilot result does not prove the original completed NOT_READY decision")
    plan = core.check(result["reflection_plan_reference"])
    core.check(result["catalog_reference"])
    if (result["reflection_plan_reference"]["path"] != str(Path(old["reflection_native_root"]) / "bank-24/reflection-plan.json")
            or result["catalog_reference"]["path"] != str(Path(old_learning) / "catalog.json")
            or (Path(old_learning) / "learning-frozen.json").exists()):
        raise core.PipelineError("inherited NOT_READY evidence changed or became a different publication")
    if plan.get("binding", {}).get("enrollment_reference") != receipt["learning_enrollment_reference"]:
        raise core.PipelineError("inherited reflection plan belongs to a different learning authority")
    for source_ref in plan["binding"].get("source_cell_references", []):
        core.check(source_ref)
    for job in plan.get("jobs", []):
        core.check(job["reflection_reference"])
    return result


def validate_infrastructure_replacement(config, *, execution=None):
    """Permit one named quota interruption under an explicit new protocol only.

    The original failed attempt remains excluded from all memory source lists.
    No audit, submission, official outcome, or original controller is rewritten.
    """
    continuation = config.get("grading_continuation_reference")
    if continuation is not None:
        current = core.check(continuation)
        old = core.check(current["predecessor_pipeline_reference"])
        if ((old.get("grading_continuation_reference") is not None and current.get("schema") not in {CHAINED_CONTINUATION_SCHEMA, TRAINING_CONTINUATION_SCHEMA})
                or config.get("infrastructure_replacement_reference") != old.get("infrastructure_replacement_reference")):
            raise core.PipelineError("grading continuation must preserve the exact historical quota authority")
        if current.get("schema") in {CHAINED_CONTINUATION_SCHEMA, TRAINING_CONTINUATION_SCHEMA}:
            _grading_lineage(config)
            if current.get("historical_grading_continuation_reference") != old.get("grading_continuation_reference"):
                raise core.PipelineError("chained continuation changed historical grading authority")
        # This only validates historical authority; it does not authorize another
        # native replacement in the new source continuation.
        return validate_infrastructure_replacement(old, execution=execution)
    reference = config.get("infrastructure_replacement_reference")
    if reference is None:
        if any(stage.get("inherited_bank_reference") for stage in config["training_stages"]):
            raise core.PipelineError("bank inheritance requires the explicit recovery authority")
        return None
    receipt = core.check(reference)
    required = {"schema": REPLACEMENT_SCHEMA, "operation": "AUTHORIZE_ONE_QUOTA_REPLACEMENT",
        "reason": "CODEX_USAGE_LIMIT", "replacement_limit": 1,
        "fresh_task_requests": 120, "fresh_task_seconds": 1200,
        "original_attempt_excluded_from_memory": True, "official_outcome_retries": False,
        "protocol_amendment": "ONE_NATIVE_INFRASTRUCTURE_REPLACEMENT_WITH_FRESH_BUDGET",
        "model_calls": 0, "official_grader_runs": 0}
    if any(type(receipt.get(key)) is not type(value) or receipt[key] != value for key, value in required.items()):
        raise core.PipelineError("unsupported infrastructure replacement protocol amendment")
    old_pipeline = core.check(receipt["predecessor_pipeline_reference"])
    old = core.check(receipt["old_execution_reference"])
    new = core.check(receipt["new_execution_reference"])
    task = receipt["task_id"]
    if (core.read(Path(old_pipeline["pipeline_root"]) / "pipeline-binding.json") !=
            {"schema": SCHEMA, "configuration_reference": receipt["predecessor_pipeline_reference"]}
            or core.read(Path(old["run_root"]) / "cohort/cohort.json").get("experiment_reference") != receipt["old_execution_reference"]):
        raise core.PipelineError("predecessor journal is not bound to the exact original configuration")
    if task != "swebench--django__django-16686":
        raise core.PipelineError("quota authority permits only the exact interrupted source")
    old_stage = old_pipeline["training_stages"][1]
    stage = config["training_stages"][1]
    allowed = {"run_root", "native_control_root", "scale_authority_reference", "prelaunch_revision"}
    if (old_stage["execution_reference"] != receipt["old_execution_reference"]
            or stage["execution_reference"] != receipt["new_execution_reference"]
            or config.get("supersedes_configuration_reference") != receipt["predecessor_pipeline_reference"]
            or {k: v for k, v in old.items() if k not in allowed} != {k: v for k, v in new.items() if k not in allowed}
            or old["run_root"] == new["run_root"] or old["native_control_root"] == new["native_control_root"]
            or config["pipeline_root"] == old_pipeline["pipeline_root"]
            or stage.get("learning_root", str(Path(config["pipeline_root"]) / "learning-120")) ==
               old_stage.get("learning_root", str(Path(old_pipeline["pipeline_root"]) / "learning-120"))):
        raise core.PipelineError("replacement changed the task protocol or reused an immutable execution root")
    for key in ("protocol_reference", "source_adoption_reference", "training_experiment_reference",
                "helper_references", "reflection_source_reference", "selection_policy", "reflection_max_bytes"):
        if config[key] != old_pipeline[key]:
            raise core.PipelineError("quota recovery cannot replace source helpers, pilot, or selection policy")
    for index in (0, 2):
        if config["training_stages"][index]["execution_reference"] != old_pipeline["training_stages"][index]["execution_reference"]:
            raise core.PipelineError("quota recovery cannot alter other execution stages")
    pipeline_tail = _event_reference(receipt["predecessor_pipeline_event_tail_reference"], old_pipeline["pipeline_root"], tail=True)
    cohort_tail = _event_reference(receipt["predecessor_cohort_event_tail_reference"], Path(old["run_root"]) / "cohort", tail=True)
    if (pipeline_tail.get("stage") != "PIPELINE_BLOCKED" or cohort_tail.get("stage") != "INFRA_ERROR"
            or cohort_tail.get("task_id") != task):
        raise core.PipelineError("replacement needs the exact blocked predecessor journals")
    folder = Path(old["run_root"]) / "cells/TRAINING" / task / "PDF_MEMORY"
    paths = {"old_cell_reference": folder / "cell.json", "audit_reference": folder / "execution-audit.json",
        "native_failure_reference": folder / "native-execution-failure.json",
        "submission_reference": folder / "broker/submission.json", "submission_patch_reference": folder / "broker/submission.diff"}
    for key, path in paths.items():
        if receipt[key]["path"] != str(path):
            raise core.PipelineError("quota evidence is outside the exact original cell")
        core.check(receipt[key], decode=key != "submission_patch_reference")
    cell, audit = core.check(receipt["old_cell_reference"]), core.check(receipt["audit_reference"])
    submission, failure = core.check(receipt["submission_reference"]), core.check(receipt["native_failure_reference"])
    config_sha = core.digest(canonical_bytes(old))
    prior_events = core.read_event_chain(Path(old["run_root"]) / "cohort")
    prepared = [row for row in prior_events if row.get("stage") == "PREPARED" and row.get("task_id") == task]
    if (cell.get("experiment_config") != receipt["old_execution_reference"]["path"]
            or len(prepared) != 1 or prepared[0].get("details", {}).get("cell_reference") != receipt["old_cell_reference"]
            or (folder / "cell.sha256").read_text().strip() != core.digest(canonical_bytes(cell))
            or cell.get("task_public", {}).get("task_id") != task or cell.get("arm") != "PDF_MEMORY"
            or cell.get("phase") != "TRAINING" or cell.get("bank_reference") is not None
            or audit.get("passed") is not False or not audit.get("errors")
            or audit.get("task_id") != task or audit.get("configuration_sha256") != config_sha
            or submission.get("task_id") != task or submission.get("configuration_sha256") != config_sha
            or submission.get("reason") != "NATIVE_WORKER_INFRASTRUCTURE_FAILURE"
            or submission.get("agent_completed") is not False
            or submission.get("actions") != receipt.get("historical_actions")
            or type(receipt.get("historical_actions")) is not int or not 0 < receipt["historical_actions"] <= 120
            or audit.get("patch_sha256") != receipt["submission_patch_reference"]["sha256"]
            or submission.get("patch_sha256") != audit.get("patch_sha256")
            or any((folder / name).exists() for name in ("public-result.json", "grader-pending.json"))):
        raise core.PipelineError("replacement requires a sealed failed native attempt with no official result or pending grade")
    worker_number = int(failure["worker_id"].rsplit("-", 1)[-1])
    native_folder = Path(old["native_control_root"]) / "TRAINING" / cell["target"]["instance_id"] / "PDF_MEMORY" / f"worker-{worker_number:03d}" / "output"
    if (receipt["native_completion_reference"]["path"] != str(native_folder / "completion.json")
            or receipt["native_events_reference"]["path"] != str(native_folder / "events.jsonl")):
        raise core.PipelineError("quota completion is outside the failed worker")
    completion = core.check(receipt["native_completion_reference"])
    core.check(receipt["native_events_reference"], decode=False)
    if (completion.get("exit_code") != 1 or failure.get("launcher_returncode") != 1
            or completion.get("admitted") is not True or completion.get("timed_out") is not False
            or any(completion.get(key) != [] for key in ("errors", "transport_errors", "outside_broker_tool_events"))
            or completion.get("events_sha256") != receipt["native_events_reference"]["sha256"]
            or failure.get("completion_sha256") != receipt["native_completion_reference"]["sha256"]):
        raise core.PipelineError("replacement does not bind one admitted quota-failed native worker")
    events = [json.loads(line) for line in Path(receipt["native_events_reference"]["path"]).read_text().splitlines() if line]
    errors = [event for event in events if event.get("type") in ("error", "turn.failed")]
    if ({event["type"] for event in errors} != {"error", "turn.failed"}
            or any("You've hit your usage limit." not in json.dumps(event) for event in errors)):
        raise core.PipelineError("retained native events do not identify the exact provider quota failure")
    authority = core.check(new["scale_authority_reference"])
    old_authority = core.check(old["scale_authority_reference"])
    adoption = core.check(authority["source_adoption_reference"])
    adopted = [row["task_id"] for row in adoption["rows"]]
    completed = [event["task_id"] for event in prior_events
                 if event.get("stage") == "CELL_COMPLETE"]
    if (authority.get("purpose") != "TRAINING_INCREMENT" or authority.get("cumulative_training_count") != 120
            or authority.get("task_ids") != [item for item in old_authority["task_ids"] if item not in adopted]
            or not authority["task_ids"] or authority["task_ids"][0] != task
            or len(adopted) != len(set(adopted)) or set(adopted) != set(completed)
            or task in adopted or receipt["old_execution_reference"] not in adoption["predecessor_configrefs"]):
        raise core.PipelineError("replacement must preserve the exact remaining increment and original source owners")
    if execution is not None:
        execution.execution_enrollment(new, core.check(new["dataset_manifest"]))
    _inherited_bank(config, config["training_stages"][0])
    return receipt


def _windows_native_path(path):
    text = Path(path).as_posix()
    if not text.startswith("/mnt/c/"):
        raise core.PipelineError("native binary must bind an explicit C-drive bundle")
    return "C:/" + text[len("/mnt/c/"):]


def _validate_frozen_native_binary(reference, executions, *, verify_bytes):
    receipt = core.check(reference)
    root = core.absolute(receipt["bundle_root"])
    binary = receipt["binary_reference"]
    hashes = receipt["bundle_sha256"]
    if (receipt.get("schema") != "skhynix/frozen-native-binary/1.0"
            or type(receipt.get("model_calls")) is not int or receipt["model_calls"] != 0
            or not isinstance(receipt.get("version"), str) or not receipt["version"]
            or binary.get("path") != str(root / "codex.exe")
            or receipt.get("codex_binary") != _windows_native_path(root / "codex.exe")
            or receipt.get("original_binary_reference", {}).get("sha256") != binary.get("sha256")
            or not isinstance(hashes, dict) or hashes.get("codex.exe") != binary.get("sha256")
            or any(item.get("codex_binary") != receipt["codex_binary"] for item in executions)):
        raise core.PipelineError("native binary receipt must bind the same frozen executable in both future stages")
    for relative, sha256 in hashes.items():
        path = root / relative
        if (not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts
                or not isinstance(sha256, str) or len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256)):
            raise core.PipelineError("native binary bundle contains an invalid member")
        if verify_bytes:
            core.check({"path": str(path), "sha256": sha256}, decode=False)
    # The original extension may later be upgraded/removed; its retained hash
    # proves provenance without depending on that mutable installation path.
    return receipt


def _validate_aborted_native_launch(config, receipt, new):
    reference = receipt.get("aborted_native_launch_pipeline_reference")
    if reference is None:
        return
    if receipt.get("native_binary_reference") is None:
        raise core.PipelineError("aborted native launch requires an explicit frozen binary")
    prior = core.check(reference)
    prior_ref = prior["training_stages"][1]["execution_reference"]
    execution = core.check(prior_ref)
    root, task = Path(execution["run_root"]), core.check(new["scale_authority_reference"])["task_ids"][0]
    pipeline_tail = _event_reference(receipt["aborted_native_launch_pipeline_event_tail_reference"], prior["pipeline_root"], tail=True)
    cohort_tail = _event_reference(receipt["aborted_native_launch_cohort_event_tail_reference"], root / "cohort", tail=True)
    events = core.read_event_chain(root / "cohort")
    if (core.read(Path(prior["pipeline_root"]) / "pipeline-binding.json") != {"schema": SCHEMA, "configuration_reference": reference}
            or core.read(root / "cohort/cohort.json").get("experiment_reference") != prior_ref
            or pipeline_tail.get("stage") != "PIPELINE_BLOCKED"
            or [row.get("stage") for row in events] != ["PREPARE_STARTED", "PREPARED", "SOLVE_STARTED", "INFRA_ERROR"]
            or any(row.get("task_id") != task for row in events)
            or cohort_tail.get("details", {}).get("error_type") != "FileNotFoundError"
            or "output/completion.json" not in cohort_tail.get("details", {}).get("error", "").replace("\\", "/")
            or any(new.get(key) != execution.get(key) for key in ("dataset_manifest", "model", "reasoning_effort", "authentication", "limits", "source_root", "source_sha256"))
            or core.check(execution["scale_authority_reference"])["task_ids"] != core.check(new["scale_authority_reference"])["task_ids"]
            or config["pipeline_root"] == prior["pipeline_root"]
            or new["run_root"] == execution["run_root"] or new["native_control_root"] == execution["native_control_root"]):
        raise core.PipelineError("native continuation requires the exact pre-admission blocked attempt and fresh roots")
    folder = root / "cells/TRAINING" / task / "PDF_MEMORY"
    cell = core.read(folder / "cell.json")
    native = Path(execution["native_control_root"]) / "TRAINING" / cell["target"]["instance_id"] / "PDF_MEMORY/worker-001"
    paths = {"cell": folder / "cell.json", "cell_checksum": folder / "cell.sha256",
        "broker_state": folder / "broker/state.json", "broker_events": folder / "broker/events.jsonl",
        "broker_packet": folder / "broker/packets/0001.json", "worker_config": native / "config.json",
        "worker_packet": native / "packet.json", "worker_prompt": native / "prompt.txt",
        "launch": native / "output/launch.json", "launcher_stderr": native / "launcher-stderr.log",
        "events": native / "output/events.jsonl", "stderr": native / "output/stderr.log"}
    refs = receipt.get("aborted_native_launch_evidence_references", {})
    if set(refs) != set(paths):
        raise core.PipelineError("aborted native attempt requires every retained public launch binding")
    for key, path in paths.items():
        if refs[key].get("path") != str(path):
            raise core.PipelineError("aborted native evidence escaped its original attempt")
        core.check(refs[key], decode=False)
    state, worker_config, launch = (core.read(paths[key]) for key in ("broker_state", "worker_config", "launch"))
    broker_events = [json.loads(line) for line in paths["broker_events"].read_text().splitlines() if line]
    workers = state.get("workers", {})
    worker_id = state.get("current_worker")
    worker = workers.get(worker_id, {})
    packet = core.read(paths["broker_packet"])
    packet_sha = core.digest(canonical_bytes(packet["body"]))
    stderr = paths["launcher_stderr"].read_text(encoding="utf-8", errors="replace")
    if (events[1].get("details", {}).get("cell_reference") != refs["cell"]
            or paths["cell_checksum"].read_text().strip() != core.digest(canonical_bytes(cell))
            or cell.get("experiment_config") != prior_ref["path"] or cell.get("phase") != "TRAINING" or cell.get("arm") != "PDF_MEMORY"
            or cell.get("task_public", {}).get("task_id") != task or cell.get("bank_reference") is not None
            or state.get("status") != "WAITING_ADMISSION" or state.get("actions") != 0 or state.get("started_at") is not None
            or state.get("history") != [] or state.get("submission") is not None
            or state.get("unfinished_actions", 0) != 0 or state.get("tool_errors", 0) != 0
            or len(workers) != 1 or worker.get("status") != "ISSUED" or worker.get("packet_file") != "0001.json"
            or "thread_id" in worker
            or packet.get("sha256") != packet_sha or worker.get("packet_sha256") != packet_sha or state.get("last_packet") != "0001.json"
            or len(broker_events) != 1 or broker_events[0].get("kind") != "ISSUE_HANDOFF"
            or broker_events[0].get("sequence") != 1 or broker_events[0].get("previous_sha256") != "0" * 64
            or broker_events[0].get("sha256") != core.digest(canonical_bytes({k: v for k, v in broker_events[0].items() if k != "sha256"}))
            or broker_events[0].get("state_after_sha256") != core.digest(canonical_bytes(state))
            or core.read(paths["worker_packet"]) != packet
            or worker_config.get("worker_id") != worker_id or worker_config.get("linux_cell_config") != str(folder / "cell.json")
            or worker_config.get("codex_binary") != execution.get("codex_binary")
            or worker_config.get("packet_sha256") != packet_sha or launch.get("packet_sha256") != packet_sha
            or worker_config.get("prompt_sha256") != refs["worker_prompt"]["sha256"] or launch.get("prompt_sha256") != refs["worker_prompt"]["sha256"]
            or worker_config.get("model") != "gpt-6-astra" or worker_config.get("reasoning_effort") != "high"
            or worker_config.get("authentication") != "CHATGPT"
            or launch.get("worker_id") != worker_id or launch.get("requested_model") != "gpt-6-astra" or launch.get("reasoning_effort") != "high"
            or launch.get("authentication") != "CHATGPT_FORCED" or launch.get("fresh_session") is not True or launch.get("resume_or_fork_used") is not False
            or paths["events"].stat().st_size != 0 or paths["stderr"].stat().st_size != 0
            or any(text not in stderr for text in ("WinError 2", "CreateProcess", "Popen"))
            or any((native / name).exists() for name in ("admission.json", "output/completion.json"))
            or any((folder / name).exists() for name in ("public-result.json", "grader-pending.json", "execution-audit.json", "broker/submission.json", "broker/submission.diff"))
            or len(list((root / "cells").glob("**/cell.json"))) != 1):
        raise core.PipelineError("only an issued worker with zero admission, model events and actions can continue")


def _validate_training_runtime_revision(config, old_pipeline, receipt, old, new, *, execution=None):
    """Authorize exactly the reviewed training-only terminal-source policy revision."""
    freeze = core.check(receipt["runtime_change_reference"])
    changed = sorted(key for key in old["source_sha256"] if old["source_sha256"][key] != new["source_sha256"].get(key))
    expected = sorted("scripts/trimem_skhynix_architecture_" + name + ".py" for name in ("run", "cohort", "cleanup"))
    if (freeze.get("schema") != "skhynix/grading-continuation-runtime-freeze/1.0"
            or freeze.get("previous_execution_reference") != receipt["old_execution_reference"]
            or set(old["source_sha256"]) != set(new["source_sha256"]) or changed != expected
            or sorted(freeze.get("changed_paths", [])) != changed
            or any(freeze.get(key) != new[key] for key in ("source_root", "source_sha256"))
            or any(freeze.get("old_" + key) != old[key] for key in ("source_root", "source_sha256"))
            or old["source_root"] == new["source_root"]
            or new.get("phase") != "TRAINING_RUNTIME" or old.get("training_grade_hold_policy") is not None
            or new.get("training_grade_hold_policy") != TRAINING_GRADE_HOLD_POLICY
            or type(freeze.get("model_calls")) is not int or freeze["model_calls"] != 0
            or type(freeze.get("official_grader_runs")) is not int or freeze["official_grader_runs"] != 0):
        raise core.PipelineError("training continuation requires the exact reviewed training-only runtime revision")
    old_helpers, new_helpers = old_pipeline["helper_references"], config["helper_references"]
    if old_helpers.keys() != new_helpers.keys():
        raise core.PipelineError("training continuation cannot add or remove pipeline helpers")
    for name, before, after in [*((name, old_helpers[name], new_helpers[name]) for name in old_helpers),
            ("reflection", old_pipeline["reflection_source_reference"], config["reflection_source_reference"])]:
        relative = str(Path(before["path"]).relative_to(old["source_root"]))
        if (Path(after["path"]).relative_to(new["source_root"]) != Path(relative)
                or after["sha256"] != new["source_sha256"].get(relative)
                or before["sha256"] != old["source_sha256"].get(relative)
                or (name not in {"cohort", "cleanup"} and before["sha256"] != after["sha256"])):
            raise core.PipelineError("training runtime changed unrelated helper logic or source binding")
        core.check(after, decode=False)
    old_stage, new_stage = old_pipeline["training_stages"][2], config["training_stages"][2]
    old240, new240 = core.check(old_stage["execution_reference"]), core.check(new_stage["execution_reference"])
    runtime_keys = {"source_root", "source_sha256", "prelaunch_revision", "training_grade_hold_policy",
                    "loader_preflight_path", "loader_preflight_sha256"}
    if ({k: v for k, v in old_stage.items() if k != "execution_reference"} !=
            {k: v for k, v in new_stage.items() if k != "execution_reference"}
            or {k: v for k, v in old240.items() if k not in runtime_keys} !=
               {k: v for k, v in new240.items() if k not in runtime_keys}
            or any(new240.get(key) != new.get(key) for key in runtime_keys - {"prelaunch_revision"})):
        raise core.PipelineError("future training240 must preserve enrollment and use the same training-only runtime")
    loader = receipt.get("loader_preflight_reference")
    if loader is None:
        raise core.PipelineError("training runtime revision requires its exact new loader preflight")
    core.check(loader)
    if any(item.get("loader_preflight_path") != loader["path"]
            or item.get("loader_preflight_sha256") != loader["sha256"] for item in (new, new240)):
        raise core.PipelineError("new training runtimes differ from the exact loader preflight receipt")
    if execution is not None:
        import trimem_benchmark_run as benchmark
        benchmark.load_official_harness_loader_preflight(Path(loader["path"]))


def _validate_historical_loader(reference, execution_config):
    """Run the unchanged exact checker in its own frozen historical import root."""
    root = core.absolute(execution_config["source_root"])
    core.check(reference)
    for relative, digest in execution_config["source_sha256"].items():
        core.check({"path": str(root / relative), "sha256": digest}, decode=False)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(str(root / name) for name in ("scripts", "src"))
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    code = ("import sys; from pathlib import Path; import trimem_benchmark_run as benchmark\n"
        "if Path(benchmark.__file__).resolve() != Path(sys.argv[2]) / 'scripts/trimem_benchmark_run.py':\n"
        "    raise RuntimeError('historical loader imported a different runtime')\n"
        "benchmark.load_official_harness_loader_preflight(Path(sys.argv[1]))")
    completed = subprocess.run([sys.executable, "-P", "-c", code, reference["path"], str(root)],
        cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False)
    if completed.returncode != 0:
        raise core.PipelineError("historical frozen loader's exact environment and invocation check failed")


def _validate_chained_grading_continuation(config, receipt, *, execution=None, historical_loader=False):
    """Continue an exact later source suffix while retaining every earlier authority."""
    _grading_lineage(config)
    reasons = {"AMBIGUOUS_MISSING_MODULE": "missing_module",
               "AMBIGUOUS_NO_TESTS_COLLECTED": "no_tests_collected"}
    classification = receipt.get("classification")
    if not isinstance(classification, str) or classification not in reasons:
        raise core.PipelineError("unsupported chained ambiguous grading classification")
    revised = receipt.get("schema") == TRAINING_CONTINUATION_SCHEMA
    required = {"schema": TRAINING_CONTINUATION_SCHEMA if revised else CHAINED_CONTINUATION_SCHEMA, "operation": "CONTINUE_AFTER_UNDETERMINED_SOURCE_GRADE",
        "official_outcome": "UNDETERMINED", "resolved": None,
        "source_only": True, "native_retries": False, "official_grader_retries": False,
        "model_calls": 0, "official_grader_runs": 0}
    if any(type(receipt.get(key)) is not type(value) or receipt.get(key) != value for key, value in required.items()):
        raise core.PipelineError("unsupported chained source-only grading continuation")
    old_pipeline = core.check(receipt["predecessor_pipeline_reference"])
    historical = old_pipeline.get("grading_continuation_reference")
    if (historical is None or receipt.get("historical_grading_continuation_reference") != historical
            or config.get("supersedes_configuration_reference") != receipt["predecessor_pipeline_reference"]
            or config.get("infrastructure_replacement_reference") != old_pipeline.get("infrastructure_replacement_reference")):
        raise core.PipelineError("chained continuation must preserve exact historical authority")
    previous_receipt = core.check(historical)
    for key in ("runtime_change_reference", "loader_preflight_reference", "native_binary_reference"):
        if (not revised or key == "native_binary_reference") and receipt.get(key) != previous_receipt.get(key):
            raise core.PipelineError("chained continuation cannot replace runtime, loader or native binary provenance")
    if any(key.startswith(("abandoned_preparation_", "aborted_native_launch_")) for key in receipt):
        raise core.PipelineError("prior preparation failures belong only to their historical continuation")
    validate_grading_continuation(old_pipeline, execution=execution, _historical_loader=historical_loader or revised)
    old, new = core.check(receipt["old_execution_reference"]), core.check(receipt["new_execution_reference"])
    old_stage, stage = old_pipeline["training_stages"][1], config["training_stages"][1]
    if (old_stage["execution_reference"] != receipt["old_execution_reference"]
            or stage["execution_reference"] != receipt["new_execution_reference"]
            or config.get("training_experiment_reference") != receipt["new_execution_reference"]
            or core.read(Path(old_pipeline["pipeline_root"]) / "pipeline-binding.json") !=
               {"schema": SCHEMA, "configuration_reference": receipt["predecessor_pipeline_reference"]}
            or core.read(Path(old["run_root"]) / "cohort/cohort.json").get("experiment_reference") != receipt["old_execution_reference"]):
        raise core.PipelineError("chained continuation must bind the exact blocked predecessor configurations")
    allowed = {"run_root", "native_control_root", "scale_authority_reference", "prelaunch_revision"}
    if revised:
        allowed.update(("source_root", "source_sha256", "loader_preflight_path", "loader_preflight_sha256", "training_grade_hold_policy"))
    if ({k: v for k, v in old.items() if k not in allowed} != {k: v for k, v in new.items() if k not in allowed}
            or old["run_root"] == new["run_root"] or old["native_control_root"] == new["native_control_root"]
            or config["pipeline_root"] == old_pipeline["pipeline_root"]
            or stage.get("learning_root", str(Path(config["pipeline_root"]) / "learning-120")) ==
               old_stage.get("learning_root", str(Path(old_pipeline["pipeline_root"]) / "learning-120"))
            or config["training_stages"][0] != old_pipeline["training_stages"][0]
            or (not revised and config["training_stages"][2] != old_pipeline["training_stages"][2])):
        raise core.PipelineError("chained continuation changed task protocol or reused immutable roots")
    for key in ("protocol_reference", "source_adoption_reference", "selection_policy", "reflection_max_bytes",
                "helper_references", "reflection_source_reference"):
        if not (revised and key in {"helper_references", "reflection_source_reference"}) and config[key] != old_pipeline[key]:
            raise core.PipelineError("chained continuation changed source, helper or evaluation selection authority")
    if revised:
        _validate_training_runtime_revision(config, old_pipeline, receipt, old, new, execution=execution)
    task = receipt["task_id"]
    pipeline_tail = _event_reference(receipt["predecessor_pipeline_event_tail_reference"], old_pipeline["pipeline_root"], tail=True)
    cohort_tail = _event_reference(receipt["predecessor_cohort_event_tail_reference"], Path(old["run_root"]) / "cohort", tail=True)
    events = core.read_event_chain(Path(old["run_root"]) / "cohort")
    if (pipeline_tail.get("stage") != "PIPELINE_BLOCKED" or cohort_tail.get("stage") != "INFRA_ERROR"
            or cohort_tail.get("task_id") != task or cohort_tail.get("details", {}).get("error_type") != "GraderInvocationFailure"):
        raise core.PipelineError("chained continuation needs the exact grading-blocked predecessor journals")
    folder = Path(old["run_root"]) / "cells/TRAINING" / task / "PDF_MEMORY"
    paths = {"old_cell_reference": folder / "cell.json", "audit_reference": folder / "execution-audit.json",
        "submission_reference": folder / "broker/submission.json", "submission_patch_reference": folder / "broker/submission.diff",
        "grader_pending_reference": folder / "grader-pending.json"}
    for key, path in paths.items():
        if receipt[key]["path"] != str(path):
            raise core.PipelineError("chained grading evidence is outside the exact original cell")
        core.check(receipt[key], decode=key != "submission_patch_reference")
    cell, audit, submission = (core.check(receipt[key]) for key in ("old_cell_reference", "audit_reference", "submission_reference"))
    prepared = [row for row in events if row.get("stage") == "PREPARED" and row.get("task_id") == task]
    config_sha = core.digest(canonical_bytes(old))
    if (cell.get("experiment_config") != receipt["old_execution_reference"]["path"]
            or len(prepared) != 1 or prepared[0].get("details", {}).get("cell_reference") != receipt["old_cell_reference"]
            or (folder / "cell.sha256").read_text().strip() != core.digest(canonical_bytes(cell))
            or cell.get("task_public", {}).get("task_id") != task or cell.get("phase") != "TRAINING"
            or cell.get("arm") != "PDF_MEMORY" or cell.get("bank_reference") is not None
            or audit.get("passed") is not True or audit.get("errors") != []
            or any(value.get("task_id") != task or value.get("configuration_sha256") != config_sha for value in (audit, submission))
            or not ((submission.get("agent_completed") is True and submission.get("reason") == "WORKER_SUBMITTED")
                or (revised and submission.get("agent_completed") is False and submission.get("reason") == "NATIVE_WORKER_WALL_LIMIT"
                    and isinstance(audit.get("workers"), list) and audit["workers"]
                    and any(worker.get("outcome") == "BUDGET_TIMEOUT" for worker in audit["workers"])
                    and all(worker.get("outcome") in {"COMPLETE", "BUDGET_TIMEOUT"} for worker in audit["workers"])))
            or any(value.get("patch_sha256") != receipt["submission_patch_reference"]["sha256"]
                   for value in (audit, submission, core.check(receipt["grader_pending_reference"])))
            or (folder / "public-result.json").exists() or (folder / "native-execution-failure.json").exists()):
        raise core.PipelineError("chained continuation requires a sealed successful native attempt and an undetermined grade")
    summary = core.check(receipt["official_summary_reference"])
    summary_root = Path(old["run_root"]) / "environment/TRAINING/cells/PDF_MEMORY" / task / "official-grader" / task / "report"
    counts = {"total_instances": 1, "submitted_instances": 1, "completed_instances": 1,
        "resolved_instances": 0, "unresolved_instances": 1, "ambiguous_failure_instances": 1,
        "infra_failure_instances": 0, "empty_patch_instances": 0, "error_instances": 0, "unstopped_instances": 0}
    if (Path(receipt["official_summary_reference"]["path"]).parent != summary_root
            or any(type(summary.get(key)) is not int or summary[key] != value for key, value in counts.items())
            or summary.get("failure_reasons") != {cell["target"]["instance_id"]: reasons[classification]}):
        raise core.PipelineError("chained continuation requires the exact single terminal ambiguous aggregate and matching reason")
    authority, old_authority = (core.check(item["scale_authority_reference"]) for item in (new, old))
    adoption = core.check(receipt["source_adoption_reference"])
    previous_adoption = core.check(old_authority["source_adoption_reference"])
    prefix, rows = previous_adoption["rows"], adoption["rows"]
    extra = rows[len(prefix):]
    completed = [row["task_id"] for row in events if row.get("stage") == "CELL_COMPLETE"]
    expected_ids = completed + [task]
    consumed = len(expected_ids)
    if (authority.get("source_adoption_reference") != receipt["source_adoption_reference"]
            or authority.get("purpose") != "TRAINING_INCREMENT" or authority.get("cumulative_training_count") != 120
            or rows[:len(prefix)] != prefix or [row["task_id"] for row in extra] != expected_ids
            or old_authority["task_ids"][:consumed] != expected_ids
            or [row["task_id"] for row in events if row.get("stage") == "PREPARED"] != expected_ids
            or authority.get("task_ids") != old_authority["task_ids"][consumed:] or not authority["task_ids"]
            or len({row["task_id"] for row in rows}) != len(rows)
            or adoption.get("predecessor_configrefs") != [*previous_adoption["predecessor_configrefs"], receipt["old_execution_reference"]]
            or adoption.get("source_count") != len(rows)
            or adoption.get("official_complete") != previous_adoption["official_complete"] + len(completed)):
        raise core.PipelineError("chained continuation must preserve every prior source and the exact untouched suffix")
    for row in extra:
        source_folder = Path(old["run_root"]) / "cells/TRAINING" / row["task_id"] / "PDF_MEMORY"
        if row["cell_reference"]["path"] != str(source_folder / "cell.json"):
            raise core.PipelineError("chained continuation sources must retain original owners")
        core.check(row["cell_reference"])
        if row["task_id"] != task:
            if (row.get("classification") != "OFFICIAL_COMPLETE"
                    or row.get("official_result_reference", {}).get("path") != str(source_folder / "public-result.json")):
                raise core.PipelineError("completed source must retain its original official result")
            core.check(row["official_result_reference"])
    final = extra[-1]
    if (final.get("classification") != classification
            or final.get("official_result_reference") is not None
            or final.get("official_summary_reference") != receipt["official_summary_reference"]
            or final["cell_reference"] != receipt["old_cell_reference"]):
        raise core.PipelineError("chained ambiguous source must remain undetermined without retry")
    if execution is not None:
        execution.execution_enrollment(new, core.check(new["dataset_manifest"]))
    _inherited_bank(config, config["training_stages"][0])
    return receipt


def validate_grading_continuation(config, *, execution=None, _historical_loader=False):
    """Adopt one sealed, unresolved grading attempt without solving/grading again."""
    reference = config.get("grading_continuation_reference")
    if reference is None:
        return None
    receipt = core.check(reference)
    if receipt.get("schema") in {CHAINED_CONTINUATION_SCHEMA, TRAINING_CONTINUATION_SCHEMA}:
        return _validate_chained_grading_continuation(config, receipt, execution=execution, historical_loader=_historical_loader)
    required = {"schema": CONTINUATION_SCHEMA, "operation": "CONTINUE_AFTER_UNDETERMINED_SOURCE_GRADE",
        "task_id": "swebench--mwaskom__seaborn-2766", "official_outcome": "UNDETERMINED",
        "resolved": None, "classification": "AMBIGUOUS_MISSING_MODULE", "source_only": True,
        "native_retries": False, "official_grader_retries": False, "model_calls": 0, "official_grader_runs": 0}
    if any(type(receipt.get(key)) is not type(value) or receipt.get(key) != value for key, value in required.items()):
        raise core.PipelineError("unsupported source-only grading continuation")
    old_pipeline = core.check(receipt["predecessor_pipeline_reference"])
    if old_pipeline.get("grading_continuation_reference") is not None:
        raise core.PipelineError("grading continuation cannot recursively authorize another interruption")
    validate_infrastructure_replacement(config, execution=execution)
    old, new = core.check(receipt["old_execution_reference"]), core.check(receipt["new_execution_reference"])
    task = receipt["task_id"]
    old_stage, stage = old_pipeline["training_stages"][1], config["training_stages"][1]
    if (old_stage["execution_reference"] != receipt["old_execution_reference"]
            or stage["execution_reference"] != receipt["new_execution_reference"]
            or config.get("training_experiment_reference") != receipt["new_execution_reference"]
            or config.get("supersedes_configuration_reference") != receipt["predecessor_pipeline_reference"]
            or core.read(Path(old_pipeline["pipeline_root"]) / "pipeline-binding.json") !=
               {"schema": SCHEMA, "configuration_reference": receipt["predecessor_pipeline_reference"]}
            or core.read(Path(old["run_root"]) / "cohort/cohort.json").get("experiment_reference") != receipt["old_execution_reference"]):
        raise core.PipelineError("grading continuation must bind the exact blocked predecessor configurations")
    allowed = {"run_root", "native_control_root", "scale_authority_reference", "prelaunch_revision", "source_root", "source_sha256"}
    loader_reference = receipt.get("loader_preflight_reference")
    native_reference = receipt.get("native_binary_reference")
    if loader_reference is not None:
        allowed.update(("loader_preflight_path", "loader_preflight_sha256"))
    if native_reference is not None:
        allowed.add("codex_binary")
    if ({k: v for k, v in old.items() if k not in allowed} != {k: v for k, v in new.items() if k not in allowed}
            or any(old[key] == new[key] for key in ("run_root", "native_control_root", "source_root"))
            or config["pipeline_root"] == old_pipeline["pipeline_root"]
            or stage.get("learning_root", str(Path(config["pipeline_root"]) / "learning-120")) ==
               old_stage.get("learning_root", str(Path(old_pipeline["pipeline_root"]) / "learning-120"))
            or config["training_stages"][0] != old_pipeline["training_stages"][0]):
        raise core.PipelineError("grading continuation changed the task protocol or reused immutable roots")
    for key in ("protocol_reference", "source_adoption_reference", "selection_policy", "reflection_max_bytes"):
        if config[key] != old_pipeline[key]:
            raise core.PipelineError("grading continuation changed pilot or selection authority")
    freeze = core.check(receipt["runtime_change_reference"])
    changed = [key for key in old["source_sha256"] if old["source_sha256"][key] != new["source_sha256"].get(key)]
    if (freeze.get("schema") != "skhynix/grading-continuation-runtime-freeze/1.0"
            or freeze.get("previous_execution_reference") != receipt["old_execution_reference"]
            or set(old["source_sha256"]) != set(new["source_sha256"])
            or changed != ["scripts/trimem_skhynix_architecture_run.py"]
            or freeze.get("changed_paths") != changed
            or any(freeze.get(key) != new[key] for key in ("source_root", "source_sha256"))
            or any(freeze.get("old_" + key) != old[key] for key in ("source_root", "source_sha256"))
            or freeze.get("model_calls") != 0 or freeze.get("official_grader_runs") != 0):
        raise core.PipelineError("grading continuation requires the exact frozen adoption-only runtime change")
    old_helpers, new_helpers = old_pipeline["helper_references"], config["helper_references"]
    if old_helpers.keys() != new_helpers.keys():
        raise core.PipelineError("grading continuation cannot replace source helpers")
    for before, after in [*(zip(old_helpers.values(), (new_helpers[key] for key in old_helpers))),
                          (old_pipeline["reflection_source_reference"], config["reflection_source_reference"])]:
        if (before["sha256"] != after["sha256"]
                or Path(before["path"]).relative_to(old["source_root"]) != Path(after["path"]).relative_to(new["source_root"])):
            raise core.PipelineError("grading continuation cannot change helper business logic")
        core.check(after, decode=False)
    old240 = core.check(old_pipeline["training_stages"][2]["execution_reference"])
    new240 = core.check(config["training_stages"][2]["execution_reference"])
    runtime_keys = {"source_root", "source_sha256", "prelaunch_revision"}
    if loader_reference is not None:
        runtime_keys.update(("loader_preflight_path", "loader_preflight_sha256"))
    if native_reference is not None:
        runtime_keys.add("codex_binary")
    if ({k: v for k, v in old240.items() if k not in runtime_keys} != {k: v for k, v in new240.items() if k not in runtime_keys}
            or any(new240[key] != new[key] for key in ("source_root", "source_sha256"))):
        raise core.PipelineError("grading continuation changed the future240 task protocol")
    if loader_reference is not None:
        core.check(loader_reference)
        for item in (new, new240):
            if (item.get("loader_preflight_path") != loader_reference["path"]
                    or item.get("loader_preflight_sha256") != loader_reference["sha256"]):
                raise core.PipelineError("continuation loader preflight differs between future execution stages")
        if execution is not None:
            if _historical_loader:
                _validate_historical_loader(loader_reference, new)
            else:
                import trimem_benchmark_run as benchmark
                benchmark.load_official_harness_loader_preflight(Path(loader_reference["path"]))
    if native_reference is not None:
        _validate_frozen_native_binary(native_reference, (new, new240), verify_bytes=execution is not None)
    _validate_aborted_native_launch(config, receipt, new)
    abandoned = receipt.get("abandoned_preparation_pipeline_reference")
    if abandoned is not None:
        if loader_reference is None:
            raise core.PipelineError("abandoned preparation requires a fresh exact loader preflight")
        prior = core.check(abandoned)
        prior_execution = core.check(prior["training_stages"][1]["execution_reference"])
        prior_root = Path(prior_execution["run_root"])
        prior_tail = _event_reference(receipt["abandoned_preparation_pipeline_event_tail_reference"], prior["pipeline_root"], tail=True)
        prior_cohort = _event_reference(receipt["abandoned_preparation_cohort_event_tail_reference"], prior_root / "cohort", tail=True)
        preparation_events = core.read_event_chain(prior_root / "cohort")
        preparation_task = core.check(new["scale_authority_reference"])["task_ids"][0]
        if (core.read(Path(prior["pipeline_root"]) / "pipeline-binding.json") !=
                {"schema": SCHEMA, "configuration_reference": abandoned}
                or core.read(prior_root / "cohort/cohort.json").get("experiment_reference") !=
                   prior["training_stages"][1]["execution_reference"]
                or prior_tail.get("stage") != "PIPELINE_BLOCKED"
                or [event.get("stage") for event in preparation_events] != ["PREPARE_STARTED", "INFRA_ERROR"]
                or prior_cohort.get("details", {}).get("error_type") != "BenchmarkProcessFailure"
                or prior_cohort.get("details", {}).get("error") !=
                   "official harness loader preflight current exact loader/environment identity differs"
                or any(event.get("task_id") != preparation_task for event in preparation_events)
                or list((prior_root / "cells").glob("**/cell.json"))
                or Path(prior_execution["native_control_root"]).exists()
                or config["pipeline_root"] == prior["pipeline_root"]
                or new["run_root"] == prior_execution["run_root"]
                or new["native_control_root"] == prior_execution["native_control_root"]):
            raise core.PipelineError("only pre-model loader preparation failure may be superseded")
    pipeline_tail = _event_reference(receipt["predecessor_pipeline_event_tail_reference"], old_pipeline["pipeline_root"], tail=True)
    cohort_tail = _event_reference(receipt["predecessor_cohort_event_tail_reference"], Path(old["run_root"]) / "cohort", tail=True)
    if (pipeline_tail.get("stage") != "PIPELINE_BLOCKED" or cohort_tail.get("stage") != "INFRA_ERROR"
            or cohort_tail.get("task_id") != task or cohort_tail.get("details", {}).get("error_type") != "GraderInvocationFailure"):
        raise core.PipelineError("grading continuation needs the exact grading-blocked predecessor journals")
    folder = Path(old["run_root"]) / "cells/TRAINING" / task / "PDF_MEMORY"
    paths = {"old_cell_reference": folder / "cell.json", "audit_reference": folder / "execution-audit.json",
        "submission_reference": folder / "broker/submission.json", "submission_patch_reference": folder / "broker/submission.diff",
        "grader_pending_reference": folder / "grader-pending.json"}
    for key, path in paths.items():
        if receipt[key]["path"] != str(path):
            raise core.PipelineError("grading evidence is outside the exact original cell")
        core.check(receipt[key], decode=key != "submission_patch_reference")
    cell, audit, submission = (core.check(receipt[key]) for key in ("old_cell_reference", "audit_reference", "submission_reference"))
    prior_events = core.read_event_chain(Path(old["run_root"]) / "cohort")
    prepared = [row for row in prior_events if row.get("stage") == "PREPARED" and row.get("task_id") == task]
    config_sha = core.digest(canonical_bytes(old))
    if (cell.get("experiment_config") != receipt["old_execution_reference"]["path"]
            or len(prepared) != 1 or prepared[0].get("details", {}).get("cell_reference") != receipt["old_cell_reference"]
            or (folder / "cell.sha256").read_text().strip() != core.digest(canonical_bytes(cell))
            or cell.get("task_public", {}).get("task_id") != task or cell.get("phase") != "TRAINING"
            or cell.get("arm") != "PDF_MEMORY" or cell.get("bank_reference") is not None
            or audit.get("passed") is not True or audit.get("errors") != []
            or any(value.get("task_id") != task or value.get("configuration_sha256") != config_sha for value in (audit, submission))
            or submission.get("agent_completed") is not True or submission.get("reason") != "WORKER_SUBMITTED"
            or any(value.get("patch_sha256") != receipt["submission_patch_reference"]["sha256"]
                   for value in (audit, submission, core.check(receipt["grader_pending_reference"])))
            or (folder / "public-result.json").exists() or (folder / "native-execution-failure.json").exists()):
        raise core.PipelineError("grading continuation requires a sealed successful native attempt with an undetermined grade")
    summary = core.check(receipt["official_summary_reference"])
    summary_root = Path(old["run_root"]) / "environment/TRAINING/cells/PDF_MEMORY" / task / "official-grader" / task / "report"
    counts = {"total_instances": 1, "submitted_instances": 1, "completed_instances": 1,
        "resolved_instances": 0, "unresolved_instances": 1, "ambiguous_failure_instances": 1,
        "infra_failure_instances": 0, "empty_patch_instances": 0, "error_instances": 0, "unstopped_instances": 0}
    if (Path(receipt["official_summary_reference"]["path"]).parent != summary_root
            or any(type(summary.get(key)) is not int or summary[key] != value for key, value in counts.items())
            or summary.get("failure_reasons") != {cell["target"]["instance_id"]: "missing_module"}):
        raise core.PipelineError("grading continuation requires the exact single ambiguous missing-module aggregate")
    authority, old_authority = (core.check(item["scale_authority_reference"]) for item in (new, old))
    adoption = core.check(receipt["source_adoption_reference"])
    previous_adoption = core.check(old_authority["source_adoption_reference"])
    rows = adoption["rows"]
    extra = rows[len(previous_adoption["rows"]):]
    completed = [row["task_id"] for row in prior_events if row.get("stage") == "CELL_COMPLETE"]
    extra_ids = [row["task_id"] for row in extra]
    expected_ids = completed + [task]
    if (authority.get("source_adoption_reference") != receipt["source_adoption_reference"]
            or authority.get("purpose") != "TRAINING_INCREMENT" or authority.get("cumulative_training_count") != 120
            or rows[:len(previous_adoption["rows"])] != previous_adoption["rows"]
            or len(previous_adoption["rows"]) != 21 or len(extra) != 15 or len(completed) != 14
            or extra_ids != expected_ids or old_authority["task_ids"][:15] != expected_ids
            or authority.get("task_ids") != old_authority["task_ids"][15:] or len(authority["task_ids"]) != 60
            or len({row["task_id"] for row in rows}) != 36
            or adoption.get("predecessor_configrefs") != [*previous_adoption["predecessor_configrefs"], receipt["old_execution_reference"]]
            or adoption.get("source_count") != 36 or adoption.get("official_complete") != 35):
        raise core.PipelineError("grading continuation must preserve exact adopted prefix and untouched60 suffix")
    for row in extra:
        expected_cell = Path(old["run_root"]) / "cells/TRAINING" / row["task_id"] / "PDF_MEMORY/cell.json"
        if row["cell_reference"]["path"] != str(expected_cell):
            raise core.PipelineError("grading continuation sources must retain their original owners")
        core.check(row["cell_reference"])
    if (extra[-1].get("classification") != "AMBIGUOUS_MISSING_MODULE"
            or extra[-1].get("official_result_reference") is not None
            or extra[-1].get("official_summary_reference") != receipt["official_summary_reference"]
            or extra[-1]["cell_reference"] != receipt["old_cell_reference"]
            or any(row.get("classification") != "OFFICIAL_COMPLETE" for row in extra[:-1])):
        raise core.PipelineError("ambiguous source must remain undetermined and must not be retried")
    if execution is not None:
        execution.execution_enrollment(new, core.check(new["dataset_manifest"]))
    _inherited_bank(config, config["training_stages"][0])
    return receipt


def selection(candidates, baseline):
    """Select only from complete development60 reports; never accept final data."""
    if (baseline.get("scope") != "DEVELOPMENT" or baseline.get("planned") != 60 or baseline.get("completed") != 60
            or type(baseline.get("resolved")) is not int or not 0 <= baseline["resolved"] <= 60
            or not isinstance(baseline.get("task_ids"), list) or len(baseline["task_ids"]) != 60
            or len(set(baseline["task_ids"])) != 60):
        raise core.PipelineError("selection needs the complete fixed development baseline")
    checked = []
    for row in candidates:
        if row.get("status") == "NOT_READY":
            continue
        if (row.get("scope") != "DEVELOPMENT" or row.get("planned") != 60
                or row.get("completed") != 60 or row.get("size") not in SIZES
                or type(row.get("resolved")) is not int or not 0 <= row["resolved"] <= 60
                or row.get("task_ids") != baseline.get("task_ids")):
            raise core.PipelineError("bank choice requires identical complete development tasks")
        checked.append(row)
    if not checked or len({row["size"] for row in checked}) != len(checked):
        raise core.PipelineError("bank choice needs unique ready candidates")
    winner = min(checked, key=lambda row: (-row["resolved"], row["size"]))
    return {"policy": SELECTION_POLICY, "selected_size": winner["size"],
            "selected_bank_reference": winner["bank_reference"],
            "development_resolved": winner["resolved"],
            "baseline_resolved": baseline["resolved"],
            "development_delta_percentage_points": 100 * (winner["resolved"] - baseline["resolved"]) / 60,
            "final_outcomes_used": False}


def write_execution(path, value):
    reference = core.retain(path, value)
    checksum = path.with_suffix(".sha256")
    raw = (core.digest(canonical_bytes(value)) + "\n").encode()
    if checksum.exists():
        if checksum.read_bytes() != raw:
            raise core.PipelineError("execution checksum changed")
    else:
        with checksum.open("xb") as stream:
            stream.write(raw)
    return reference


def validate_config(config, *, executing_source=None):
    if (config.get("schema") != SCHEMA or config.get("selection_policy") != SELECTION_POLICY
            or config.get("outcome_retries") is not False
            or [stage.get("size") for stage in config.get("training_stages", [])] != list(SIZES)):
        raise core.PipelineError("unsupported frozen scale protocol")
    for field in ("pipeline_root", "progress_root", "reflection_native_root", "evaluation_native_root"):
        core.absolute(config[field])
    for field in ("pipeline_source_reference", "source_adoption_reference", "protocol_reference",
                  "training_experiment_reference", "reflection_source_reference"):
        core.check(config[field], decode=field not in {"pipeline_source_reference", "reflection_source_reference"})
    if executing_source is not None and core.ref(executing_source) != config["pipeline_source_reference"]:
        raise core.PipelineError("scale controller differs from frozen source")
    for reference in config["helper_references"].values():
        core.check(reference, decode=False)
    previous_ids = set()
    for stage in config["training_stages"]:
        execution = core.check(stage["execution_reference"])
        dataset = core.check(execution["dataset_manifest"])
        ids = {row["target_id"] for row in dataset["targets"] if row["role"] == "TRAINING"}
        if len(ids) != stage["size"] or not previous_ids <= ids:
            raise core.PipelineError("source collections must be nested exact24/120/240")
        previous_ids = ids
        if execution.get("model") != "gpt-6-astra" or execution.get("reasoning_effort") != "high":
            raise core.PipelineError("all new workers must retain the requested model/high effort")
        if (execution.get("authentication") != "CHATGPT" or execution.get("phase") != "TRAINING_RUNTIME"
                or execution.get("limits", {}).get("task_requests") != 120
                or execution.get("limits", {}).get("task_seconds") != 1200):
            raise core.PipelineError("new training execution differs from common frozen budget/authentication")
        authority = core.check(execution["scale_authority_reference"])
        if authority.get("dataset_reference") != execution["dataset_manifest"]:
            raise core.PipelineError("execution authority must bind the exact cumulative dataset")
        if "learning_root" in stage:
            core.absolute(stage["learning_root"])
    roots = [core.check(s["execution_reference"])["run_root"] for s in config["training_stages"]]
    roots += [str(Path(config["pipeline_root"]) / "development"), str(Path(config["pipeline_root"]) / "final")]
    if len(set(roots)) != len(roots):
        raise core.PipelineError("training and evaluation roots must remain separate")
    for index, stage in enumerate(config["training_stages"]):
        experiment = core.check(stage["execution_reference"])
        authority = core.check(experiment["scale_authority_reference"])
        adoption_ref = authority.get("source_adoption_reference")
        if index == 0 and adoption_ref != config["source_adoption_reference"]:
            raise core.PipelineError("pilot adoption must retain its exact original authority")
        if index and adoption_ref and not (config.get("infrastructure_replacement_reference") or config.get("grading_continuation_reference")):
            raise core.PipelineError("increment source migration requires an explicit recovery protocol")
    validate_infrastructure_replacement(config)
    validate_grading_continuation(config)


class ScalePipeline(core.Pipeline):
    """Reuse the audited native publisher and append-only journal, not old scope."""

    def __init__(self, config_path, *, operations=None, clock=time.time):
        self.path = core.absolute(config_path)
        self.reference = core.ref(self.path)
        self.config = core.read(self.path)
        if self.path.with_suffix(".sha256").read_text().strip() != core.digest(canonical_bytes(self.config)):
            raise core.PipelineError("scale pipeline checksum differs")
        validate_config(self.config, executing_source=Path(__file__).resolve())
        self.root, self.clock = Path(self.config["pipeline_root"]), clock
        self.root.mkdir(parents=True, exist_ok=True)
        core.retain(self.root / "pipeline-binding.json", {"schema": SCHEMA, "configuration_reference": self.reference})
        (self.root / "events").mkdir(exist_ok=True)
        # FrozenOperations binds imports to the new runtime snapshot and audits
        # native publisher provenance. Old model execution is never imported/run.
        self.operations = operations or core.FrozenOperations(self.config)
        self.training = core.check(self.config["training_experiment_reference"])
        self.base_reflection_root = self.config["reflection_native_root"]
        self.adoption = core.check(self.config["source_adoption_reference"])
        if self.config.get("infrastructure_replacement_reference"):
            execution = self.operations.modules["cohort"].execution
            validate_infrastructure_replacement(self.config, execution=execution)
            for stage in self.config["training_stages"]:
                experiment = core.check(stage["execution_reference"])
                execution.execution_enrollment(experiment, core.check(experiment["dataset_manifest"]))
        if self.config.get("grading_continuation_reference"):
            validate_grading_continuation(self.config, execution=self.operations.modules["cohort"].execution)

    def progress(self):
        value = self.status()
        value["updated_at"] = datetime.now(timezone.utc).isoformat()
        output = Path(self.config["progress_root"])
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        reference = core.retain(output / "progress-history" / (stamp + ".json"), value)
        temporary = output / "progress.next.json"
        temporary.write_bytes(canonical_bytes(value) + b"\n")
        temporary.replace(output / "progress.json")
        return reference

    def _source_cells(self, through_size):
        refs = [row["cell_reference"] for row in core.check(self.config["source_adoption_reference"])["rows"]]
        seen_adoptions = [self.config["source_adoption_reference"]]
        for stage in self.config["training_stages"]:
            if stage["size"] > through_size:
                break
            config = core.check(stage["execution_reference"])
            adoption_ref = core.check(config["scale_authority_reference"]).get("source_adoption_reference")
            if adoption_ref is not None and adoption_ref not in seen_adoptions:
                refs.extend(row["cell_reference"] for row in core.check(adoption_ref)["rows"])
                seen_adoptions.append(adoption_ref)
            for path in sorted((Path(config["run_root"]) / "cells/TRAINING").glob("*/PDF_MEMORY/cell.json")):
                cell = core.read(path)
                state = core.read(Path(cell["broker_root"]) / "state.json")
                # An interrupted active task is resumed by its original cohort;
                # it cannot become a captured source until submission/audit.
                if state["status"] == "SUBMITTED" and (path.parent / "execution-audit.json").exists():
                    audit = core.read(path.parent / "execution-audit.json")
                    if audit.get("passed") is True:
                        refs.append(core.ref(path))
        ids = [core.check(ref)["task_public"]["task_id"] for ref in refs]
        if len(ids) != len(set(ids)):
            raise core.PipelineError("source adoption would repeat a solved task")
        dataset = core.check(core.check(next(stage["execution_reference"] for stage in self.config["training_stages"]
            if stage["size"] == through_size))["dataset_manifest"])
        permitted = {row["target_id"] for row in dataset["targets"] if row["role"] == "TRAINING"}
        if not set(ids) <= permitted:
            raise core.PipelineError("source adoption escaped the exact cumulative stage")
        if self.config.get("infrastructure_replacement_reference"):
            failed = core.check(self.config["infrastructure_replacement_reference"])["old_cell_reference"]
            if any(ref["path"] == failed["path"] for ref in refs):
                raise core.PipelineError("failed infrastructure attempt cannot enter the memory bank")
        return refs

    def _learning(self, stage):
        modules = self.operations.modules
        config = core.check(stage["execution_reference"])
        self.training = config
        self.operations.training = config
        self.learning_root = Path(stage.get("learning_root", self.root / ("learning-" + str(stage["size"]))))
        candidates = list(core.check(self.config["source_adoption_reference"])["predecessor_configrefs"])
        for item in self.config["training_stages"]:
            if item["size"] > stage["size"]:
                break
            source_config = core.check(item["execution_reference"])
            adoption_ref = core.check(source_config["scale_authority_reference"]).get("source_adoption_reference")
            if adoption_ref is not None:
                candidates.extend(core.check(adoption_ref)["predecessor_configrefs"])
            candidates.append(item["execution_reference"])
        references = []
        for reference in candidates:
            if reference not in references:
                references.append(reference)
        enrollment = modules["learning"].initialize_learning(self.learning_root,
            execution_references=references, dataset_reference=config["dataset_manifest"])
        self._capture_sources(self._source_cells(stage["size"]))
        return enrollment

    def _capture_sources(self, references):
        learning = self.operations.modules["learning"]
        pending = references
        if self.config.get("grading_continuation_reference"):
            # Validate enrollment once, then every immutable original receipt.
            # Reopening the same cumulative enrollment for every already-captured
            # source recursively loads all historical runtimes dozens of times.
            pending = []
            with learning._session(self.learning_root, mutable=False) as (_, _, registry, _):
                for reference in references:
                    core.check(reference)
                    identity = learning.memory._hash({"cell_path": str(learning.memory._path(reference["path"]))})
                    retained = registry["cells"].get(identity)
                    if retained is None:
                        pending.append(reference)
                        continue
                    receipt = learning._checked_cell_receipt(retained)
                    if (receipt.get("cell_path") != reference["path"]
                            or receipt.get("source_references", {}).get("cell.json") != reference
                            or receipt.get("status") not in {"CAPTURED", "NO_PUBLIC_ATTEMPTS"}):
                        raise core.PipelineError("retained capture differs from the exact source or is incomplete")
        for reference in pending:
            core.check(reference)
            learning.capture_cell(self.learning_root, reference["path"])

    def _runner(self, stage):
        config = core.check(stage["execution_reference"])
        root = Path(config["run_root"]) / "cohort"
        if str(root) in self.operations.cohorts:
            return self.operations.cohorts[str(root)]
        cohort, cleanup = self.operations.modules["cohort"], self.operations.modules["cleanup"]
        hook = self.operations.modules["learning"].make_capture_hook(self.learning_root)
        if (root / "cohort.json").exists():
            runner = cohort.CohortRunner(root, learning_hook=hook, cleanup_operations=cleanup)
        else:
            Path(config["run_root"]).mkdir(parents=True, exist_ok=True)
            policy = cleanup.create_cleanup_policy(Path(config["run_root"]) / "cleanup-policy.json",
                experiment_reference=stage["execution_reference"])
            runner = cohort.CohortRunner.create(root, experiment_path=stage["execution_reference"]["path"],
                phase="TRAINING", learning_root=self.learning_root, learning_hook=hook,
                cleanup_policy_reference=policy, cleanup_operations=cleanup)
        self.operations.cohorts[str(root)] = runner
        return runner

    def _advance_runner(self, runner, job):
        status = runner.status()
        while status["status"] != "COMPLETE":
            self.record("COHORT_ADVANCE_STARTED", {"completed_before": status["completed_cells"],
                "planned_cells": status["planned_cells"], "cohort_root": str(runner.root)}, job=job)
            previous = status["completed_cells"]
            status = runner.run(cell_limit=1)
            self.record("COHORT_PROGRESS", {"status": {k: v for k, v in status.items() if k != "cells"}}, job=job)
            self.progress()
            if status["status"] == "BLOCKED":
                raise core.PipelineError("cohort blocked; immutable attempt preserved, no native outcome retry: " + job)
            if status["completed_cells"] - previous not in (0, 1):
                raise core.PipelineError("one-cell advance has an invalid completion count")
            if status["completed_cells"] == previous and status["status"] != "COMPLETE":
                raise core.PipelineError("cohort failed to advance")
        if not status.get("terminal_full_audit_complete"):
            raise core.PipelineError("completed cohort lacks its full retained-evidence audit")
        return status

    def _bank(self, stage):
        size, name = stage["size"], "bank-" + str(stage["size"])
        self.training = core.check(stage["execution_reference"])
        self.operations.training = self.training
        self.learning_root = Path(stage.get("learning_root", self.root / ("learning-" + str(size))))
        plan_path = Path(self.base_reflection_root) / name / "reflection-plan.json"
        existing = self.latest("BANK_READY", name) or self.latest("BANK_NOT_READY", name)
        if existing:
            core.check(existing["details"]["reference"])
            return core.check(existing["details"]["reference"])
        inherited = _inherited_bank(self.config, stage)
        if inherited is not None:
            receipt = core.check(stage["inherited_bank_reference"])
            self.record("BANK_NOT_READY", {"reference": receipt["result_reference"],
                "inherited_bank_reference": stage["inherited_bank_reference"], "reflection_repeated": False}, job=name)
            self.progress()
            return inherited
        frozen_marker = self.learning_root / "learning-frozen.json"
        if frozen_marker.exists():
            # Recover a completed publication before any mutable capture/export
            # call; this never relaunches a publisher or rewrites frozen memory.
            return self._finish_bank(stage, core.read(frozen_marker), core.ref(plan_path))
        self._learning(stage)
        runner = self._runner(stage)
        status = self._advance_runner(runner, name)
        # Reimport exact historical sources into this independent cumulative bank.
        refs = self._source_cells(size)
        if len(refs) != size:
            raise core.PipelineError("not every enrolled source has a sealed attempt")
        self._capture_sources(refs)
        reflection = core.import_frozen_helper("scale_reflection", self.config["reflection_source_reference"], list(__import__("sys").path))
        plan_reference = reflection.build_reflection_plan(self.learning_root, plan_path,
            max_bytes=190000, max_sources_per_batch=8)
        plan = core.check(plan_reference)
        self.config["reflection_native_root"] = str(Path(self.base_reflection_root) / name)
        self.config["adopted_reflections"] = []
        for job in plan["jobs"]:
            # The inherited publisher flow keys events by repository; use the
            # immutable unique batch identity while preserving true repo in plan.
            self._reflect({**job, "repository": name + ":" + job["job_id"]})
            self.progress()
        output = self.root / name / "bank.json"
        frozen_marker = self.learning_root / "learning-frozen.json"
        try:
            if frozen_marker.exists():
                publication_ref = core.read(frozen_marker)
                publication = core.check(publication_ref)
                bank = {key: publication["bank"][key] for key in ("path", "sha256")}
            else:
                publication_result = self.operations.modules["learning"].freeze_published_bank(self.learning_root, output)
                publication_ref = publication_result["publication_reference"]
                publication = core.check(publication_ref)
                bank = {key: publication_result[key] for key in ("path", "sha256")}
        except ValueError as exc:
            catalog = core.read(self.learning_root / "catalog.json")
            missing_layers = str(exc) == "Scale bank publication requires actual L1 episodes and L2 nodes and edges"
            missing_skills = not catalog["skills"] and any(text in str(exc) for text in
                ("actually promoted Gate B skill", "reflection proposal validation receipts"))
            if not (missing_layers or missing_skills):
                raise
            result = {"size": size, "status": "NOT_READY", "reason": "MISSING_POPULATED_LAYERS" if missing_layers else "NO_VERIFIED_GATE_B_SKILL",
                "source_attempts": size, "publication_error": str(exc), "reflection_plan_reference": plan_reference,
                "catalog_reference": core.ref(self.learning_root / "catalog.json"), "bank_reference": None}
            reference = core.retain(self.root / name / "bank-status.json", result)
            self.record("BANK_NOT_READY", {"reference": reference}, job=name)
            self.progress()
            return result
        return self._finish_bank(stage, publication_ref, plan_reference)

    def _finish_bank(self, stage, publication_ref, plan_reference):
        size, name = stage["size"], "bank-" + str(stage["size"])
        publication = core.check(publication_ref)
        bank = {key: publication["bank"][key] for key in ("path", "sha256")}
        if (publication.get("actual_training_sources") != size
                or publication.get("enrollment_reference") != core.ref(self.learning_root / "learning-enrollment.json")
                or bank["path"] != str(self.root / name / "bank.json")):
            raise core.PipelineError("published bank does not bind every cumulative source")
        counts = self.operations.validate_bank(bank)
        result = {"size": size, "status": "READY", "source_attempts": size,
            "bank_reference": bank, "publication_reference": publication_ref,
            "reflection_plan_reference": plan_reference, "layer_counts": counts}
        reference = core.retain(self.root / name / "bank-status.json", result)
        self.record("BANK_READY", {"reference": reference}, job=name)
        self.progress()
        return result

    def _evaluation(self, purpose, stage, bank_reference, name):
        modules = self.operations.modules
        template = core.check(stage["execution_reference"])
        if self.config.get("grading_continuation_reference"):
            # Every future arm uses the same retained adoption-capable runtime,
            # including the baseline whose dataset remains the pilot manifest.
            runtime = core.check(self.config["training_experiment_reference"])
            template = {**template, **{key: runtime[key] for key in
                ("source_root", "source_sha256", "loader_preflight_path", "loader_preflight_sha256", "codex_binary")}}
        root = self.root / ("final" if purpose == "FINAL_EVALUATION" else "development") / name
        root.mkdir(parents=True, exist_ok=True)
        authority = modules["cohort"].execution.create_execution_enrollment(root / "execution-authority.json",
            dataset_reference=template["dataset_manifest"], purpose=purpose, bank_reference=bank_reference)
        value = {**template, "phase": "EVALUATION_RUNTIME", "evaluation_status": "EVALUATION_READY",
            "run_root": str(root / "run"), "native_control_root": str(Path(self.config["evaluation_native_root"]) / name),
            "scale_authority_reference": authority, "frozen_bank_reference": bank_reference,
            "pipeline_reference": self.reference}
        value.pop("training_grade_hold_policy", None)
        experiment = write_execution(root / "execution.json", value)
        cohort_root = root / "run/cohort"
        quarantine_root = root / "run/quarantine"
        Path(value["run_root"]).mkdir(parents=True, exist_ok=True)
        quarantine = modules["quarantine"].initialize_quarantine(quarantine_root,
            execution_reference=experiment, bank_reference=bank_reference)
        hook = modules["quarantine"].make_quarantine_hook(quarantine_root)
        policy = modules["cleanup"].create_cleanup_policy(root / "cleanup-policy.json", experiment_reference=experiment)
        if (cohort_root / "cohort.json").exists():
            runner = modules["cohort"].CohortRunner(cohort_root, quarantine_hook=hook, cleanup_operations=modules["cleanup"])
        else:
            runner = modules["cohort"].CohortRunner.create(cohort_root, experiment_path=experiment["path"],
                phase="EVALUATION", bank_reference=bank_reference, quarantine_root=quarantine_root,
                quarantine_hook=hook, cleanup_policy_reference=policy, cleanup_operations=modules["cleanup"])
        self.operations.cohorts[str(cohort_root)] = runner
        if not self.latest("EVALUATION_CONFIGURED", name):
            self.record("EVALUATION_CONFIGURED", {"experiment_reference": experiment,
                "cohort_reference": core.ref(cohort_root / "cohort.json"), "quarantine_reference": quarantine,
                "purpose": purpose}, job=name)
        self._advance_runner(runner, name)
        results = []
        for row in runner.schedule:
            public, reference = runner._validate_result(row)
            results.append({"task_id": row["task_id"], "arm": row["arm"], "resolved": public["resolved"],
                "reference": reference, "requests": public["broker_status"]["submission"]["actions"],
                "memory_injections": public["broker_status"]["memory_injections"],
                "grader_wall_time_ms": public["grader_wall_time_ms"]})
        scope = "FINAL" if purpose == "FINAL_EVALUATION" else "DEVELOPMENT"
        report = {"scope": scope, "planned": len(runner.schedule), "completed": len(results),
            "resolved": sum(row["resolved"] for row in results), "task_ids": sorted({row["task_id"] for row in results}),
            "rows": results, "bank_reference": bank_reference, "size": stage["size"],
            "status": "COMPLETE", "experiment_reference": experiment}
        if scope == "FINAL":
            report["by_arm"] = {arm: {"planned": 500, "completed": len(selected),
                "resolved": sum(row["resolved"] for row in selected),
                "solve_rate": sum(row["resolved"] for row in selected) / 500}
                for arm in ("BASELINE", "PDF_MEMORY")
                for selected in ([row for row in results if row["arm"] == arm],)}
            report["delta_percentage_points"] = 100 * (report["by_arm"]["PDF_MEMORY"]["solve_rate"] - report["by_arm"]["BASELINE"]["solve_rate"])
        reference = core.retain(root / "report.json", report)
        if not self.latest("EVALUATION_COMPLETE", name):
            self.record("EVALUATION_COMPLETE", {"report_reference": reference, "scope": scope}, job=name)
        self.progress()
        return report, reference

    @contextmanager
    def _controller_locks(self):
        """Keep every adopted controller stopped, including earlier scale runs."""
        extra = self.adoption.get("predecessor_pipeline_event_tail_references", [])
        if not isinstance(extra, list):
            raise core.PipelineError("predecessor pipeline tails must be a list")
        tails = [self.adoption["original_pipeline_event_tail_reference"], *extra]
        recovery = None
        continuation = None
        for name in ("infrastructure_replacement_reference", "grading_continuation_reference"):
            if not self.config.get(name):
                continue
            receipt = core.check(self.config[name])
            if name == "infrastructure_replacement_reference":
                recovery = receipt
            else:
                continuation = receipt
            for key in ("predecessor_pipeline_event_tail_reference", "predecessor_cohort_event_tail_reference"):
                if receipt[key] not in tails:
                    tails.append(receipt[key])
            for key in ("abandoned_preparation_pipeline_event_tail_reference", "abandoned_preparation_cohort_event_tail_reference",
                        "aborted_native_launch_pipeline_event_tail_reference", "aborted_native_launch_cohort_event_tail_reference"):
                if receipt.get(key) is not None and receipt[key] not in tails:
                    tails.append(receipt[key])
        for _, receipt in _grading_lineage(self.config)[1:]:
            for key in ("predecessor_pipeline_event_tail_reference", "predecessor_cohort_event_tail_reference",
                        "abandoned_preparation_pipeline_event_tail_reference", "abandoned_preparation_cohort_event_tail_reference",
                        "aborted_native_launch_pipeline_event_tail_reference", "aborted_native_launch_cohort_event_tail_reference"):
                if receipt.get(key) is not None and receipt[key] not in tails:
                    tails.append(receipt[key])
        predecessors = {}
        for tail in tails:
            core.check(tail)
            path = core.absolute(tail["path"])
            root = path.parent.parent
            if path.parent.name != "events" or path.suffix != ".json" or root == self.root or root in predecessors:
                raise core.PipelineError("predecessor pipeline roots must be distinct retained event journals")
            predecessors[root] = tail
        with ExitStack() as stack:
            for root in sorted([*predecessors, self.root], key=str):
                stack.enter_context(locked(root / "run.lock"))
            core.check(self.reference)
            for root, tail in predecessors.items():
                core.check(tail)
                events = sorted((root / "events").glob("*.json"))
                if not events or core.ref(events[-1]) != tail:
                    raise core.PipelineError("superseded controller advanced after source adoption")
            if recovery is not None:
                validate_infrastructure_replacement(self.config, execution=self.operations.modules["cohort"].execution)
            if continuation is not None:
                validate_grading_continuation(self.config, execution=self.operations.modules["cohort"].execution)
            yield

    def run(self):
        with self._controller_locks():
            if self.latest("PIPELINE_COMPLETE") or self.latest("NO_READY_MEMORY_BANK"):
                return self.status()
            try:
                banks = [self._bank(stage) for stage in self.config["training_stages"]]
                ready = [bank for bank in banks if bank["status"] == "READY"]
                if not ready:
                    self.record("NO_READY_MEMORY_BANK", {"source_attempts": 240, "final_evaluation_cells": 0,
                        "gate_b_waived": False, "banks": banks})
                    self.progress()
                    return self.status()
                stage_by_size = {stage["size"]: stage for stage in self.config["training_stages"]}
                baseline, baseline_ref = self._evaluation("DEVELOPMENT_BASELINE", stage_by_size[24], None, "baseline")
                candidates, references = [], []
                for bank in ready:
                    report, reference = self._evaluation("DEVELOPMENT_BANK", stage_by_size[bank["size"]],
                        bank["bank_reference"], "bank-" + str(bank["size"]))
                    candidates.append(report)
                    references.append(reference)
                chosen = selection(candidates, baseline)
                chosen.update(baseline_report_reference=baseline_ref, candidate_report_references=references,
                    protocol_reference=self.config["protocol_reference"])
                choice_ref = core.retain(self.root / "bank-selection.json", chosen)
                if not self.latest("BANK_SELECTED"):
                    self.record("BANK_SELECTED", {"reference": choice_ref})
                final, final_ref = self._evaluation("FINAL_EVALUATION", stage_by_size[chosen["selected_size"]],
                    chosen["selected_bank_reference"], "verified500")
                self.record("PIPELINE_COMPLETE", {"report_reference": final_ref, "selection_reference": choice_ref,
                    "source_attempts": 240, "final_cells": 1000, "development_cells": 60 * (1 + len(ready))})
            except Exception as exc:
                self.record("PIPELINE_BLOCKED", {"error_type": type(exc).__name__, "reason": str(exc)[:2000],
                    "native_outcome_retries": False, "final_outcomes_used_for_training": False})
                self.progress()
                raise
            self.progress()
            return self.status()

    def status(self):
        events = self.events()
        last = events[-1] if events else None
        state = "COMPLETE" if self.latest("PIPELINE_COMPLETE") else "NOT_READY" if self.latest("NO_READY_MEMORY_BANK") else (
            "BLOCKED" if last and last["stage"] == "PIPELINE_BLOCKED" else "IN_PROGRESS")
        cohorts = {}
        for event in events:
            if event["stage"] == "COHORT_PROGRESS":
                raw = event["details"]["status"]
                cohorts[event["job"]] = {key: raw.get(key) for key in
                    ("status", "planned_cells", "completed_cells", "phase", "by_arm")}
        banks = {event["job"]: core.check(event["details"]["reference"]) for event in events
                 if event["stage"] in {"BANK_READY", "BANK_NOT_READY"}}
        return {"schema": SCHEMA, "status": state, "configuration_reference": self.reference,
            "planned_source_sizes": list(SIZES), "adopted_source_attempts": self.adoption["source_count"],
            "adopted_official_complete": self.adoption["official_complete"],
            "adopted_official_undetermined": self.adoption["source_count"] - self.adoption["official_complete"],
            "development_tasks": 60, "final_tasks": 500, "final_cells": 1000,
            "cohorts": cohorts, "banks": banks, "last_event": last,
            "selection_policy": SELECTION_POLICY, "native_outcome_retries": False,
            "infrastructure_replacement_reference": self.config.get("infrastructure_replacement_reference"),
            "authorized_native_infrastructure_replacements": int(bool(self.config.get("infrastructure_replacement_reference"))
                and not self.config.get("grading_continuation_reference")),
            "grading_continuation_reference": self.config.get("grading_continuation_reference"),
            "historical_native_infrastructure_replacements": int(bool(self.config.get("infrastructure_replacement_reference"))),
            "stage_adopted_source_attempts": {str(stage["size"]): sum(len(adoption["rows"])
                for reference, adoption in _stage_adoptions(self.config, stage["size"])
                if reference != self.config["source_adoption_reference"]) for stage in self.config["training_stages"]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "status", "validate"))
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    if args.command == "validate":
        validate_config(core.read(args.config), executing_source=Path(__file__).resolve())
        value = {"status": "VALIDATED", "model_calls": 0, "official_grader_runs": 0}
    else:
        pipeline = ScalePipeline(args.config)
        value = pipeline.run() if args.command == "run" else pipeline.status()
    print(json.dumps(value, ensure_ascii=False))


if __name__ == "__main__":
    main()
