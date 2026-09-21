"""Revalidate every retained native proposal under a pinned offline scan correction.

No native process, repository command or grader is launched. The amended offline
verifier has its own source snapshot; the paired evaluator keeps the old solver.
"""
from pathlib import Path, PurePosixPath
import argparse
import json
import sys

sys.dont_write_bytecode = True
import trimem_skhynix_architecture_learning as learning
import trimem_skhynix_architecture_memory as memory
import trimem_skhynix_architecture_pipeline as core
import trimem_skhynix_architecture_publisher as publisher

RUNTIME_SCHEMA = "skhynix/offline-promotion-runtime/1.0"
REQUEST_SCHEMA = "skhynix/offline-promotion-revalidation-request/1.0"
REVISION_SCHEMA = "skhynix/offline-promotion-revalidation/1.0"
MANIFEST_SCHEMA = "skhynix/architecture-reflection-recovery/1.0"
CHANGED_PATH = "src/enterprise_memory/trimem/skill_memory.py"
EXPECTED_GROUPS = 4


def _fail(message):
    raise core.PipelineError(message)


def validate_runtime(reference, *, check_imports=False):
    value = core.check(reference)
    original = core.check(value["previous_execution_reference"])
    old_root, new_root = core.absolute(value["old_source_root"]), core.absolute(value["source_root"])
    before, after = value["old_source_sha256"], value["source_sha256"]
    if (value.get("schema") != RUNTIME_SCHEMA or value.get("changed_paths") != [CHANGED_PATH] or
            any(value.get(key) != 0 for key in ("model_calls", "solver_runs", "official_grader_runs")) or
            str(old_root) != original["source_root"] or before != original["source_sha256"] or
            set(before) != set(after) or old_root == new_root or old_root in new_root.parents or new_root in old_root.parents or
            sorted(key for key in before if before[key] != after[key]) != [CHANGED_PATH]):
        _fail("Offline promotion runtime must change only the reviewed typed-template scanner")
    for name in before:
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "__pycache__" in relative.parts:
            _fail("Offline promotion manifest must contain only original relative source paths")
        for root, mapping in ((old_root, before), (new_root, after)):
            core.check({"path": str(root / name), "sha256": mapping[name]}, decode=False)
    if not value.get("test_references"):
        _fail("Offline scanner revision requires retained verification tests")
    for test in value["test_references"]:
        core.check(test, decode=False)
    if check_imports:
        required = {"enterprise_memory.trimem.skill_memory", learning.__name__, memory.__name__, core.__name__, publisher.__name__}
        if not required <= set(sys.modules):
            _fail("Required offline promotion modules were not imported")
        for name, module in tuple(sys.modules.items()):
            if not (name.startswith("trimem_") or name == "enterprise_memory" or name.startswith("enterprise_memory.")):
                continue
            if name == __name__:
                continue  # Separately retained standalone driver, not solver code.
            filename = getattr(module, "__file__", None)
            if filename is None:
                continue
            path = core.absolute(filename)
            try:
                relative = path.relative_to(new_root).as_posix()
            except ValueError as exc:
                raise core.PipelineError("Offline verifier imported a module outside its amended frozen snapshot") from exc
            if after.get(relative) != core.ref(path)["sha256"]:
                _fail("Offline verifier module differs from the reviewed source bytes")
    return value


def _normalized(reference):
    path = reference["path"]
    result = {"path": str(core.absolute(path) if Path(path).is_absolute() else core.linux_path(path)), "sha256": reference["sha256"]}
    core.check(result, decode=False)
    return result


