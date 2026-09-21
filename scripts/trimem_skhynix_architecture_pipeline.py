"""Durable training -> public native reflection -> frozen bank -> paired evaluation.

This is a trusted controller. All executable helpers and inputs are frozen file
references; native workers cannot supply paths or choose callbacks. A failed or
interrupted publisher is never silently relaunched. Cohort resumption delegates
only to its existing audited, task-wide resume contract.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import importlib
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import subprocess
import sys
import time
from typing import Protocol

from enterprise_memory.trimem.accounting import canonical_bytes, strict_json_loads
from trimem_skhynix_architecture_broker import locked
import hashlib

SCHEMA = "skhynix/architecture-pipeline/1.0"
HELPERS = ("cohort", "learning", "publisher", "progress", "quarantine", "cleanup")
SELECTION = "PER_TASK_EARLIEST_PUBLIC_GREEN_ELSE_EARLIEST_COMPLETED_OR_TERMINAL_CHECKPOINT"
PATH_FIELDS = ("pipeline_root", "reflection_native_root", "evaluation_run_root", "evaluation_native_root", "progress_root")
RUNTIME_IMPORTS = ("trimem_skhynix_architecture_run", "trimem_skhynix_architecture_environment",
    "trimem_skhynix_environment", "trimem_benchmark_run", "trimem_official_grader",
    "trimem_official_harness_loader_preflight")


class PipelineError(RuntimeError):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return strict_json_loads(Path(path).read_bytes())


def absolute(value):
    path = Path(value)
    if not path.is_absolute() or path.resolve() != path or ".." in path.parts:
        raise PipelineError("pipeline paths must be explicit canonical absolute paths")
    return path


def ref(path):
    path = absolute(path)
    return {"path": str(path), "sha256": digest(path.read_bytes())}


def check(value, *, decode=True):
    if not isinstance(value, dict) or set(value) != {"path", "sha256"} or ref(value["path"]) != value:
        raise PipelineError("immutable pipeline reference changed")
    return read(value["path"]) if decode else Path(value["path"])


def retain(path, value):
    path = absolute(path)
    raw = canonical_bytes(value) + b"\n"
    if path.exists():
        if path.read_bytes() != raw:
            raise PipelineError("refusing to replace immutable pipeline evidence")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return ref(path)


def windows_path(path):
    path = absolute(path)
    try:
        relative = path.relative_to("/mnt/c")
    except ValueError as exc:
        raise PipelineError("native publisher inputs must be under the explicit C-drive mount") from exc
    return str(PureWindowsPath("C:/", *relative.parts))


def linux_path(value):
    path = PureWindowsPath(value)
    if path.drive.lower() != "c:" or not path.is_absolute() or ".." in path.parts:
        raise PipelineError("native evidence must name an absolute C-drive path")
    return absolute(Path("/mnt/c", *path.parts[1:]))


def create_pipeline_config(path, definition):
    required = {"training_experiment_reference", "training_cohort_reference", "learning_enrollment_reference",
                "helper_references", *PATH_FIELDS}
    optional = {"reflection_max_bytes", "adopted_reflections", "supersedes", "execution_transition_reference"}
    if not required <= set(definition) or set(definition) - required - optional:
        raise PipelineError("pipeline definition fields differ")
    value = {**definition, "schema": SCHEMA, "pipeline_source_reference": ref(Path(__file__).resolve()),
             "reflection_max_bytes": definition.get("reflection_max_bytes", 190000),
             "adopted_reflections": definition.get("adopted_reflections", []),
             "selection_policy": SELECTION, "outcome_retries": False}
    _validate_config(value)
    result = retain(Path(path).resolve(), value)
    checksum = Path(path).resolve().with_suffix(".sha256")
    raw = (digest(canonical_bytes(value)) + "\n").encode()
    if checksum.exists() and checksum.read_bytes() != raw:
        raise PipelineError("pipeline configuration checksum already differs")
    if not checksum.exists():
        with checksum.open("xb") as stream:
            stream.write(raw)
    return result


def _validate_config(value):
    if (value.get("schema") != SCHEMA or value.get("selection_policy") != SELECTION
            or value.get("outcome_retries") is not False
            or type(value.get("reflection_max_bytes")) is not int
            or not 1024 <= value["reflection_max_bytes"] <= 190000
            or set(value.get("helper_references", {})) != set(HELPERS)):
        raise PipelineError("unsupported pipeline configuration or reflection budget")
    for key in PATH_FIELDS:
        absolute(value[key])
    windows_path(value["reflection_native_root"])
    windows_path(value["evaluation_native_root"])
    for key in ("training_experiment_reference", "training_cohort_reference", "learning_enrollment_reference"):
        check(value[key])
    check(value["pipeline_source_reference"], decode=False)
    if digest(Path(__file__).read_bytes()) != value["pipeline_source_reference"]["sha256"]:
        raise PipelineError("executing pipeline source differs from the frozen implementation")
    for reference in value["helper_references"].values():
        check(reference, decode=False)
    training = check(value["training_experiment_reference"])
    cohort = check(value["training_cohort_reference"])
    enrollment = check(value["learning_enrollment_reference"])
    transition = execution_transition(value)
    cohort_experiment = transition["previous_experiment_reference"] if transition else value["training_experiment_reference"]
    cohort_learning = transition["previous_learning_enrollment_reference"] if transition else value["learning_enrollment_reference"]
    learning_executions = ([transition["previous_experiment_reference"], value["training_experiment_reference"]]
                           if transition else [value["training_experiment_reference"]])
    if (training.get("phase") != "TRAINING_RUNTIME" or training.get("model") != "gpt-6-astra"
            or training.get("reasoning_effort") not in {"ultra", "high"} or training.get("authentication") != "CHATGPT"
            or cohort.get("phase") != "TRAINING" or cohort.get("scope") != "FULL_FIXED_COHORT"
            or cohort.get("selected_task_count") != 24 or len(cohort.get("schedule", [])) != 24
            or cohort.get("experiment_reference") != cohort_experiment
            or cohort.get("learning_root") != str(Path(cohort_learning["path"]).parent)
            or enrollment.get("learning_version") != 2
            or enrollment.get("execution_references") != learning_executions
            or enrollment.get("implementation_sha256", {}).get("learning") != value["helper_references"]["learning"]["sha256"]):
        raise PipelineError("pipeline must bind the exact full training cohort and its v2 learning authority")
    if (Path(value["evaluation_run_root"]) == Path(training["run_root"])
            or Path(value["evaluation_native_root"]) == Path(training["native_control_root"])
            or Path(value["reflection_native_root"]) in (Path(training["native_control_root"]), Path(value["evaluation_native_root"]))):
        raise PipelineError("training, reflection and evaluation roots must be distinct")
    adoptions = value["adopted_reflections"]
    if not isinstance(adoptions, list) or len(adoptions) > 12 or len({item["repository"] for item in adoptions}) != len(adoptions):
        raise PipelineError("publisher adoptions must be unique predeclared repository jobs")
    for item in adoptions:
        if set(item) != {"repository", "configuration_reference", "completion_reference", "launcher_reference"}:
            raise PipelineError("publisher adoption requires exact native and outer launcher receipts")
        for key in ("configuration_reference", "completion_reference", "launcher_reference"):
            check(item[key])
    if "supersedes" in value:
        validate_predecessor(value)


def execution_transition(config):
    """Bind a declared forward transition; the frozen cohort helper audits its event boundary."""
    reference = config.get("execution_transition_reference")
    if reference is None:
        return None
    value = check(reference)
    if (value.get("schema") != "skhynix/architecture-reasoning-effort-transition/1.0"
            or value.get("operation") != "ADOPT_FORWARD_REASONING_EFFORT"
            or value.get("cohort_reference") != config["training_cohort_reference"]
            or value.get("experiment_reference") != config["training_experiment_reference"]
            or value.get("learning_enrollment_reference") != config["learning_enrollment_reference"]
            or value.get("controller_source_reference") != config["helper_references"]["cohort"]
            or value.get("outcome_retries") is not False or value.get("model_calls") != 0
            or value.get("official_grader_runs") != 0):
        raise PipelineError("forward effort transition does not bind the frozen pipeline authorities")
    root = Path(config["training_cohort_reference"]["path"]).parent
    if Path(reference["path"]) != root / "reasoning-effort-transition.json":
        raise PipelineError("forward effort transition escaped its original cohort")
    old, new = check(value["previous_experiment_reference"]), check(value["experiment_reference"])
    if old.get("reasoning_effort") != "ultra" or new.get("reasoning_effort") != "high":
        raise PipelineError("forward effort transition must preserve ultra history and use high subsequently")
    mutable = {"reasoning_effort", "reasoning_source", "prelaunch_revision"}
    if ({key: child for key, child in old.items() if key not in mutable}
            != {key: child for key, child in new.items() if key not in mutable}):
        raise PipelineError("forward effort transition changed the runtime, population or task budgets")
    old_learning, new_learning = check(value["previous_learning_enrollment_reference"]), check(value["learning_enrollment_reference"])
    if (old_learning.get("execution_references") != [value["previous_experiment_reference"]]
            or new_learning.get("execution_references") != [value["previous_experiment_reference"], value["experiment_reference"]]
            or {key: child for key, child in old_learning.items() if key != "execution_references"}
            != {key: child for key, child in new_learning.items() if key != "execution_references"}):
        raise PipelineError("forward learning enrollment must preserve the original authority and add the exact high execution")
    return value


def read_event_chain(root):
    rows, previous = [], "0" * 64
    with locked(Path(root) / "journal.lock"):
        for path in sorted((Path(root) / "events").glob("*.json")):
            row = read(path)
            body = {key: value for key, value in row.items() if key != "sha256"}
            if (path.name != f"{len(rows) + 1:08d}.json" or row["sequence"] != len(rows) + 1
                    or row["previous_sha256"] != previous or row["sha256"] != digest(canonical_bytes(body))):
                raise PipelineError("pipeline event chain changed")
            rows.append(row)
            previous = row["sha256"]
    return rows


def validate_predecessor(config):
    binding = config["supersedes"]
    if not isinstance(binding, dict) or set(binding) != {"configuration_reference", "event_tail_reference"}:
        raise PipelineError("supersession requires the exact predecessor configuration and final event")
    old = check(binding["configuration_reference"])
    root = absolute(old["pipeline_root"])
    if root == absolute(config["pipeline_root"]):
        raise PipelineError("supersession requires a new pipeline root")
    if (read(root / "pipeline-binding.json") != {"schema": SCHEMA, "configuration_reference": binding["configuration_reference"]}
            or digest(canonical_bytes(old)) != Path(binding["configuration_reference"]["path"]).with_suffix(".sha256").read_text().strip()):
        raise PipelineError("predecessor root or configuration binding differs")
    transition = execution_transition(config)
    for key in ("training_cohort_reference", "selection_policy", "reflection_max_bytes", "outcome_retries", "adopted_reflections"):
        if old.get(key) != config.get(key):
            raise PipelineError("supersession cannot change training enrollment or experimental policy")
    for key, previous_key in (("training_experiment_reference", "previous_experiment_reference"),
                              ("learning_enrollment_reference", "previous_learning_enrollment_reference")):
        expected = transition[previous_key] if transition else config.get(key)
        if old.get(key) != expected:
            raise PipelineError("supersession cannot change training enrollment outside the bound forward transition")
    check(old["pipeline_source_reference"], decode=False)
    events = read_event_chain(root)
    allowed = {"COHORT_ADVANCE_STARTED", "COHORT_PROGRESS", "PUBLIC_PROGRESS", "PIPELINE_BLOCKED", "TRAINING_COMPLETE", "CONTROLLER_SUPERSESSION"}
    if not events or any(event["stage"] not in allowed for event in events):
        raise PipelineError("supersession is only supported before any reflection or evaluation stage")
    for event in events:
        if event["stage"] == "CONTROLLER_SUPERSESSION":
            if ("supersedes" not in old or event["details"] != {"predecessor": old["supersedes"],
                    "training_cohort_reference": old["training_cohort_reference"],
                    "original_evidence_preserved": True, "native_outcome_retries": False}):
                raise PipelineError("predecessor supersession event has a different authority binding")
            validate_predecessor(old)
    tail = root / "events" / f"{len(events):08d}.json"
    if ref(tail) != binding["event_tail_reference"]:
        raise PipelineError("predecessor event tail changed after supersession was declared")
    return root


@contextmanager
def predecessor_guard(config):
    if "supersedes" not in config:
        yield
        return
    root = validate_predecessor(config)
    with (root / "run.lock").open("a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0, 2)
                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise PipelineError("predecessor controller is still running") from exc
        try:
            validate_predecessor(config)
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def select_reflection_jobs(targets, captures):
    """Public checkpoint policy; official outcomes are neither an input nor a selector."""
    training = sorted((target for target in targets if target["role"] == "TRAINING"), key=lambda row: row["order_index"])
    if len(training) != 24 or len({target["target_id"] for target in training}) != 24:
        raise PipelineError("reflection planning requires every one of the 24 frozen source tasks")
    by_repo = {}
    for target in training:
        rows = [row for row in captures if row["task_id"] == target["target_id"]]
        if any(row["repository"] != target["repository"] for row in rows):
            raise PipelineError("checkpoint repository differs from its public task")
        green = [row for row in rows if row["kind"] == "PUBLIC_TEST_OBSERVATION" and row["public_test_outcome"] == "GREEN"]
        fallback = [row for row in rows if row["kind"] in {"COMPLETED_SUBGOAL", "TERMINAL_ACTIVE"}]
        eligible = green or fallback
        chosen = min(eligible, key=lambda row: (row["cutoff_step"], row["kind"], row["node_id"], row["capture_id"])) if eligible else None
        by_repo.setdefault(target["repository"], []).append({"task_id": target["target_id"],
            "capture_count_retained": len(rows), "selected": chosen,
            "selection": "EARLIEST_GREEN" if green else "EARLIEST_COMPLETED_OR_TERMINAL" if fallback else "NO_PUBLIC_CAPTURE"})
    if len(by_repo) != 12 or any(len(rows) != 2 for rows in by_repo.values()):
        raise PipelineError("reflection requires the fixed 12 repositories with two source tasks each")
    if not {row["task_id"] for row in captures} <= {row["target_id"] for row in training}:
        raise PipelineError("reflection inventory contains a task outside training")
    return [{"ordinal": index, "repository": repository, "sources": sources,
        "capture_ids": sorted(row["selected"]["capture_id"] for row in sources if row["selected"]),
        "status": "READY" if all(row["selected"] for row in sources) else "INSUFFICIENT_PUBLIC_SOURCES"}
        for index, (repository, sources) in enumerate(sorted(by_repo.items()), 1)]


def validate_native_publication(configuration_reference, completion_reference, launcher_reference, *,
                                reflection_reference, publisher_reference, publisher_module, mapper=linux_path):
    config, completion, outer = (check(reference) for reference in (configuration_reference, completion_reference, launcher_reference))
    output = mapper(config["worker_output"])
    if (Path(completion_reference["path"]) != output / "completion.json"
            or mapper(config["reflection_reference"]["path"]) != Path(reflection_reference["path"])
            or config["reflection_reference"]["sha256"] != reflection_reference["sha256"]):
        raise PipelineError("native publisher evidence belongs to a different public export")
    public = check(reflection_reference)
    if public.get("schema") != "skhynix/native-architecture-public-reflection/2.0":
        raise PipelineError("publisher must receive the frozen v2 public projection")
    if (outer.get("schema") != "skhynix/pipeline-native-launch/1.0" or outer.get("status") != "COMPLETE"
            or outer.get("returncode") != 0 or outer.get("configuration_reference") != configuration_reference
            or outer.get("publisher_reference") != publisher_reference):
        raise PipelineError("native publisher outer launcher did not complete successfully")
    for reference in outer["output_references"].values():
        check(reference, decode=False)
    if (output / "failure.json").exists():
        raise PipelineError("native publisher has a retained failure receipt")
    raw = (output / "events.jsonl").read_bytes()
    thread, response = publisher_module.validate_events([strict_json_loads(line) for line in raw.splitlines()])
    launch_ref = {"path": str(mapper(completion["launch_reference"]["path"])), "sha256": completion["launch_reference"]["sha256"]}
    proposal_ref = {"path": str(mapper(completion["proposal_reference"]["path"])), "sha256": completion["proposal_reference"]["sha256"]}
    if Path(launch_ref["path"]) != output / "launch.json" or Path(proposal_ref["path"]) != output / "proposals.json":
        raise PipelineError("publisher output references escaped their bound output directory")
    launch, proposal = check(launch_ref), check(proposal_ref)
    prompt = publisher_module.PREFIX.encode() + canonical_bytes({"reflection_sha256": reflection_reference["sha256"], "public_training_export": public})
    command = publisher_module.publisher_command(config, PureWindowsPath(config["worker_output"]))
    if (len(prompt) > publisher_module.CAP or (output / "prompt.txt").read_bytes() != prompt
            or launch.get("schema") != "skhynix/native-reflection-launch/1.0"
            or launch.get("configuration_sha256") != configuration_reference["sha256"]
            or launch.get("implementation_sha256") != publisher_reference["sha256"]
            or launch.get("reflection_reference") != config["reflection_reference"]
            or launch.get("reflection_sha256") != reflection_reference["sha256"]
            or launch.get("prompt_sha256") != digest(prompt) or launch.get("prompt_bytes") != len(prompt)
            or launch.get("command_sha256") != digest(canonical_bytes(command))
            or launch.get("fresh_session") is not True or launch.get("requested_model") != "gpt-6-astra"
            or config.get("reasoning_effort") not in {"ultra", "high"}
            or launch.get("reasoning_effort") != config["reasoning_effort"] or launch.get("separate_model_api_client_calls") != 0
            or completion.get("schema") != "skhynix/native-reflection-completion/1.0"
            or completion.get("thread_id") != thread or completion.get("events_sha256") != digest(raw)
            or completion.get("configuration_sha256") != configuration_reference["sha256"]
            or completion.get("reflection_sha256") != reflection_reference["sha256"]
            or completion.get("response_text_sha256") != digest(response.encode())
            or completion.get("proposal_sha256") != proposal_ref["sha256"]
            or completion.get("separate_model_api_client_calls") != 0
            or completion.get("validation_required") is not True or completion.get("gate_b_promotions") != 0
            or strict_json_loads(response) != proposal or set(proposal) != {"schema", "reflection_sha256", "proposals"}
            or proposal["schema"] != "skhynix/native-architecture-reflection-proposals/1.0"
            or proposal["reflection_sha256"] != reflection_reference["sha256"]
            or not isinstance(proposal["proposals"], list) or completion.get("proposal_count") != len(proposal["proposals"])):
        raise PipelineError("native proposal is not bound to the exact fresh response, prompt, source and launch")
    return {"thread_id": thread, "configuration_reference": configuration_reference,
        "completion_reference": completion_reference, "launcher_reference": launcher_reference,
        "launch_reference": launch_ref, "proposal_reference": proposal_ref, "reflection_reference": reflection_reference}


class PipelineOperations(Protocol):
    def cohort_status(self, root): ...
    def run_cohort(self, root): ...
    def inventory(self, root): ...
    def export_reflection(self, root, path, capture_ids, max_bytes): ...
    def launch_publisher(self, configuration_reference, launcher_path): ...
    def validate_publisher(self, configuration_reference, completion_reference, launcher_reference, reflection_reference): ...
    def ingest(self, root, proposal_reference, reflection_reference): ...
    def freeze(self, root, path): ...
    def validate_bank(self, bank_reference): ...
    def prepare_evaluation(self, experiment_reference, bank_reference, cohort_root, quarantine_root, policy_path): ...
    def progress(self, configurations, output): ...


def import_frozen_helper(name, reference, runtime_paths):
    """A helper's import-time path edits must not redirect later runtime imports."""
    path = check(reference, decode=False)
    module_name = "trimem_skhynix_architecture_" + name
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
        raise
    finally:
        sys.path[:] = runtime_paths
    return module


