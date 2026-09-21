"""Evaluate a separately verified reflection recovery without repeating training.

Run as a standalone controller with the original frozen solver on PYTHONPATH.
Offline discovery/projection modules are never imported into this process.
"""
from contextlib import contextmanager, ExitStack
from pathlib import Path, PurePosixPath
import argparse
import importlib.util
import json
import sys
import time

import trimem_skhynix_architecture_pipeline as core
import trimem_skhynix_architecture_scale_pipeline as scale

SCHEMA = "skhynix/architecture-reflection-recovery-pipeline/1.0"
RECOVERY_SCHEMA = "skhynix/architecture-reflection-recovery/1.0"
CLONE_SCHEMA = "skhynix/learning-authority-recovery/1.0"
RECOVERED_SIZE = 240
PROMOTION_CHANGED_PATH = "src/enterprise_memory/trimem/skill_memory.py"
PROMOTION_GROUPS = 4


def _fail(message):
    raise core.PipelineError(message)


def _normalized(reference):
    path = reference["path"]
    value = {"path": str(core.absolute(path) if Path(path).is_absolute() else core.linux_path(path)), "sha256": reference["sha256"]}
    core.check(value, decode=False)
    return value


def _same_references(first, second):
    return sorted(first, key=lambda row: (row["path"], row["sha256"])) == sorted(second, key=lambda row: (row["path"], row["sha256"]))


def _load_predecessor_controller(previous):
    """Load separately pinned orchestration, never replacing a solver module.

    The historical controller is intentionally outside the solver source tree.
    Its explicit immutable reference authorizes this orchestration module only;
    FrozenOperations retains its unchanged scan of every solver/runtime import.
    """
    reference = previous["pipeline_source_reference"]
    path = core.check(reference, decode=False)
    name = "skhynix_bound_scale_controller_" + reference["sha256"]
    if name in sys.modules:
        module = sys.modules[name]
        if core.ref(module.__file__) != reference:
            _fail("Previously loaded controller differs from historical authority")
        return module
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        if any(not hasattr(module, field) for field in ("ScalePipeline", "validate_grading_continuation",
                "validate_infrastructure_replacement", "_grading_lineage", "_event_reference")):
            _fail("Predecessor controller lacks the bound historical recovery validators")
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def validate_config(config, *, executing_source=None):
    if config.get("schema") != SCHEMA:
        _fail("Unsupported reflection recovery controller")
    previous = core.check(config["supersedes_configuration_reference"])
    allowed = {"schema", "pipeline_root", "progress_root", "reflection_native_root", "evaluation_native_root",
               "pipeline_source_reference", "supersedes_configuration_reference", "revision_reason",
               "predecessor_pipeline_event_tail_reference", "reflection_recovery_reference"}
    if {k: v for k, v in config.items() if k not in allowed} != {k: v for k, v in previous.items() if k not in allowed}:
        _fail("Reflection recovery cannot change training, solver, memory retrieval or evaluation protocol")
    for field in ("pipeline_root", "progress_root", "reflection_native_root", "evaluation_native_root"):
        path = core.absolute(config[field])
        old = core.absolute(previous[field])
        if field != "progress_root" and (path == old or old in path.parents or path in old.parents):
            _fail("Reflection recovery requires separate execution roots")
    if executing_source is not None and core.ref(executing_source) != config["pipeline_source_reference"]:
        _fail("Recovery controller differs from its frozen implementation")
    core.check(config["pipeline_source_reference"], decode=False)
    _load_predecessor_controller(previous).validate_config(previous)
    _predecessor(config, previous)
    return previous


def _predecessor(config, previous):
    root = Path(previous["pipeline_root"])
    if core.read(root / "pipeline-binding.json") != {
            "schema": scale.SCHEMA, "configuration_reference": config["supersedes_configuration_reference"]}:
        _fail("Completed predecessor binding changed")
    tail = _load_predecessor_controller(previous)._event_reference(config["predecessor_pipeline_event_tail_reference"], root, tail=True)
    events = core.read_event_chain(root)
    if (tail.get("stage") != "NO_READY_MEMORY_BANK" or tail["details"].get("source_attempts") != 240 or
            tail["details"].get("gate_b_waived") is not False or tail["details"].get("final_evaluation_cells") != 0 or
            any(row["stage"] in {"EVALUATION_CONFIGURED", "EVALUATION_COMPLETE", "BANK_SELECTED", "PIPELINE_COMPLETE"} for row in events)):
        _fail("Recovery needs completed untouched training and no previous evaluation")
    banks = tail["details"].get("banks", [])
    if [bank.get("size") for bank in banks] != list(scale.SIZES) or any(bank.get("status") != "NOT_READY" for bank in banks):
        _fail("Recovery must preserve all original NOT_READY decisions")
    for bank in banks:
        core.check(bank["catalog_reference"])
    return banks