def _validate_inputs(request):
    expected = {"schema", "predecessor_manifest_reference", "clone_reference", "runtime_reference", "output_root", "bank_output"}
    if set(request) != expected or request["schema"] != REQUEST_SCHEMA:
        _fail("Offline revalidation requires its exact separately versioned request")
    old = core.check(request["predecessor_manifest_reference"])
    clone, old_clone = core.check(request["clone_reference"]), core.check(old["clone_reference"])
    previous = core.check(clone["predecessor_pipeline_reference"])
    runtime = validate_runtime(request["runtime_reference"], check_imports=True)
    if (old.get("schema") != MANIFEST_SCHEMA or old.get("status") not in {"READY", "NOT_READY"} or
            len(old.get("jobs", [])) != EXPECTED_GROUPS or old.get("proposed_group_count") != EXPECTED_GROUPS or
            old.get("promotion_revision_reference") is not None or
            any(old.get(key) is not False for key in ("outcome_retries", "official_outcomes_used", "gate_b_waived")) or
            clone.get("schema") != "skhynix/learning-authority-recovery/1.0" or
            clone["predecessor_pipeline_reference"] != old_clone["predecessor_pipeline_reference"] or
            clone["source_snapshot_references"] != old_clone["source_snapshot_references"] or
            clone["learning_enrollment_reference"]["sha256"] != old_clone["learning_enrollment_reference"]["sha256"] or
            clone["destination_root"] == old_clone["destination_root"] or
            runtime["previous_execution_reference"] != previous["training_experiment_reference"]):
        _fail("Revalidation must retain all original proposals and original captured source authority")
    root = core.absolute(clone["destination_root"])
    if any((root / name).exists() for name in ("frozen.json", "learning-frozen.json")):
        _fail("Revalidation needs a fresh unpublished clone")
    for group in (clone["source_snapshot_references"], clone["clone_initial_references"], clone["implementation_references"]):
        for ref in group.values():
            core.check(ref, decode=False)
    if core.read(root / "learning-state.json") != core.check(clone["clone_initial_references"]["learning-state.json"]):
        _fail("Fresh revalidation clone already has new reflections or cached ingestion outcomes")
    if core.ref(root / "catalog.json")["sha256"] != clone["clone_initial_references"]["catalog.json"]["sha256"]:
        _fail("Fresh revalidation clone catalog changed before verification")
    old_registry = core.read(Path(old_clone["destination_root"]) / "learning-state.json")
    template = core.check(previous["training_experiment_reference"])
    grouping = core.check(old["grouping_completion_reference"])
    response = core.check(_normalized(grouping["response_reference"]))
    mapping = core.check(old["grouping_map_reference"])
    if len(response["groups"]) != EXPECTED_GROUPS:
        _fail("All native-discovered groups must remain in the revalidation schedule")
    threads = {grouping["thread_id"]}
    for group, job in zip(response["groups"], old["jobs"]):
        if sorted(job["capture_ids"]) != sorted(mapping["candidates"][key]["capture_id"] for key in group["candidate_ids"]):
            _fail("Offline revalidation cannot change native-discovered group membership")
        config = core.check(job["configuration_reference"])
        if any(config.get(key) != template.get(key) for key in ("model", "reasoning_effort", "authentication", "codex_binary", "windows_python")):
            _fail("Retained publisher changed the original model/high/native configuration")
        proof = core.validate_native_publication(job["configuration_reference"], job["completion_reference"], job["launcher_reference"],
            reflection_reference=job["reflection_reference"], publisher_reference=previous["helper_references"]["publisher"], publisher_module=publisher)
        if proof != job["native_proof"] or proof["thread_id"] in threads:
            _fail("Retained native proposal evidence differs or repeats a worker")
        threads.add(proof["thread_id"])
        ingestion = core.check(job["ingestion_reference"])
        if (ingestion.get("proposal_reference") != proof["proposal_reference"] or
                ingestion.get("reflection_reference") != job["reflection_reference"] or
                job["ingestion_reference"] not in old_registry["ingestions"].values()):
            _fail("Original ingestion must remain retained with its exact native proposal")
    return old, clone, old_clone, old_registry