def validate_runtime_imports(training):
    """Path identity matters: the official loader hashes invocation entrypoint paths."""
    root = absolute(training["source_root"])
    excluded = {"trimem_skhynix_architecture_" + name for name in (*HELPERS, "pipeline")}
    references = {}
    for name, module in tuple(sys.modules.items()):
        if name in excluded or not (name.startswith("trimem_") or name == "enterprise_memory" or name.startswith("enterprise_memory.")):
            continue
        filename = getattr(module, "__file__", None)
        if filename is None:
            continue
        path = Path(filename).resolve()
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise PipelineError("runtime module escaped the frozen source root: " + name) from exc
        if training["source_sha256"].get(relative) != digest(path.read_bytes()):
            raise PipelineError("runtime module differs from the frozen source bytes: " + name)
        references[name] = ref(path)
    for name in RUNTIME_IMPORTS:
        if name not in references:
            raise PipelineError("required lazy runtime module was not bound: " + name)
    expected = root / "scripts/trimem_swe_bench_entrypoint.py"
    for name in ("trimem_benchmark_run", "trimem_official_grader"):
        if Path(sys.modules[name].SWE_ENTRYPOINT).resolve() != expected:
            raise PipelineError("official grader entrypoint differs from the frozen loader identity")
    return references


class FrozenOperations:
    def __init__(self, config):
        self.config, self.modules, self.cohorts = config, {}, {}
        training = check(config["training_experiment_reference"])
        source = absolute(training["source_root"])
        prefix = [str(source / "src"), str(source / "scripts")]
        runtime_paths = prefix + [item for item in sys.path if item not in prefix]
        sys.path[:] = runtime_paths
        try:
            for name in RUNTIME_IMPORTS:
                importlib.import_module(name)
        finally:
            sys.path[:] = runtime_paths
        validate_runtime_imports(training)
        for name in HELPERS:
            self.modules[name] = import_frozen_helper(name, config["helper_references"][name], runtime_paths)
        self.runtime_import_references = validate_runtime_imports(training)
        self.training = self.modules["cohort"].execution.load_experiment(config["training_experiment_reference"]["path"])
        if config.get("execution_transition_reference") is not None:
            actual = self.modules["cohort"].validate_reasoning_effort_transition(
                Path(config["training_cohort_reference"]["path"]).parent, config["execution_transition_reference"],
                operations=self.modules["cohort"].execution)
            if actual != execution_transition(config):
                raise PipelineError("cohort transition audit differs from the pipeline binding")

    def _cohort(self, root):
        key = str(absolute(root))
        if key not in self.cohorts:
            self.cohorts[key] = self.modules["cohort"]._open(Path(key))
        return self.cohorts[key]

    def cohort_status(self, root):
        return self._cohort(root).status()

    def run_cohort(self, root):
        return self._cohort(root).run(cell_limit=1)

    def inventory(self, root):
        learning = self.modules["learning"]
        with learning._session(root, mutable=False) as (root, enrollment, registry, configurations):
            available = learning._available_captures(root, registry)
            return [{"capture_id": identity, "capture_reference": reference,
                "task_id": capture["task"]["task_id"], "repository": capture["task"]["repository"],
                "node_id": item["checkpoint"]["node_id"], "cutoff_step": item["checkpoint"]["cutoff_step"],
                "kind": item["checkpoint"]["kind"], "public_test_outcome": item["checkpoint"]["public_test_outcome"]}
                for identity, (reference, capture, item, cell_ref) in sorted(available.items())]

    def export_reflection(self, root, path, capture_ids, max_bytes):
        return self.modules["learning"].export_reflection(root, path, capture_ids=capture_ids, max_bytes=max_bytes)

    def launch_publisher(self, configuration_reference, launcher_path):
        publisher_ref = self.config["helper_references"]["publisher"]
        argv = [self.training["wsl_windows_python"], windows_path(publisher_ref["path"]),
                "--config", windows_path(configuration_reference["path"])]
        check(publisher_ref, decode=False)
        log_root = Path(launcher_path).parent / "interop"
        log_root.mkdir(exist_ok=False)
        env = dict(os.environ)
        for key in ("OPENAI_API_KEY", "CODEX_API_KEY"):
            env.pop(key, None)
        receipt = {"schema": "skhynix/pipeline-native-launch/1.0", "configuration_reference": configuration_reference,
            "publisher_reference": publisher_ref, "argv_sha256": digest(canonical_bytes(argv)),
            "status": "FAILED", "returncode": None, "output_references": {}}
        try:
            with (log_root / "stdout.log").open("xb") as out, (log_root / "stderr.log").open("xb") as err:
                result = subprocess.run(argv, cwd=self.config["pipeline_root"], env=env, stdout=out, stderr=err,
                                        timeout=370, check=False)
            receipt.update(status="COMPLETE" if result.returncode == 0 else "FAILED", returncode=result.returncode)
        except Exception as exc:
            receipt["error_type"] = type(exc).__name__
        finally:
            receipt["output_references"] = {path.name: ref(path) for path in log_root.glob("*.log")}
            retain(launcher_path, receipt)
        if receipt["status"] != "COMPLETE":
            raise PipelineError("native reflection launcher failed; its output is retained without retry")

    def validate_publisher(self, configuration_reference, completion_reference, launcher_reference, reflection_reference):
        return validate_native_publication(configuration_reference, completion_reference, launcher_reference,
            reflection_reference=reflection_reference, publisher_reference=self.config["helper_references"]["publisher"],
            publisher_module=self.modules["publisher"])

    def ingest(self, root, proposal_reference, reflection_reference):
        return self.modules["learning"].ingest_proposals(root, proposal_reference, reflection_reference=reflection_reference)

    def freeze(self, root, path):
        return self.modules["learning"].freeze_published_bank(root, path)

    def validate_bank(self, bank_reference):
        dataset = check(self.training["dataset_manifest"])
        return self.modules["cohort"].validate_evaluation_bank(bank_reference, dataset, self.training)

    def prepare_evaluation(self, experiment_reference, bank_reference, cohort_root, quarantine_root, policy_path):
        config = check(experiment_reference)
        Path(config["run_root"]).mkdir(parents=True, exist_ok=True)
        quarantine_ref = self.modules["quarantine"].initialize_quarantine(quarantine_root,
            execution_reference=experiment_reference, bank_reference=bank_reference)
        policy_ref = self.modules["cleanup"].create_cleanup_policy(policy_path, experiment_reference=experiment_reference)
        if Path(cohort_root).exists():
            runner = self._cohort(cohort_root)
            if (runner.manifest["phase"] != "EVALUATION" or runner.manifest["scope"] != "FULL_FIXED_COHORT"
                    or runner.manifest["bank_reference"] != bank_reference or runner.manifest["experiment_reference"] != experiment_reference
                    or runner.manifest["quarantine_root"] != str(quarantine_root) or runner.manifest["cleanup_policy_reference"] != policy_ref):
                raise PipelineError("existing evaluation cohort differs from the frozen pipeline")
        else:
            runner = self.modules["cohort"].CohortRunner.create(cohort_root,
                experiment_path=experiment_reference["path"], phase="EVALUATION", bank_reference=bank_reference,
                quarantine_root=quarantine_root, cleanup_policy_reference=policy_ref,
                quarantine_hook=self.modules["quarantine"].make_quarantine_hook(quarantine_root))
        if len(runner.schedule) != 1000:
            raise PipelineError("evaluation enrollment must retain every paired target")
        self.cohorts[str(absolute(cohort_root))] = runner
        return {"cohort_reference": ref(Path(cohort_root) / "cohort.json"),
                "quarantine_reference": quarantine_ref, "cleanup_policy_reference": policy_ref}

    def progress(self, configurations, output):
        result = self.modules["progress"].export_progress([item["path"] for item in configurations], output)
        reference = result.get("snapshot_reference")
        if not isinstance(reference, dict):
            raise PipelineError("public progress did not return its immutable snapshot reference")
        path = check(reference, decode=False)
        if path.parent != absolute(output) / "progress-history" or path.suffix != ".json":
            raise PipelineError("public progress snapshot escaped the bound history directory")
        if digest((Path(output) / "progress.json").read_bytes()) != reference["sha256"]:
            raise PipelineError("public progress snapshot differs from the current export")
        return reference