def _group_jobs(manifest, original_catalog, publisher_module):
    completion = core.check(manifest["grouping_completion_reference"])
    input_ref = manifest["grouping_input_reference"]
    public, mapping = core.check(input_ref), core.check(manifest["grouping_map_reference"])
    if (completion.get("schema") != "skhynix/semantic-grouping-completion/1.0" or
            _normalized(completion["input_reference"]) != input_ref or
            public.get("all_representative_candidates_included") is not True or public.get("official_outcomes_used") is not False):
        _fail("Semantic grouping must bind the complete public training candidate input")
    launch = core.check(_normalized(completion["launch_reference"]))
    if (launch.get("fresh_session") is not True or launch.get("requested_model") != "gpt-6-astra" or
            launch.get("reasoning_effort") != "high" or _normalized(launch["input_reference"]) != input_ref):
        _fail("Semantic grouping changed the requested fresh model/high session")
    response_ref = _normalized(completion["response_reference"])
    response = core.check(response_ref)
    if response.get("schema") != "skhynix/semantic-repair-grouping/1.0" or response.get("input_sha256") != input_ref["sha256"]:
        _fail("Semantic grouping response differs from its immutable input")
    event_path = Path(manifest["grouping_completion_reference"]["path"]).parent / "events.jsonl"
    event_bytes = event_path.read_bytes()
    if core.digest(event_bytes) != completion.get("events_sha256"):
        _fail("Semantic grouping event evidence changed")
    thread, native_text = publisher_module.validate_events([core.strict_json_loads(line) for line in event_bytes.splitlines()])
    if (completion.get("thread_id") != thread or completion.get("response_text_sha256") != core.digest(native_text.encode()) or
            core.strict_json_loads(native_text) != response):
        _fail("Semantic grouping response is not the exact final response of its fresh native worker")
    candidates = mapping["candidates"]
    core.check(mapping["index_reference"])
    if {row["candidate_id"] for row in public["candidates"]} != set(candidates):
        _fail("Semantic candidate map omits or adds input candidates")
    for item in candidates.values():
        if original_catalog["captures"].get(item["capture_id"]) != item["capture_reference"]:
            _fail("Semantic discovery used a capture outside the original training authority")
        core.check(item["capture_reference"])
    groups, jobs = response["groups"], manifest["jobs"]
    partition = [candidate for group in groups for candidate in group["candidate_ids"]]
    partition += [row["candidate_id"] for row in response["ungrouped"]]
    if len(partition) != len(set(partition)) or set(partition) != set(candidates):
        _fail("Semantic discovery must account for every original candidate exactly once")
    if not groups or len(groups) != len(jobs) or manifest.get("proposed_group_count") != len(groups):
        _fail("Every discovered group must be reflected and ingested without outcome selection")
    for group, job in zip(groups, jobs):
        ids = group["candidate_ids"]
        if (len(ids) < 2 or sorted(job["capture_ids"]) != sorted(candidates[key]["capture_id"] for key in ids) or
                len({candidates[key]["task_id"] for key in ids}) < 2 or
                len({candidates[key]["owner_user_id"] for key in ids}) < 2):
            _fail("Reflection group changed independent original discovery membership")
    return jobs