def run(request_path):
    request_path = core.absolute(request_path)
    request_ref, request = core.ref(request_path), core.read(request_path)
    driver_ref = core.ref(__file__)
    output, bank_output = core.absolute(request["output_root"]), core.absolute(request["bank_output"])
    if output.exists() or bank_output.exists():
        _fail("Offline revalidation output and bank must be fresh; previous attempts remain retained")
    old_path = Path(request["predecessor_manifest_reference"]["path"])
    with core.locked(old_path.parent / "recovery.lock"):
        old, clone, old_clone, old_registry = _validate_inputs(request)
        root = Path(clone["destination_root"])
        runtime = core.check(request["runtime_reference"])
        protected = [root, Path(old_clone["destination_root"]), old_path.parent,
            Path(core.check(clone["predecessor_pipeline_reference"])["pipeline_root"]),
            Path(runtime["old_source_root"]), Path(runtime["source_root"])]
        if any(path == item or item in path.parents or path in item.parents
               for path in (output, bank_output) for item in protected):
            _fail("Revalidation output must be separate from original authorities and frozen runtimes")
        output.mkdir(parents=True, exist_ok=False)
        core.retain(output / "request-binding.json", {"request_reference": request_ref, "driver_reference": driver_ref})
        original_state_ref = core.ref(Path(old_clone["destination_root"]) / "learning-state.json")
        with learning._session(root) as (_, enrollment, registry, _):
            available = learning._available_captures(root, registry)
            for job in old["jobs"]:
                registered = old_registry["reflections"][job["reflection_reference"]["sha256"]]
                public, mapping = core.check(registered["public"]), core.check(registered["private"])
                if (registered["public"] != job["reflection_reference"] or
                        public["publisher_map_sha256"] != memory._hash(mapping) or
                        mapping["enrollment_sha256"] != clone["learning_enrollment_reference"]["sha256"] or
                        sorted(row["capture_id"] for row in mapping["sources"].values()) != sorted(job["capture_ids"]) or
                        any(available[row["capture_id"]][0] != row["capture_reference"] for row in mapping["sources"].values())):
                    _fail("Revalidation projection changed its original alias mapping or capture evidence")
                retained = learning._retain_reflection(root, registry, public, mapping, Path(registered["public"]["path"]), 190000)
                if retained != job["reflection_reference"]:
                    _fail("Revalidation cannot regenerate or edit an original public reflection")
        jobs, pairs = [], []
        for index, old_job in enumerate(old["jobs"], 1):
            ingestion = learning.ingest_proposals(root, old_job["native_proof"]["proposal_reference"],
                                                 reflection_reference=old_job["reflection_reference"])
            job = {**old_job, "ingestion_reference": ingestion}
            jobs.append(job)
            pairs.append({"ordinal": index, "reflection_reference": job["reflection_reference"],
                "proposal_reference": job["native_proof"]["proposal_reference"],
                "old_ingestion_reference": old_job["ingestion_reference"], "new_ingestion_reference": ingestion})
            core.retain(output / ("group-" + str(index) + "-revalidation.json"), pairs[-1])
            print("REVALIDATED", index, "/", len(old["jobs"]), "promotions=", core.check(ingestion)["promotions_added"], flush=True)
        for ref in (request_ref, driver_ref, request["predecessor_manifest_reference"], original_state_ref, request["runtime_reference"]):
            core.check(ref, decode=False)
        validate_runtime(request["runtime_reference"], check_imports=True)
        revision = {"schema": REVISION_SCHEMA, "operation": "REVALIDATE_ALL_RETAINED_NATIVE_PROPOSALS_WITH_TYPED_TEMPLATE_SCAN",
            "request_reference": request_ref, "driver_reference": driver_ref, "runtime_reference": request["runtime_reference"],
            "predecessor_manifest_reference": request["predecessor_manifest_reference"], "clone_reference": request["clone_reference"],
            "predecessor_learning_state_reference": original_state_ref, "jobs": pairs,
            "model_calls": 0, "solver_runs": 0, "official_grader_runs": 0, "native_proposal_retries": 0,
            "red_edit_green_verifier_unchanged": True, "native_solver_runtime_unchanged": True,
            "verification_implementation_changed": "TYPED_PROCEDURE_PRIVACY_SCAN"}
        revision_ref = core.retain(output / "promotion-revision.json", revision)
        catalog = core.read(root / "catalog.json")
        ingestions = [core.check(job["ingestion_reference"]) for job in jobs]
        result = {**old, "request_reference": request_ref, "driver_reference": driver_ref, "clone_reference": request["clone_reference"],
            "jobs": jobs, "publication_reference": None, "promotion_revision_reference": revision_ref,
            "status": "NOT_READY", "L3_skills": len(catalog["skills"]), "model_calls": 0,
            "solver_runs": 0, "official_grader_runs": 0, "native_proposal_retries": 0}
        result.pop("reason", None)
        if any(item.get("status") != "PROCESSED" or item.get("failures") != [] for item in ingestions):
            result["reason"] = "INGESTION_VALIDATION_FAILURE"
        elif not catalog["skills"]:
            result["reason"] = "NO_VERIFIED_GATE_B_SKILL"
        else:
            published = learning.freeze_published_bank(root, bank_output)
            result.update(status="READY", publication_reference=published["publication_reference"])
        return core.retain(output / "reflection-recovery.json", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.request)))