class Pipeline:
    def __init__(self, config_path, *, operations: PipelineOperations | None = None, clock=time.time):
        self.path = absolute(config_path)
        self.reference = ref(self.path)
        self.config = read(self.path)
        if digest(canonical_bytes(self.config)) != self.path.with_suffix(".sha256").read_text().strip():
            raise PipelineError("pipeline configuration checksum differs")
        _validate_config(self.config)
        self.root, self.clock = Path(self.config["pipeline_root"]), clock
        self.root.mkdir(parents=True, exist_ok=True)
        binding_path = self.root / "pipeline-binding.json"
        if not binding_path.exists() and any((self.root / "events").glob("*.json")):
            raise PipelineError("existing pipeline journal has no matching immutable root binding")
        retain(binding_path, {"schema": SCHEMA, "configuration_reference": self.reference})
        (self.root / "events").mkdir(exist_ok=True)
        self.operations = operations or FrozenOperations(self.config)
        self.training = check(self.config["training_experiment_reference"])
        self.training_cohort = Path(self.config["training_cohort_reference"]["path"]).parent
        self.learning_root = Path(self.config["learning_enrollment_reference"]["path"]).parent

    def events(self):
        return read_event_chain(self.root)

    def record(self, stage, details, *, job=None):
        events = self.events()
        value = {"sequence": len(events) + 1, "previous_sha256": events[-1]["sha256"] if events else "0" * 64,
                 "stage": stage, "job": job, "details": details, "at": self.clock()}
        value["sha256"] = digest(canonical_bytes(value))
        with locked(self.root / "journal.lock"):
            retain(self.root / "events" / f"{value['sequence']:08d}.json", value)
        return value

    def latest(self, stage, job=None):
        return next((event for event in reversed(self.events()) if event["stage"] == stage and event["job"] == job), None)

    def public_progress(self):
        configurations = [self.config["training_experiment_reference"]]
        transition = execution_transition(self.config)
        if transition:
            configurations.insert(0, transition["previous_experiment_reference"])
        evaluation = self.latest("EVALUATION_CONFIGURED")
        if evaluation:
            configurations.append(evaluation["details"]["experiment_reference"])
        snapshot = self.operations.progress(configurations, Path(self.config["progress_root"]))
        check(snapshot)
        self.record("PUBLIC_PROGRESS", {"snapshot_reference": snapshot})

    def _cohort(self, root, phase, remaining):
        status = self.operations.cohort_status(root)
        expected = 24 if phase == "TRAINING" else 1000
        if status["planned_cells"] != expected or status["scope"] != "FULL_FIXED_COHORT":
            raise PipelineError("pipeline refuses a reduced or reselected cohort")
        advanced = 0
        while status["status"] != "COMPLETE":
            if remaining is not None and advanced >= remaining:
                return False, advanced
            before = status["completed_cells"]
            self.record("COHORT_ADVANCE_STARTED", {"phase": phase, "completed_before": before})
            status = self.operations.run_cohort(root)
            self.public_progress()
            self.record("COHORT_PROGRESS", {"phase": phase, "status": {key: value for key, value in status.items() if key != "cells"}})
            if status["status"] == "BLOCKED":
                raise PipelineError(phase + " cohort is blocked; no solver outcome retry")
            delta = status["completed_cells"] - before
            if delta not in (0, 1) or (delta == 0 and status["status"] != "COMPLETE"):
                raise PipelineError("one-cell cohort advance did not produce exactly one completed cell")
            advanced += delta
        if status["completed_cells"] != expected:
            raise PipelineError("cohort declared completion without all enrolled cells")
        if not self.latest(phase + "_COMPLETE"):
            self.public_progress()
            self.record(phase + "_COMPLETE", {"status": {key: value for key, value in status.items() if key != "cells"}})
        return True, advanced

    def _plan(self):
        existing = self.latest("REFLECTION_PLAN")
        if existing:
            return check(existing["details"]["reference"])["jobs"]
        inventory = self.operations.inventory(self.learning_root)
        targets = check(self.training["dataset_manifest"])["targets"]
        jobs = select_reflection_jobs(targets, inventory)
        if not {item["repository"] for item in self.config["adopted_reflections"]} <= {job["repository"] for job in jobs}:
            raise PipelineError("publisher adoption is outside the fixed reflection repositories")
        receipt = retain(self.root / "reflection-plan.json", {"schema": SCHEMA, "selection_policy": SELECTION,
            "all_captures_retained": True, "official_outcomes_used_for_selection": False, "jobs": jobs})
        self.record("REFLECTION_PLAN", {"reference": receipt})
        return jobs

    def _reflect(self, job):
        name = job["repository"]
        if job["status"] != "READY":
            if not self.latest("REFLECTION_SKIPPED", name):
                self.record("REFLECTION_SKIPPED", {"reason": job["status"], "source_count": len(job["capture_ids"]),
                    "no_fabricated_sources": True}, job=name)
            return
        folder = Path(self.config["reflection_native_root"]) / f"repo-{job['ordinal']:02d}"
        adoption = next((item for item in self.config["adopted_reflections"] if item["repository"] == name), None)
        public_path = (linux_path(check(adoption["configuration_reference"])["reflection_reference"]["path"])
            if adoption else check(job["reflection_reference"], decode=False)
            if "reflection_reference" in job else folder / "public-reflection.json")
        exported = self.latest("REFLECTION_EXPORTED", name)
        if exported:
            reflection_ref = exported["details"]["reference"]
            check(reflection_ref)
        else:
            reflection_ref = self.operations.export_reflection(self.learning_root, public_path,
                job["capture_ids"], self.config["reflection_max_bytes"])
            if Path(reflection_ref["path"]) != public_path:
                raise PipelineError("reflection exporter returned another source path")
            self.record("REFLECTION_EXPORTED", {"reference": reflection_ref, "capture_ids": job["capture_ids"]}, job=name)
        expected = {key: self.training[key] for key in ("model", "authentication", "reasoning_effort", "codex_binary", "windows_python")}
        if adoption:
            configuration_ref = adoption["configuration_reference"]
            publisher_config = check(configuration_ref)
            if any(publisher_config.get(key) != value for key, value in expected.items()):
                raise PipelineError("adopted publisher model or authentication differs")
            launcher_ref, completion_ref = adoption["launcher_reference"], adoption["completion_reference"]
        else:
            publisher_config = {**expected, "reflection_reference": {"path": windows_path(public_path), "sha256": reflection_ref["sha256"]},
                "worker_output": windows_path(folder / "output"), "worker_cwd": windows_path(folder / "cwd")}
            configuration_ref = retain(folder / "publisher-config.json", publisher_config)
            launcher_path = folder / "interop-completion.json"
            completion_path = folder / "output/completion.json"
            started = self.latest("PUBLISH_STARTED", name)
            if started is None and self.latest("PUBLISHED", name) is None:
                if launcher_path.exists() or (folder / "output").exists() or (folder / "cwd").exists():
                    raise PipelineError("pre-existing publisher attempt requires explicit frozen adoption")
                self.record("PUBLISH_STARTED", {"configuration_reference": configuration_ref,
                    "reflection_reference": reflection_ref}, job=name)
                self.operations.launch_publisher(configuration_ref, launcher_path)
            # Missing files after a started invocation are an infrastructure block, never a new launch.
            launcher_ref, completion_ref = ref(launcher_path), ref(completion_path)
        proof = self.operations.validate_publisher(configuration_ref, completion_ref, launcher_ref, reflection_ref)
        previous = self.latest("PUBLISHED", name)
        others = [event["details"]["thread_id"] for event in self.events() if event["stage"] == "PUBLISHED" and event["job"] != name]
        if proof["thread_id"] in others:
            raise PipelineError("repository reflection reused another native thread")
        if previous is not None and previous["details"] != proof:
            raise PipelineError("completed native publication evidence changed")
        if previous is None:
            self.record("PUBLISHED", proof, job=name)
        ingested = self.latest("PROPOSALS_INGESTED", name)
        if ingested:
            check(ingested["details"]["reference"])
            return
        identity = digest(canonical_bytes({"proposal": proof["proposal_reference"], "reflection": reflection_ref}))
        durable = self.learning_root / "learning-ingestions" / (identity + ".json")
        if self.latest("INGEST_STARTED", name) and not durable.is_file():
            raise PipelineError("interrupted proposal verification has no durable receipt; no automatic replay")
        if not self.latest("INGEST_STARTED", name):
            self.record("INGEST_STARTED", {"proposal_reference": proof["proposal_reference"],
                "reflection_reference": reflection_ref}, job=name)
        ingestion_ref = self.operations.ingest(self.learning_root, proof["proposal_reference"], reflection_ref)
        ingestion = check(ingestion_ref)
        if ingestion.get("proposal_reference") != proof["proposal_reference"] or ingestion.get("reflection_reference") != reflection_ref:
            raise PipelineError("proposal verification receipt differs from native output")
        self.record("PROPOSALS_INGESTED", {"reference": ingestion_ref,
            "promotions_added": ingestion["promotions_added"], "failures": ingestion["failures"]}, job=name)

    def _freeze(self):
        existing = self.latest("BANK_FROZEN")
        if existing:
            self.operations.validate_bank(existing["details"]["bank_reference"])
            check(existing["details"]["publication_reference"])
            return existing["details"]["bank_reference"]
        bank_path = self.root / "trained-bank.json"
        frozen_marker = self.learning_root / "learning-frozen.json"
        if frozen_marker.is_file():
            publication_ref = read(frozen_marker)
            publication = check(publication_ref)
            bank = publication["bank"]
            if Path(bank["path"]) != bank_path or publication["enrollment_reference"] != self.config["learning_enrollment_reference"]:
                raise PipelineError("existing publication belongs to another pipeline or learning authority")
            result = {**bank, "publication_reference": publication_ref}
        else:
            if self.latest("BANK_FREEZE_STARTED"):
                raise PipelineError("interrupted bank publication has no completed frozen receipt; no automatic replay")
            self.record("BANK_FREEZE_STARTED", {"output_path": str(bank_path)})
            try:
                result = self.operations.freeze(self.learning_root, bank_path)
            except ValueError as exc:
                catalog = read(self.learning_root / "catalog.json")
                if not catalog["skills"] and ("actually promoted Gate B skill" in str(exc) or "reflection proposal validation receipts" in str(exc)):
                    self.record("TRAINING_COMPLETE_NOT_EVALUATION_READY", {"reason": "NO_VERIFIED_GATE_B_SKILL",
                        "publication_error": str(exc), "catalog_reference": ref(self.learning_root / "catalog.json"),
                        "training_tasks_accounted": 24, "evaluation_cells_started": 0})
                    return None
                raise
        bank_reference = {key: result[key] for key in ("path", "sha256")}
        publication = check(result["publication_reference"])
        if (publication.get("schema") != "skhynix/native-architecture-learning/1.0"
                or publication.get("learning_version") != 2 or publication.get("operation") != "PUBLISH_TRAINED_BANK"
                or publication.get("actual_training_sources") != 24
                or publication.get("enrollment_reference") != self.config["learning_enrollment_reference"]
                or {key: publication["bank"][key] for key in ("path", "sha256")} != bank_reference):
            raise PipelineError("published bank receipt does not account for the bound v2 training cohort")
        counts = self.operations.validate_bank(bank_reference)
        self.record("BANK_FROZEN", {"bank_reference": bank_reference,
            "publication_reference": result["publication_reference"], "layer_counts": counts})
        return bank_reference

    def _evaluation(self, bank_reference):
        value = {**self.training, "phase": "EVALUATION_RUNTIME", "evaluation_status": "EVALUATION_READY",
            "run_root": self.config["evaluation_run_root"], "native_control_root": self.config["evaluation_native_root"],
            "frozen_bank_reference": bank_reference, "pipeline_reference": self.reference}
        path = self.root / "evaluation-execution.json"
        reference = retain(path, value)
        checksum = path.with_suffix(".sha256")
        expected = (digest(canonical_bytes(value)) + "\n").encode()
        if checksum.exists() and checksum.read_bytes() != expected:
            raise PipelineError("evaluation configuration checksum changed")
        if not checksum.exists():
            with checksum.open("xb") as stream:
                stream.write(expected)
        cohort_root = Path(self.config["evaluation_run_root"]) / "cohort"
        existing = self.latest("EVALUATION_CONFIGURED")
        if existing:
            if existing["details"]["experiment_reference"] != reference:
                raise PipelineError("evaluation configuration no longer matches its frozen event")
            for key in ("cohort_reference", "quarantine_reference", "cleanup_policy_reference"):
                check(existing["details"][key])
            return cohort_root
        receipts = self.operations.prepare_evaluation(reference, bank_reference, cohort_root,
            Path(self.config["evaluation_run_root"]) / "quarantine", self.root / "evaluation-cleanup-policy.json")
        self.record("EVALUATION_CONFIGURED", {"experiment_reference": reference, **receipts})
        return cohort_root

    def run(self, *, cell_limit=None, training_only=False):
        if cell_limit is not None and (type(cell_limit) is not int or cell_limit < 1):
            raise PipelineError("cell limit must be a positive whole-task limit")
        with predecessor_guard(self.config), locked(self.root / "run.lock"):
            check(self.reference)
            _validate_config(self.config)
            if "supersedes" in self.config and not self.latest("CONTROLLER_SUPERSESSION"):
                self.record("CONTROLLER_SUPERSESSION", {"predecessor": self.config["supersedes"],
                    "training_cohort_reference": self.config["training_cohort_reference"],
                    "original_evidence_preserved": True, "native_outcome_retries": False})
            if self.latest("TRAINING_COMPLETE_NOT_EVALUATION_READY") or self.latest("PIPELINE_COMPLETE"):
                return self.status()
            try:
                completed, advanced = self._cohort(self.training_cohort, "TRAINING", cell_limit)
                if not completed or training_only:
                    return self.status()
                for job in self._plan():
                    self._reflect(job)
                bank_reference = self._freeze()
                if bank_reference is None:
                    return self.status()
                evaluation_root = self._evaluation(bank_reference)
                remaining = None if cell_limit is None else cell_limit - advanced
                completed, _ = self._cohort(evaluation_root, "EVALUATION", remaining)
                if completed:
                    self.record("PIPELINE_COMPLETE", {"training_cells": 24, "evaluation_cells": 1000,
                        "paired_targets": 500, "bank_reference": bank_reference})
            except Exception as exc:
                self.record("PIPELINE_BLOCKED", {"error_type": type(exc).__name__, "reason": str(exc)[:2000],
                    "automatic_native_retries": False, "evaluation_results_used_for_training": False})
            return self.status()

    def status(self):
        events = self.events()
        terminal = self.latest("TRAINING_COMPLETE_NOT_EVALUATION_READY")
        if terminal:
            check(terminal["details"]["catalog_reference"])
        bank = self.latest("BANK_FROZEN")
        if bank:
            self.operations.validate_bank(bank["details"]["bank_reference"])
            check(bank["details"]["publication_reference"])
        stage = "COMPLETE" if self.latest("PIPELINE_COMPLETE") else "TRAINING_COMPLETE_NOT_EVALUATION_READY" if terminal else (
            "BLOCKED" if events and events[-1]["stage"] == "PIPELINE_BLOCKED" else "IN_PROGRESS")
        progress = self.latest("PUBLIC_PROGRESS")
        if progress:
            check(progress["details"]["snapshot_reference"])
        return {"schema": SCHEMA, "status": stage, "event_count": len(events),
            "event_tail_sha256": events[-1]["sha256"] if events else "0" * 64,
            "training_complete": self.latest("TRAINING_COMPLETE") is not None,
            "evaluation_configured": self.latest("EVALUATION_CONFIGURED") is not None,
            "reflection_repositories_published": sum(event["stage"] == "PUBLISHED" for event in events),
            "reflection_repositories_skipped": sum(event["stage"] == "REFLECTION_SKIPPED" for event in events),
            "public_progress_reference": progress["details"]["snapshot_reference"] if progress else None,
            "last_event": events[-1] if events else None, "outcome_retries": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "run", "status"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--definition", type=Path)
    parser.add_argument("--cell-limit", type=int)
    parser.add_argument("--training-only", action="store_true")
    args = parser.parse_args()
    if args.command == "create":
        if args.definition is None:
            parser.error("create requires --definition")
        result = create_pipeline_config(args.config.resolve(), read(args.definition))
    else:
        pipeline = Pipeline(args.config.resolve())
        result = pipeline.run(cell_limit=args.cell_limit, training_only=args.training_only) if args.command == "run" else pipeline.status()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