def _validate_promotion_revision(manifest, config, clone):
    """Admit an explicitly versioned offline scanner correction, never a solver change."""
    reference = manifest.get("promotion_revision_reference")
    if reference is None:
        return
    revision = core.check(reference)
    required = {"schema": "skhynix/offline-promotion-revalidation/1.0",
        "operation": "REVALIDATE_ALL_RETAINED_NATIVE_PROPOSALS_WITH_TYPED_TEMPLATE_SCAN",
        "model_calls": 0, "solver_runs": 0, "official_grader_runs": 0, "native_proposal_retries": 0,
        "red_edit_green_verifier_unchanged": True, "native_solver_runtime_unchanged": True,
        "verification_implementation_changed": "TYPED_PROCEDURE_PRIVACY_SCAN"}
    if any(type(revision.get(key)) is not type(value) or revision[key] != value for key, value in required.items()):
        _fail("Unsupported separately versioned offline promotion revision")
    runtime = core.check(revision["runtime_reference"])
    execution = core.check(config["training_experiment_reference"])
    old_root, new_root = core.absolute(runtime["old_source_root"]), core.absolute(runtime["source_root"])
    before, after = runtime["old_source_sha256"], runtime["source_sha256"]
    if (runtime.get("schema") != "skhynix/offline-promotion-runtime/1.0" or
            runtime.get("previous_execution_reference") != config["training_experiment_reference"] or
            runtime.get("changed_paths") != [PROMOTION_CHANGED_PATH] or before != execution["source_sha256"] or
            str(old_root) != execution["source_root"] or set(before) != set(after) or old_root == new_root or
            old_root in new_root.parents or new_root in old_root.parents or
            sorted(key for key in before if before[key] != after[key]) != [PROMOTION_CHANGED_PATH] or
            any(runtime.get(key) != 0 for key in ("model_calls", "solver_runs", "official_grader_runs"))):
        _fail("Offline revision must leave the paired evaluator at the original frozen solver")
    for name in before:
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "__pycache__" in relative.parts:
            _fail("Offline source snapshot contains an invalid relative path")
        for root, mapping in ((old_root, before), (new_root, after)):
            core.check({"path": str(root / name), "sha256": mapping[name]}, decode=False)
    if not runtime.get("test_references"):
        _fail("Offline scanner correction lacks retained verification tests")
    for ref in runtime["test_references"]:
        core.check(ref, decode=False)
    old = core.check(revision["predecessor_manifest_reference"])
    old_clone = core.check(old["clone_reference"])
    request = core.check(revision["request_reference"])
    for key in ("driver_reference", "predecessor_learning_state_reference"):
        core.check(revision[key], decode=False)
    if (revision.get("clone_reference") != manifest["clone_reference"] or
            old.get("schema") != RECOVERY_SCHEMA or old.get("status") not in {"READY", "NOT_READY"} or
            old.get("promotion_revision_reference") is not None or len(old.get("jobs", [])) != PROMOTION_GROUPS or
            len(manifest.get("jobs", [])) != PROMOTION_GROUPS or old.get("proposed_group_count") != PROMOTION_GROUPS or
            len(revision.get("jobs", [])) != PROMOTION_GROUPS or
            old_clone["source_snapshot_references"] != clone["source_snapshot_references"] or
            old_clone["predecessor_pipeline_reference"] != clone["predecessor_pipeline_reference"] or
            old_clone["destination_root"] == clone["destination_root"] or
            revision["predecessor_learning_state_reference"]["path"] != str(Path(old_clone["destination_root"]) / "learning-state.json") or
            request.get("schema") != "skhynix/offline-promotion-revalidation-request/1.0" or
            request.get("predecessor_manifest_reference") != revision["predecessor_manifest_reference"] or
            request.get("runtime_reference") != revision["runtime_reference"] or request.get("clone_reference") != manifest["clone_reference"] or
            manifest.get("request_reference") != revision["request_reference"] or manifest.get("driver_reference") != revision["driver_reference"]):
        _fail("Offline promotion revision changed original provenance or reused an old learning authority")
    for key in ("grouping_completion_reference", "grouping_input_reference", "grouping_map_reference", "projection_producer_reference"):
        if old[key] != manifest[key]:
            _fail("Offline scanner revision cannot replace discovery or projection evidence")
    old_state = core.check(revision["predecessor_learning_state_reference"])
    for index, (old_job, new_job, pair) in enumerate(zip(old["jobs"], manifest["jobs"], revision["jobs"]), 1):
        if {key: value for key, value in old_job.items() if key != "ingestion_reference"} != {
                key: value for key, value in new_job.items() if key != "ingestion_reference"}:
            _fail("Offline scanner revision must revalidate every identical retained native proposal")
        expected = {"ordinal": index, "reflection_reference": new_job["reflection_reference"],
            "proposal_reference": new_job["native_proof"]["proposal_reference"],
            "old_ingestion_reference": old_job["ingestion_reference"], "new_ingestion_reference": new_job["ingestion_reference"]}
        old_ingestion = core.check(old_job["ingestion_reference"])
        if (pair != expected or old_job["ingestion_reference"] == new_job["ingestion_reference"] or
                old_job["ingestion_reference"] not in old_state["ingestions"].values() or
                old_ingestion.get("proposal_reference") != expected["proposal_reference"] or
                old_ingestion.get("reflection_reference") != expected["reflection_reference"]):
            _fail("Original failed ingestion and new verification must both remain exactly retained")


