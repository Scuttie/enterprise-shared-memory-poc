"""Small public-metadata health observation; no runtime imports or process claims."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sqlite3
import time

SCHEMA = "skhynix/scale-health/1.0"
EVENTS = set("COHORT_ADVANCE_STARTED COHORT_PROGRESS PIPELINE_BLOCKED PIPELINE_COMPLETE PIPELINE_COMPLETE_WITH_UNDETERMINED NO_READY_MEMORY_BANK BANK_READY BANK_NOT_READY BANK_SELECTED EVALUATION_COMPLETE EVALUATION_CONFIGURED REFLECTION_PLAN REFLECTION_SKIPPED REFLECTION_EXPORTED PUBLISH_STARTED PUBLISHED INGEST_STARTED PROPOSALS_INGESTED BANK_FREEZE_STARTED BANK_FROZEN PUBLIC_PROGRESS PREPARE_STARTED PREPARED SOLVE_STARTED SOLVE_COMPLETE GRADE_STARTED GRADED GRADE_UNDETERMINED LEARN_STARTED LEARNED CELL_COMPLETE CLEANED INFRA_ERROR DISK_BLOCK CONTROLLER_SUPERSESSION".split())
ERRORS = set("PipelineError CohortError GraderInvocationFailure ValueError RuntimeError OSError TimeoutError FileNotFoundError NativeQuotaPaused".split())
CONTINUATION_SCHEMA = "skhynix/evaluation-continuation-pipeline/1.0"
AMENDMENT_SCHEMA = "skhynix/evaluation-accounting-amendment/1.0"
CONTINUATION_POLICY = "RETAIN_TERMINAL_AMBIGUITY_UNSCORED_AND_CONTINUE_FIXED_SCHEDULE"
QUOTA_CONTINUATION_SCHEMA = "skhynix/evaluation-quota-continuation-pipeline/1.0"
QUOTA_AMENDMENT_SCHEMA = "skhynix/evaluation-native-quota-amendment/1.0"
QUOTA_HOLD_SCHEMA = "skhynix/evaluation-native-quota-undetermined/1.0"
QUOTA_POLICY = "RETAIN_NATIVE_SERVICE_USAGE_LIMIT_UNSCORED_AND_CONTINUE_FIXED_SCHEDULE"


class ProbeError(ValueError):
    pass


def _stamp(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _read(path, retries=3, *, sha256=None, with_digest=False):
    """Detect append, replacement and partial writes; never print input or errors."""
    for _ in range(retries):
        try:
            before = _stamp(path)
            if before[2] > 32 * 1024 * 1024:
                raise ProbeError("FILE_TOO_LARGE")
            raw = path.read_bytes()
            if before != _stamp(path):
                continue
            if sha256 is not None and hashlib.sha256(raw).hexdigest() != sha256:
                raise ProbeError("REFERENCE_HASH_MISMATCH")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ProbeError("MALFORMED_JSON")
            result = value, before[3] / 1e9
            return (*result, hashlib.sha256(raw).hexdigest()) if with_digest else result
        except FileNotFoundError:
            continue
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    raise ProbeError("MISSING_MALFORMED_OR_RACING_FILE")


def _latest(directory):
    return max((p for p in directory.glob("*.json") if re.fullmatch(r"[0-9]+\.json", p.name)),
               key=lambda p: int(p.stem), default=None)


def _tail(directory, retries=3):
    for _ in range(retries):
        path = _latest(directory)
        if path is None:
            return {}, 0.0
        try:
            value, stamp = _read(path, 1)
            if path == _latest(directory):
                return value, stamp
        except ProbeError:
            pass
    raise ProbeError("JOURNAL_RACE_OR_MALFORMED")


def _number(value):
    return value if type(value) is int and value >= 0 else None


def _when(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) and value >= 0 else 0.0


def _task(value):
    return value if isinstance(value, str) and re.fullmatch(r"swebench(?:_verified)?--[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-[0-9]+", value) else None


def _event(value):
    details = value.get("details", {})
    details = details if isinstance(details, dict) else {}
    return {"stage": value.get("stage") if isinstance(value.get("stage"), str) and value.get("stage") in EVENTS else "UNKNOWN",
            "at": _when(value.get("at")), "task_id": _task(value.get("task_id")),
            "error_type": details.get("error_type") if isinstance(details.get("error_type"), str) and details.get("error_type") in ERRORS else None}


class _Probe:
    def __init__(self, retries):
        self.retries, self.activity, self.warnings = retries, [], set()

    def read(self, path, *, optional=False):
        path = Path(path)
        if optional and not path.exists():
            return {}
        try:
            value, stamp = _read(path, self.retries)
            return value
        except (OSError, ProbeError, TypeError, ValueError):
            self.warnings.add("MISSING_OR_INVALID_PUBLIC_METADATA")
            return {}

    def touch(self, path):
        try:
            self.activity.append(_stamp(Path(path))[3] / 1e9)
        except OSError:
            pass

    def reference(self, reference):
        self.reference_metadata(reference)
        return _read(Path(reference["path"]), self.retries, sha256=reference["sha256"])[0]

    @staticmethod
    def reference_metadata(reference):
        """Validate a public hash binding without opening its potentially private source."""
        if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"}
                or not isinstance(reference["path"], str) or not Path(reference["path"]).is_absolute()
                or not isinstance(reference["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", reference["sha256"]) is None):
            raise ProbeError("INVALID_REFERENCE")

    def tail(self, root):
        try:
            value, stamp = _tail(Path(root) / "events", self.retries)
            if value:
                self.activity.extend((stamp, _when(value.get("at"))))
            return value
        except (OSError, ProbeError):
            self.warnings.add("JOURNAL_RACE_OR_MALFORMED")
            return {}

    def cohort(self, root, *, manifest=None, accounting=None):
        root = Path(root)
        event = self.tail(root)
        if manifest is None:
            manifest = self.read(root / "cohort.json", optional=True)
        schedule = manifest.get("schedule", [])
        if not isinstance(schedule, list) or len(schedule) > 1000:
            self.warnings.add("INVALID_SCHEDULE")
            schedule = []
        official = resolved = 0
        selected = None
        for row in schedule:
            if not isinstance(row, dict) or not _task(row.get("task_id")):
                self.warnings.add("INVALID_SCHEDULE")
                continue
            cell = Path(row.get("cell_config", ""))
            expected = root.parent / "cells" / manifest.get("phase", "TRAINING") / row["task_id"] / row.get("arm", "PDF_MEMORY") / "cell.json"
            if cell != expected:
                self.warnings.add("CELL_PATH_MISMATCH")
                continue
            public = self.read(cell.parent / "public-result.json", optional=True)
            if public.get("official") is True and public.get("grader_status") == "success" and type(public.get("resolved")) is bool and public.get("task_id") == row["task_id"] and public.get("arm") == row.get("arm"):
                official += 1
                resolved += int(public["resolved"])
            if row["task_id"] == event.get("task_id") and row.get("arm") == event.get("arm"):
                selected = cell
        current = {"state": "PREPARING" if event.get("stage") == "PREPARE_STARTED" else "NO_ACTIVE_CELL"}
        if selected is not None:
            broker = selected.parent / "broker"
            state = self.read(broker / "state.json", optional=event.get("stage") == "PREPARE_STARTED")
            if state:
                self.touch(broker / "state.json")
                self.touch(broker / "events.jsonl")
                workers = state.get("workers", {})
                workers = workers if isinstance(workers, dict) else {}
                counts = Counter(w.get("status") for w in workers.values() if isinstance(w, dict) and w.get("status") in {"ISSUED", "ADMITTED", "REVOKED"})
                status = state.get("status")
                pending = _number(state.get("unfinished_actions"))
                active = workers.get(state.get("current_worker"), {}) if isinstance(state.get("current_worker"), str) else {}
                mode = {"SUBMITTED": "SUBMITTED", "WAITING_HANDOFF": "AWAITING_WORKER", "WAITING_ADMISSION": "AWAITING_ADMISSION", "TERMINATED": "TERMINATED"}.get(status, "UNKNOWN") if isinstance(status, str) else "UNKNOWN"
                if status == "RUNNING" and isinstance(active, dict) and active.get("status") == "ADMITTED":
                    mode = "ACTION_PENDING" if pending else "ACTIVE"
                if mode in {"UNKNOWN", "TERMINATED"}:
                    self.warnings.add("BROKER_TERMINATED" if mode == "TERMINATED" else "INVALID_BROKER_STATE")
                current = {"state": mode, "actions": _number(state.get("actions")), "pending_actions": pending,
                           "workers": len(workers), "worker_status_counts": dict(counts)}
        ordinal = _number(event.get("ordinal"))
        completed = (ordinal if event.get("stage") in {"CLEANED", "CELL_COMPLETE"} else max(0, ordinal - 1)) if ordinal is not None else 0
        result = {"planned": len(schedule), "completed": completed, "completed_is_lower_bound": True, "official_complete": official,
                  "resolved": resolved, "last_event": _event(event), "current": current}
        if accounting is not None:
            try:
                result.update(self.evaluation_accounting(root, manifest, accounting))
                if result.pop("retained_current", False):
                    result["current"] = {"state": "RETAINED_UNSCORED"}
            except (KeyError, TypeError, ValueError, OSError):
                self.warnings.add("INVALID_EVALUATION_ACCOUNTING")
                result.update(completed=None, undetermined=None, processed=None, processed_is_lower_bound=True)
                if accounting.get("schema") == QUOTA_CONTINUATION_SCHEMA:
                    result.update(grader_undetermined=None, native_infrastructure_undetermined=None)
        return result

    def evaluation_accounting(self, root, manifest, config):
        """Read public completion events and separately bound external hold receipts."""
        retained, _, manifest_sha = _read(root / "cohort.json", self.retries, with_digest=True)
        if retained != manifest or manifest.get("phase") != "EVALUATION":
            raise ProbeError("COHORT_MANIFEST_CHANGED")
        cohort_ref = {"path": str(root / "cohort.json"), "sha256": manifest_sha}
        schedule = manifest["schedule"]
        rows = {(row["task_id"], row["arm"]): row for row in schedule}
        if len(rows) != len(schedule) or any(_number(row.get("ordinal")) is None for row in schedule):
            raise ProbeError("INVALID_SCHEDULE")
        paths = sorted((p for p in (root / "events").glob("*.json") if re.fullmatch(r"[0-9]+\.json", p.name)), key=lambda p: int(p.stem))
        if len(paths) > 32000:
            raise ProbeError("JOURNAL_TOO_LARGE")
        boundary = _stamp(paths[-1]) if paths else None
        completed, graded, errors, stages = set(), set(), {}, {}
        last_ordinal = 0
        for path in paths:
            event, _, event_sha = _read(path, self.retries, with_digest=True)
            key = event.get("task_id"), event.get("arm")
            if key not in rows or event.get("ordinal") != rows[key]["ordinal"]:
                raise ProbeError("UNENROLLED_COHORT_EVENT")
            last_ordinal = max(last_ordinal, rows[key]["ordinal"])
            stages.setdefault(key, set()).add(event.get("stage"))
            if event.get("stage") == "CELL_COMPLETE":
                if key in completed:
                    raise ProbeError("DUPLICATE_COMPLETION_EVENT")
                completed.add(key)
            elif event.get("stage") == "GRADED":
                graded.add(key)
            elif event.get("stage") == "INFRA_ERROR":
                errors[key] = ({"path": str(path), "sha256": event_sha}, event)
        if paths and _stamp(paths[-1]) != boundary:
            raise ProbeError("JOURNAL_BOUNDARY_CHANGED")
        held, held_proofs = set(), {}
        quota = config.get("schema") == QUOTA_CONTINUATION_SCHEMA
        proof_roots = [Path(config["pipeline_root"])]
        if quota:
            previous = self.reference(config["supersedes_configuration_reference"])
            proof_roots.append(Path(previous["pipeline_root"]))
        proof_paths = sorted(path for parent in proof_roots for path in (parent / "unscored").glob("*.json"))
        if len(proof_paths) > 1120:
            raise ProbeError("TOO_MANY_HOLD_PROOFS")
        for path in proof_paths:
            proof, _ = _read(path, self.retries)
            proof_cohort = proof.get("cohort_reference")
            if not isinstance(proof_cohort, dict):
                raise ProbeError("INVALID_HOLD_COHORT_REFERENCE")
            if proof_cohort.get("path") != cohort_ref["path"]:
                continue
            key = proof.get("task_id"), proof.get("arm")
            experiment = manifest.get("experiment_reference")
            if (proof_cohort != cohort_ref or key not in rows
                    or proof.get("schema") != "skhynix/evaluation-grade-undetermined/1.0"
                    or proof.get("policy") != CONTINUATION_POLICY
                    or proof.get("amendment_reference") != config["evaluation_continuation_reference"]
                    or proof.get("experiment_reference") != experiment
                    or proof.get("phase") != "EVALUATION" or proof.get("official") is not False
                    or "resolved" not in proof or proof["resolved"] is not None
                    or proof.get("grader_status") != "undetermined"):
                raise ProbeError("INVALID_EVALUATION_HOLD_PROOF")
            identity = hashlib.sha256(json.dumps([experiment, *key], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            if (path.name != identity + ".json" or key in completed or key in graded
                    or key in held and (not quota or proof != held_proofs[key])):
                raise ProbeError("CONFLICTING_EVALUATION_HOLD_PROOF")
            if key in held:
                continue
            self.reference(experiment)
            error_reference, error = errors[key]
            if (proof["references"]["graded_error_event"] != error_reference
                    or error.get("details", {}).get("error_type") != "GraderInvocationFailure"):
                raise ProbeError("HOLD_ERROR_EVENT_MISMATCH")
            public = self.read(Path(rows[key]["cell_config"]).parent / "public-result.json", optional=True)
            if public.get("official") is True and public.get("grader_status") == "success" and type(public.get("resolved")) is bool:
                raise ProbeError("HOLD_OFFICIAL_RESULT_CONFLICT")
            held.add(key)
            held_proofs[key] = proof
        native_held = set()
        if quota:
            native_paths = sorted((Path(config["pipeline_root"]) / "native-quota-unscored").glob("*.json"))
            if len(native_paths) > 1120:
                raise ProbeError("TOO_MANY_HOLD_PROOFS")
            for path in native_paths:
                proof, _ = _read(path, self.retries)
                proof_cohort = proof.get("cohort_reference")
                if not isinstance(proof_cohort, dict):
                    raise ProbeError("INVALID_HOLD_COHORT_REFERENCE")
                if proof_cohort.get("path") != cohort_ref["path"]:
                    continue
                key = proof.get("task_id"), proof.get("arm")
                experiment = manifest.get("experiment_reference")
                required = {"schema": QUOTA_HOLD_SCHEMA, "policy": QUOTA_POLICY,
                            "amendment_reference": config["native_quota_continuation_reference"],
                            "experiment_reference": experiment, "cohort_reference": cohort_ref,
                            "phase": "EVALUATION", "official": False, "resolved": None,
                            "grader_status": "not_invoked", "native_status": "usage_limit",
                            "classification": "NATIVE_SERVICE_USAGE_LIMIT", "resources_retained": True,
                            "model_calls": 0, "official_grader_runs": 0, "training_memory_writes": 0,
                            "native_retries": False, "official_grader_retries": False}
                if key not in rows or any(name not in proof or type(proof[name]) is not type(value) or proof[name] != value
                                          for name, value in required.items()):
                    raise ProbeError("INVALID_NATIVE_QUOTA_HOLD_PROOF")
                identity = hashlib.sha256(json.dumps([experiment, *key], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                if (path.name != identity + ".json" or key in native_held or key in held
                        or key in completed or key in graded):
                    raise ProbeError("CONFLICTING_EVALUATION_HOLD_PROOF")
                error_reference, error = errors[key]
                if (proof["references"]["failed_event"] != error_reference
                        or error.get("details", {}).get("error_type") != "RuntimeError"
                        or error.get("details", {}).get("automatic_retry") is not False
                        or stages[key] & {"SOLVE_COMPLETE", "GRADE_STARTED", "GRADE_UNDETERMINED", "LEARNED", "CLEANED"}):
                    raise ProbeError("HOLD_ERROR_EVENT_MISMATCH")
                self.native_hold_metadata(proof, rows[key])
                native_held.add(key)
        all_held = held | native_held
        counts = {"grader_undetermined": len(held), "native_infrastructure_undetermined": len(native_held)} if quota else {}
        if any(key not in completed and key not in all_held and (quota or rows[key]["ordinal"] < last_ordinal) for key in errors):
            self.warnings.add("MISSING_EVALUATION_HOLD_PROOF")
            return {"completed": len(completed), "undetermined": None, "processed": None,
                    "processed_is_lower_bound": True, **{key: None for key in counts}}
        if quota:
            counts["retained_current"] = bool(paths and (event.get("task_id"), event.get("arm")) in all_held)
        return {"completed": len(completed), "undetermined": len(all_held),
                "processed": len(completed | all_held), "processed_is_lower_bound": True, **counts}

    def native_hold_metadata(self, proof, row):
        """Authenticate public native metadata; never open streams, prompts or grader payloads."""
        references = proof["references"]
        cell_path = Path(row["cell_config"])
        for name, filename in (("cell", "cell.json"), ("audit", "execution-audit.json"),
                               ("submission", "broker/submission.json"), ("native_failure", "native-execution-failure.json")):
            if Path(references[name]["path"]) != cell_path.parent / filename:
                raise ProbeError("NATIVE_HOLD_SOURCE_PATH_MISMATCH")
        cell = self.reference(references["cell"])
        audit = self.reference(references["audit"])
        submission = self.reference(references["submission"])
        failure = self.reference(references["native_failure"])
        experiment = self.reference(proof["experiment_reference"])
        if (cell.get("task_public", {}).get("task_id") != row["task_id"]
                or cell.get("arm") != row["arm"] or cell.get("phase") != "EVALUATION"
                or audit.get("passed") is not False or submission.get("agent_completed") is not False
                or submission.get("reason") != "NATIVE_WORKER_INFRASTRUCTURE_FAILURE"
                or any((cell_path.parent / name).exists() for name in ("public-result.json", "grader-pending.json", "grader-private.json"))):
            raise ProbeError("NATIVE_HOLD_EXECUTION_CONFLICT")
        workers = proof["native_workers"]
        if not isinstance(workers, list) or not 1 <= len(workers) <= 120:
            raise ProbeError("INVALID_NATIVE_WORKER_METADATA")
        root = Path(experiment["native_control_root"])
        if not root.is_absolute():
            raise ProbeError("INVALID_NATIVE_CONTROL_ROOT")
        numbers = set()
        for index, worker in enumerate(workers):
            if not isinstance(worker, dict):
                raise ProbeError("INVALID_NATIVE_WORKER_METADATA")
            number = _number(worker.get("number"))
            if number != index + 1 or number in numbers:
                raise ProbeError("INVALID_NATIVE_WORKER_METADATA")
            numbers.add(number)
            prefix = f"worker_{number:03d}"
            folder = root / "EVALUATION" / cell["target"]["instance_id"] / row["arm"] / f"worker-{number:03d}" / "output"
            completion_ref, events_ref = references[prefix + "_completion"], references[prefix + "_events"]
            self.reference_metadata(events_ref)
            if (Path(completion_ref["path"]) != folder / "completion.json"
                    or Path(events_ref["path"]) != folder / "events.jsonl"
                    or worker.get("completion_reference") != completion_ref
                    or worker.get("events_reference") != events_ref
                    or worker.get("completion_sha256") != completion_ref["sha256"]
                    or worker.get("events_sha256") != events_ref["sha256"]):
                raise ProbeError("NATIVE_WORKER_REFERENCE_MISMATCH")
            completion = self.reference(completion_ref)
            failed = index == len(workers) - 1
            if (completion.get("events_sha256") != events_ref["sha256"]
                    or completion.get("admitted") is not True or completion.get("timed_out") is not False
                    or any(completion.get(name) != [] for name in ("errors", "transport_errors", "outside_broker_tool_events"))
                    or not isinstance(worker.get("thread_id"), str) or not worker["thread_id"]
                    or completion.get("thread_id") != worker["thread_id"]
                    or type(completion.get("exit_code")) is not int or completion["exit_code"] != int(failed)
                    or worker.get("outcome") != ("NATIVE_SERVICE_USAGE_LIMIT" if failed else "COMPLETE")):
                raise ProbeError("NATIVE_COMPLETION_METADATA_MISMATCH")
            if failed and (failure.get("completion_sha256") != completion_ref["sha256"]
                           or failure.get("launcher_returncode") != 1):
                raise ProbeError("NATIVE_FAILURE_METADATA_MISMATCH")
        lines = proof["service_error_lines"]
        if (not isinstance(lines, list) or len(lines) != 2
                or [line.get("type") for line in lines if isinstance(line, dict)] != ["error", "turn.failed"]):
            raise ProbeError("INVALID_NATIVE_SERVICE_ERROR_METADATA")
        seen = set()
        for line in lines:
            if (not isinstance(line, dict) or _number(line.get("line")) in (None, 0)
                    or line["line"] in seen or not isinstance(line.get("sha256"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", line["sha256"]) is None):
                raise ProbeError("INVALID_NATIVE_SERVICE_ERROR_METADATA")
            seen.add(line["line"])
        if lines[1]["line"] != lines[0]["line"] + 1:
            raise ProbeError("INVALID_NATIVE_SERVICE_ERROR_METADATA")

    def learning(self, root):
        root = Path(root)
        state = self.read(root / "learning-state.json", optional=True)
        catalog = self.read(root / "catalog.json", optional=True)
        for name in ("learning-state.json", "catalog.json"):
            self.touch(root / name)
        counts = {key: len(value) for source in (state, catalog) for key, value in source.items()
                  if key in {"cells", "reflections", "ingestions", "captures", "knowledge", "edges", "skills"} and isinstance(value, (dict, list))}
        if (root / "authority.sqlite3").is_file():
            try:
                with closing(sqlite3.connect((root / "authority.sqlite3").as_uri() + "?mode=ro", uri=True, timeout=.1)) as db:
                    db.execute("BEGIN")
                    layers = {"L1_episodes": 0, "L2_nodes": 0, "L3_skills": 0}
                    layers.update({{"episode": "L1_episodes", "knowledge": "L2_nodes", "skill": "L3_skills"}[kind]: count
                                   for kind, count in db.execute("SELECT kind,COUNT(*) FROM memory_records WHERE revoked=0 GROUP BY kind") if kind in {"episode", "knowledge", "skill"}})
                    layers["L2_relations"] = db.execute("SELECT COUNT(*) FROM knowledge_relations").fetchone()[0]
                    counts.update(layers)
            except sqlite3.Error:
                self.warnings.add("DATABASE_BUSY_OR_INVALID")
        return counts


def _continuation_authority(probe, config):
    """Bind the single retained baseline to its immutable continuation authority."""
    if config.get("schema") == QUOTA_CONTINUATION_SCHEMA:
        amendment = probe.reference(config["native_quota_continuation_reference"])
        if (amendment.get("schema") != QUOTA_AMENDMENT_SCHEMA
                or amendment.get("policy") != QUOTA_POLICY
                or amendment.get("previous_configuration_reference") != config.get("supersedes_configuration_reference")):
            raise ProbeError("INVALID_NATIVE_QUOTA_CONTINUATION")
        previous = probe.reference(config["supersedes_configuration_reference"])
        if (previous.get("schema") != CONTINUATION_SCHEMA
                or previous.get("evaluation_continuation_reference") != config.get("evaluation_continuation_reference")
                or not Path(previous["pipeline_root"]).is_absolute()
                or Path(previous["pipeline_root"]) == Path(config["pipeline_root"])
                or previous.get("training_stages") != config.get("training_stages")):
            raise ProbeError("INVALID_NATIVE_QUOTA_PREDECESSOR")
        retained = _continuation_authority(probe, previous)
        if Path(config["pipeline_root"]) == Path(retained[2]["pipeline_root"]):
            raise ProbeError("INVALID_PREVIOUS_PIPELINE_ROOT")
        if (Path(amendment["baseline_cohort_reference"]["path"]) != retained[0] / "cohort.json"
                or probe.reference(amendment["baseline_cohort_reference"]) != retained[1]):
            raise ProbeError("RETAINED_BASELINE_REFERENCE_MISMATCH")
        tail_reference = amendment["baseline_event_tail_reference"]
        tail_path = Path(tail_reference["path"])
        if tail_path.parent != retained[0] / "events" or re.fullmatch(r"[0-9]+\.json", tail_path.name) is None:
            raise ProbeError("RETAINED_BASELINE_TAIL_PATH_MISMATCH")
        tail = probe.reference(tail_reference)
        if tail.get("stage") != "INFRA_ERROR" or tail.get("arm") != "BASELINE":
            raise ProbeError("INVALID_NATIVE_QUOTA_FAILURE_EVENT")
        return retained
    amendment = probe.reference(config["evaluation_continuation_reference"])
    if amendment.get("schema") != AMENDMENT_SCHEMA or amendment.get("policy") != CONTINUATION_POLICY:
        raise ProbeError("INVALID_EVALUATION_CONTINUATION")
    previous_reference = amendment["previous_configuration_reference"]
    if (config.get("previous_configuration_reference", previous_reference) != previous_reference
            or config.get("supersedes_configuration_reference", previous_reference) != previous_reference):
        raise ProbeError("PREVIOUS_CONFIGURATION_REFERENCE_MISMATCH")
    previous = probe.reference(previous_reference)
    previous_root = Path(previous["pipeline_root"])
    if not previous_root.is_absolute() or previous_root == Path(config["pipeline_root"]):
        raise ProbeError("INVALID_PREVIOUS_PIPELINE_ROOT")
    expected = previous_root / "development" / "baseline" / "run" / "cohort"
    if expected.resolve(strict=True) != previous_root.resolve(strict=True) / "development" / "baseline" / "run" / "cohort":
        raise ProbeError("RETAINED_BASELINE_PATH_MISMATCH")
    cohort_reference = amendment["baseline_cohort_reference"]
    if Path(cohort_reference["path"]) != expected / "cohort.json":
        raise ProbeError("RETAINED_BASELINE_REFERENCE_MISMATCH")
    manifest = probe.reference(cohort_reference)
    if manifest.get("phase") != "EVALUATION" or any(
            not isinstance(row, dict) or row.get("arm") != "BASELINE"
            for row in manifest.get("schedule", [])):
        raise ProbeError("INVALID_RETAINED_BASELINE_MANIFEST")
    tail_reference = amendment["baseline_event_tail_reference"]
    tail_path = Path(tail_reference["path"])
    if tail_path.parent != expected / "events" or re.fullmatch(r"[0-9]+\.json", tail_path.name) is None:
        raise ProbeError("RETAINED_BASELINE_TAIL_PATH_MISMATCH")
    probe.reference(tail_reference)
    return expected, manifest, previous


def inspect_health(config_path, *, now=None, stale_seconds=3600, retries=3):
    now = time.time() if now is None else float(now)
    if not Path(config_path).is_absolute() or not math.isfinite(now) or now < 0 or not math.isfinite(stale_seconds) or stale_seconds <= 0 or not 1 <= retries <= 5:
        raise ValueError("Absolute config path and bounded positive probe limits required")
    probe = _Probe(retries)
    config = probe.read(config_path)
    stages, evaluation = [], None
    try:
        root = Path(config["pipeline_root"])
        if not root.is_absolute():
            raise ValueError()
        event = probe.tail(root)
        continuation = None
        if config.get("schema") in {CONTINUATION_SCHEMA, QUOTA_CONTINUATION_SCHEMA}:
            try:
                continuation = _continuation_authority(probe, config)
            except (KeyError, TypeError, ValueError, OSError):
                probe.warnings.add("INVALID_EVALUATION_CONTINUATION")
        adoption = probe.read(config["source_adoption_reference"]["path"])
        if [stage.get("size") for stage in config["training_stages"]] != [24, 120, 240]:
            raise ValueError()
        for stage in config["training_stages"]:
            if stage.get("size") not in (24, 120, 240):
                raise ValueError()
            execution = probe.read(stage["execution_reference"]["path"])
            learning_root = stage.get("learning_root", root / ("learning-" + str(stage["size"])))
            if "learning_root" not in stage and continuation is not None:
                previous = continuation[2]
                matching = [old for old in previous.get("training_stages", [])
                            if isinstance(old, dict) and old.get("size") == stage["size"]
                            and old.get("execution_reference") == stage.get("execution_reference")]
                if len(matching) == 1 and matching[0] == stage:
                    learning_root = Path(previous["pipeline_root"]) / ("learning-" + str(stage["size"]))
                else:
                    probe.warnings.add("INVALID_EVALUATION_CONTINUATION")
            stages.append({"size": stage["size"], "cohort": probe.cohort(Path(execution["run_root"]) / "cohort"),
                           "learning": probe.learning(learning_root)})
        details = event.get("details", {})
        current_root = details.get("cohort_root") if isinstance(details, dict) else None
        if isinstance(current_root, str):
            current = Path(current_root)
            if config.get("schema") == QUOTA_CONTINUATION_SCHEMA and continuation is None:
                probe.warnings.add("INVALID_EVALUATION_CONTINUATION")
            elif len(current.parents) >= 4 and current.name == "cohort" and current.parent.name == "run" and current.parents[2].name in {"development", "final"} and current.parents[3] == root:
                evaluation = probe.cohort(current, accounting=config if continuation is not None else None)
            elif config.get("schema") in {CONTINUATION_SCHEMA, QUOTA_CONTINUATION_SCHEMA}:
                if continuation is not None and current == continuation[0]:
                    evaluation = probe.cohort(current, manifest=continuation[1], accounting=config)
                else:
                    probe.warnings.add("INVALID_EVALUATION_CONTINUATION")
        disk = round(shutil.disk_usage(root if root.exists() else root.parent).free / 1024 ** 3, 2)
    except (KeyError, TypeError, ValueError, OSError):
        probe.warnings.add("INVALID_OR_MISSING_CONFIGURATION")
        event, adoption, disk = {}, {}, None
    latest = max(probe.activity, default=0.0)
    if not latest:
        try:
            latest = _stamp(Path(config_path))[3] / 1e9
        except OSError:
            pass
    age = max(0.0, now - latest) if latest else None
    blocked = event.get("stage") == "PIPELINE_BLOCKED" or any(
        c["last_event"]["stage"] in {"INFRA_ERROR", "DISK_BLOCK"} and c["current"]["state"] != "RETAINED_UNSCORED"
        for c in [s["cohort"] for s in stages] + ([evaluation] if evaluation else []))
    terminal = {"PIPELINE_COMPLETE": "COMPLETE", "PIPELINE_COMPLETE_WITH_UNDETERMINED": "COMPLETE_WITH_UNDETERMINED", "NO_READY_MEMORY_BANK": "NOT_READY"}
    status = terminal.get(event.get("stage")) if isinstance(event.get("stage"), str) else None
    if status is None:
        status = "BLOCKED" if blocked else "WARNING_INVALID_METADATA" if probe.warnings else "WARNING_STALE" if age is not None and age >= stale_seconds else "PROGRESSING" if probe.activity else "IDLE_PREPARATION"
    return {"schema": SCHEMA, "status": status, "observed_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "latest_activity_at": latest or None, "activity_age_seconds": round(age, 1) if age is not None else None,
            "stale_after_seconds": stale_seconds, "process_liveness": "NOT_OBSERVED", "pipeline": _event(event),
            "adopted_sources": _number(adoption.get("source_count")), "adopted_official_complete": _number(adoption.get("official_complete")),
            "stages": stages, "evaluation_cohort": evaluation, "disk_free_gib": disk, "warnings": sorted(probe.warnings)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--stale-seconds", type=float, default=3600)
    args = parser.parse_args()
    print(json.dumps(inspect_health(args.config, stale_seconds=args.stale_seconds), sort_keys=True))


if __name__ == "__main__":
    main()