def validate_recovered_bank(config, previous, operations):
    manifest = core.check(config["reflection_recovery_reference"])
    if (manifest.get("schema") != RECOVERY_SCHEMA or manifest.get("outcome_retries") is not False or
            manifest.get("official_outcomes_used") is not False or manifest.get("gate_b_waived") is not False):
        _fail("Unsupported reflection-only recovery provenance")
    clone = core.check(manifest["clone_reference"])
    _validate_promotion_revision(manifest, config, clone)
    stage = next(item for item in previous["training_stages"] if item["size"] == RECOVERED_SIZE)
    expected_source = Path(stage.get("learning_root", Path(previous["pipeline_root"]) / ("learning-" + str(RECOVERED_SIZE))))
    clone_root = core.absolute(clone["destination_root"])
    metadata = {"learning-enrollment.json", "learning-enrollment.ref.json", "scope.json",
                "catalog.json", "learning-state.json", "authority.sqlite3"}
    if (clone.get("schema") != CLONE_SCHEMA or clone.get("predecessor_pipeline_reference") != config["supersedes_configuration_reference"] or
            clone.get("predecessor_pipeline_event_tail_reference") != config["predecessor_pipeline_event_tail_reference"] or
            clone.get("source_root") != str(expected_source) or clone.get("stage_execution_reference") != stage["execution_reference"] or
            clone.get("learning_enrollment_reference", {}).get("path") != str(clone_root / "learning-enrollment.json") or
            clone.get("counts", {}).get("training_sources") != RECOVERED_SIZE or clone["counts"].get("L3_skills") != 0 or
            clone.get("original_evidence_paths_preserved") is not True or clone.get("gate_b_waived") is not False or
            any(clone.get(key) != 0 for key in ("model_calls", "solver_runs", "official_grader_runs", "source_recaptures"))):
        _fail("Recovery clone differs from the unchanged complete original training authority")
    if (set(clone["source_snapshot_references"]) != metadata or set(clone["clone_initial_references"]) != metadata or
            any(clone["source_snapshot_references"][name]["path"] != str(expected_source / name) or
                clone["clone_initial_references"][name]["path"] != str(clone_root / "recovery-initial" / name) or
                (name != "authority.sqlite3" and clone["source_snapshot_references"][name]["sha256"] !=
                 clone["clone_initial_references"][name]["sha256"]) for name in metadata)):
        _fail("Clone snapshot metadata must bind the exact original and separately retained initial copies")
    for group in (clone["source_snapshot_references"], clone["clone_initial_references"], clone["implementation_references"]):
        for ref in group.values():
            core.check(ref, decode=False)
    for ref in clone["original_evidence_references"]:
        core.check(ref, decode=False)
    for key in ("recovery_helper_reference", "request_reference"):
        if clone.get(key) is not None:
            core.check(clone[key], decode=False)
    core.check(manifest["projection_producer_reference"], decode=False)
    initial = core.check(clone["clone_initial_references"]["learning-state.json"])
    original_catalog = core.check(clone["source_snapshot_references"]["catalog.json"])
    jobs = _group_jobs(manifest, original_catalog, operations.modules["publisher"])
    publication = core.check(manifest["publication_reference"])
    if (publication.get("operation") != "PUBLISH_TRAINED_BANK" or publication.get("actual_training_sources") != RECOVERED_SIZE or
            publication.get("enrollment_reference") != clone["learning_enrollment_reference"] or
            publication.get("official_grader_payloads_read") != 0 or
            core.read(clone_root / "learning-frozen.json") != manifest["publication_reference"] or
            not _same_references(publication["cell_receipts"], list(initial["cells"].values()))):
        _fail("Published recovery bank must preserve all original captured sources")
    bank_ref = {key: publication["bank"][key] for key in ("path", "sha256")}
    bank = core.check(bank_ref)
    if core.read(clone_root / "frozen.json") != bank_ref:
        _fail("Recovery bank differs from the clone's frozen authority")
    for key in ("captures", "knowledge", "edges"):
        if bank["catalog"][key] != original_catalog[key]:
            _fail("Reflection recovery changed original L1/L2 evidence")
    exports = {item["public"]["sha256"]: item for item in publication["reflection_exports"]}
    expected_exports = dict(initial["reflections"])
    ingestion_refs, promoted = list(initial["ingestions"].values()), set()
    threads = {core.check(manifest["grouping_completion_reference"])["thread_id"]}
    for job in jobs:
        reflection_ref = job["reflection_reference"]
        config_ref, completion_ref, launcher_ref = (job[key] for key in
            ("configuration_reference", "completion_reference", "launcher_reference"))
        publisher = core.check(config_ref)
        template = core.check(config["training_experiment_reference"])
        if any(publisher.get(key) != template.get(key) for key in
                ("model", "authentication", "reasoning_effort", "codex_binary", "windows_python")):
            _fail("Recovery publisher changed the original model/high/native configuration")
        proof = operations.validate_publisher(config_ref, completion_ref, launcher_ref, reflection_ref)
        if proof != job["native_proof"] or proof["thread_id"] in threads:
            _fail("Recovery publisher provenance changed or reused another worker thread")
        threads.add(proof["thread_id"])
        ingestion = core.check(job["ingestion_reference"])
        if (ingestion.get("proposal_reference") != proof["proposal_reference"] or
                ingestion.get("reflection_reference") != reflection_ref or
                ingestion.get("status") != "PROCESSED" or ingestion.get("failures") != []):
            _fail("Recovery ingestion does not bind its actual native proposal and reflection")
        registered = exports.get(reflection_ref["sha256"])
        if registered is None or registered["public"] != reflection_ref:
            _fail("New reflection is absent from the actual frozen publication")
        mapping = core.check(registered["private"])
        public = core.check(reflection_ref)
        if (public["publisher_map_sha256"] != core.digest(core.canonical_bytes(mapping)) or
                mapping["enrollment_sha256"] != clone["learning_enrollment_reference"]["sha256"] or
                sorted(row["capture_id"] for row in mapping["sources"].values()) != sorted(job["capture_ids"]) or
                any(original_catalog["captures"].get(row["capture_id"]) != row["capture_reference"] for row in mapping["sources"].values())):
            _fail("Recovery reflection projection changed its original capture mapping")
        expected_exports[reflection_ref["sha256"]] = registered
        ingestion_refs.append(job["ingestion_reference"])
        promoted.update(row["promotion"]["skill_id"] for row in ingestion["outcomes"] if row["status"] in {"PROMOTED", "ALREADY_PROMOTED"})
    if (exports != expected_exports or len(publication["reflection_exports"]) != len(expected_exports) or
            not _same_references(publication["ingestion_receipts"], ingestion_refs) or
            promoted != set(bank["catalog"]["skills"]) or not promoted):
        _fail("Published skills must come from every retained recovery reflection without hidden ingestions")
    operations.training = core.check(stage["execution_reference"])
    counts = operations.validate_bank(bank_ref)
    return {"size": RECOVERED_SIZE, "status": "READY", "source_attempts": RECOVERED_SIZE,
            "bank_reference": bank_ref, "publication_reference": manifest["publication_reference"],
            "reflection_recovery_reference": config["reflection_recovery_reference"], "layer_counts": counts}


class ReflectionRecoveryPipeline(core.Pipeline):
    def __init__(self, config_path, *, operations=None, clock=time.time):
        self.path, self.clock = core.absolute(config_path), clock
        self.reference, self.config = core.ref(self.path), core.read(self.path)
        if self.path.with_suffix(".sha256").read_text().strip() != core.digest(core.canonical_bytes(self.config)):
            _fail("Recovery controller configuration checksum differs")
        self.previous = validate_config(self.config, executing_source=Path(__file__).resolve())
        self.scale = _load_predecessor_controller(self.previous)
        self.root = Path(self.config["pipeline_root"])
        self.operations = operations or core.FrozenOperations(self.config)
        self.scale.validate_grading_continuation(self.previous, execution=self.operations.modules["cohort"].execution)
        self.scale.validate_infrastructure_replacement(self.previous, execution=self.operations.modules["cohort"].execution)
        self.root.mkdir(parents=True, exist_ok=True)
        core.retain(self.root / "pipeline-binding.json", {"schema": SCHEMA, "configuration_reference": self.reference})
        (self.root / "events").mkdir(exist_ok=True)

    @contextmanager
    def _controller_locks(self):
        adoption = core.check(self.previous["source_adoption_reference"])
        tails = [self.config["predecessor_pipeline_event_tail_reference"], adoption["original_pipeline_event_tail_reference"],
                 *adoption.get("predecessor_pipeline_event_tail_references", [])]
        receipts = [receipt for _, receipt in self.scale._grading_lineage(self.previous)]
        if self.previous.get("infrastructure_replacement_reference"):
            receipts.append(core.check(self.previous["infrastructure_replacement_reference"]))
        for receipt in receipts:
            tails.extend(value for key, value in receipt.items() if key.endswith("_event_tail_reference") and isinstance(value, dict))
        roots = {}
        for tail in tails:
            path = core.absolute(tail["path"])
            root = path.parent.parent
            if path.parent.name != "events" or root == self.root or (root in roots and roots[root] != tail):
                _fail("Conflicting recovery predecessor journal authority")
            roots[root] = tail
        with ExitStack() as stack:
            for root in sorted([self.root, *roots], key=str):
                stack.enter_context(self.scale.locked(root / "run.lock"))
            for root, tail in roots.items():
                self.scale._event_reference(tail, root, tail=True)
            core.check(self.reference)
            _predecessor(self.config, self.previous)
            yield

    def _evaluation(self, *args):
        return self.scale.ScalePipeline._evaluation(self, *args)

    def _advance_runner(self, *args):
        return self.scale.ScalePipeline._advance_runner(self, *args)

    def progress(self):
        return self.scale.ScalePipeline.progress(self)

    def run(self):
        with self._controller_locks():
            if self.latest("PIPELINE_COMPLETE"):
                return self.status()
            try:
                bank = validate_recovered_bank(self.config, self.previous, self.operations)
                if not self.latest("RECOVERY_BANK_VALIDATED"):
                    self.record("RECOVERY_BANK_VALIDATED", bank)
                stages = {row["size"]: row for row in self.config["training_stages"]}
                baseline, baseline_ref = self._evaluation("DEVELOPMENT_BASELINE", stages[24], None, "baseline")
                candidate, candidate_ref = self._evaluation("DEVELOPMENT_BANK", stages[RECOVERED_SIZE], bank["bank_reference"], "bank-240")
                chosen = self.scale.selection([candidate], baseline)
                chosen.update(baseline_report_reference=baseline_ref, candidate_report_references=[candidate_ref],
                              protocol_reference=self.config["protocol_reference"],
                              reflection_recovery_reference=self.config["reflection_recovery_reference"])
                selection_ref = core.retain(self.root / "bank-selection.json", chosen)
                if not self.latest("BANK_SELECTED"):
                    self.record("BANK_SELECTED", {"reference": selection_ref})
                final, final_ref = self._evaluation("FINAL_EVALUATION", stages[RECOVERED_SIZE], bank["bank_reference"], "verified500")
                self.record("PIPELINE_COMPLETE", {"report_reference": final_ref, "selection_reference": selection_ref,
                            "source_attempts": 240, "new_training_solves": 0, "final_cells": 1000, "development_cells": 120})
            except Exception as exc:
                self.record("PIPELINE_BLOCKED", {"error_type": type(exc).__name__, "reason": str(exc)[:2000],
                            "native_outcome_retries": False, "final_outcomes_used_for_training": False})
                self.progress()
                raise
            self.progress()
            return self.status()

    def status(self):
        events = self.events()
        return {"schema": SCHEMA, "status": "COMPLETE" if self.latest("PIPELINE_COMPLETE") else
                "BLOCKED" if events and events[-1]["stage"] == "PIPELINE_BLOCKED" else "IN_PROGRESS",
                "configuration_reference": self.reference, "reflection_recovery_reference": self.config["reflection_recovery_reference"],
                "source_attempts": 240, "new_training_solves": 0, "development_tasks": 60,
                "final_tasks": 500, "final_cells": 1000, "selection_policy": scale.SELECTION_POLICY,
                "native_outcome_retries": False, "last_event": events[-1] if events else None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "run", "status"))
    parser.add_argument("--config", required=True)
    arguments = parser.parse_args()
    controller = ReflectionRecoveryPipeline(arguments.config)
    result = (validate_recovered_bank(controller.config, controller.previous, controller.operations)
              if arguments.command == "validate" else controller.run() if arguments.command == "run" else controller.status())
    print(json.dumps(result))
