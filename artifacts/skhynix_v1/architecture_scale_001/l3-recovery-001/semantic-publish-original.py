"""Standalone reflection recovery over native-discovered TRAINING groups.

Invoke in a fresh Python -P process with the original frozen runtime on
PYTHONPATH. FrozenOperations is initialized before the separately hash-bound
projection producer is imported. This process has no evaluation entry point.
"""
import argparse
import importlib
import importlib.util
from pathlib import Path
import sys
import time


REQUEST_SCHEMA = "skhynix/architecture-semantic-publish-request/1.0"
SCHEMA = "skhynix/architecture-reflection-recovery/1.0"
REFERENCE_FIELDS = ("predecessor_pipeline_reference", "clone_reference", "grouping_completion_reference",
                    "grouping_input_reference", "grouping_map_reference", "projection_producer_reference")


def _fail(core, message):
    raise core.PipelineError(message)


def _normalized(core, reference):
    path = reference["path"]
    value = {"path": str(core.linux_path(path)) if str(path).lower().startswith("c:") else str(core.absolute(path)),
             "sha256": reference["sha256"]}
    core.check(value, decode=False)
    return value


def validate_inputs(core, request):
    required = {"schema", *REFERENCE_FIELDS, "output_root", "expected_group_count"}
    if set(request) != required or request["schema"] != REQUEST_SCHEMA or request["expected_group_count"] != 4:
        _fail(core, "Recovery request must bind the complete four-group offline experiment")
    output = core.absolute(request["output_root"])
    core.windows_path(output)
    previous = core.check(request["predecessor_pipeline_reference"])
    clone = core.check(request["clone_reference"])
    if (clone.get("schema") != "skhynix/learning-authority-recovery/1.0"
            or clone.get("operation") != "CLONE_COMPLETED_PUBLIC_LEARNING_FOR_REFLECTION"
            or clone.get("predecessor_pipeline_reference") != request["predecessor_pipeline_reference"]
            or clone.get("original_evidence_paths_preserved") is not True or clone.get("gate_b_waived") is not False
            or clone.get("counts", {}).get("training_sources") != 240 or clone["counts"].get("L3_skills") != 0
            or any(clone.get(key) != 0 for key in ("model_calls", "solver_runs", "official_grader_runs", "source_recaptures"))):
        _fail(core, "Recovery requires the unchanged completed 240-source clone")
    learning_root = core.absolute(clone["destination_root"])
    if Path(request["clone_reference"]["path"]) != learning_root / "learning-recovery.json":
        _fail(core, "Clone receipt is outside its declared learning root")
    if learning_root == core.absolute(clone["source_root"]):
        _fail(core, "Recovery cannot mutate the predecessor learning root")
    for field in ("source_snapshot_references", "clone_initial_references", "implementation_references"):
        for reference in clone[field].values():
            core.check(reference, decode=False)
    core.check(clone["learning_enrollment_reference"])
    core.check(request["projection_producer_reference"], decode=False)
    public = core.check(request["grouping_input_reference"])
    mapping = core.check(request["grouping_map_reference"])
    completion = core.check(request["grouping_completion_reference"])
    if (public.get("schema") != "skhynix/public-repair-grouping-input/1.0"
            or public.get("all_representative_candidates_included") is not True or public.get("official_outcomes_used") is not False
            or mapping.get("schema") != "skhynix/semantic-repair-grouping-map/1.0"
            or completion.get("schema") != "skhynix/semantic-grouping-completion/1.0"
            or completion.get("validation_required") is not True
            or any(completion.get(key) != 0 for key in ("memory_writes", "official_grader_runs", "separate_model_api_client_calls"))
            or _normalized(core, completion["input_reference"]) != request["grouping_input_reference"]):
        _fail(core, "Semantic discovery must bind all public training candidates without grading or memory writes")
    core.check(mapping["index_reference"])
    launch = core.check(_normalized(core, completion["launch_reference"]))
    if (launch.get("schema") != "skhynix/semantic-grouping-launch/1.0" or launch.get("fresh_session") is not True
            or launch.get("requested_model") != "gpt-6-astra" or launch.get("reasoning_effort") != "high"
            or _normalized(core, launch["input_reference"]) != request["grouping_input_reference"]):
        _fail(core, "Semantic discovery must retain its actual fresh Astra/high launch")
    # Hash-only binding of the discovery journal; never expose its transcript.
    event_path = Path(request["grouping_completion_reference"]["path"]).parent / "events.jsonl"
    if core.ref(event_path)["sha256"] != completion.get("events_sha256"):
        _fail(core, "Semantic discovery event evidence changed")
    response_reference = _normalized(core, completion["response_reference"])
    response = core.check(response_reference)
    if (set(response) != {"schema", "input_sha256", "groups", "ungrouped"}
            or response["schema"] != "skhynix/semantic-repair-grouping/1.0"
            or response["input_sha256"] != request["grouping_input_reference"]["sha256"]
            or len(response["groups"]) != request["expected_group_count"]):
        _fail(core, "Every actual native-discovered group must be retained in response order")
    candidates = {row["candidate_id"]: row for row in public["candidates"]}
    if len(candidates) != len(public["candidates"]) or set(candidates) != set(mapping["candidates"]):
        _fail(core, "Semantic candidate input and original-capture map differ")
    original = core.check(clone["source_snapshot_references"]["catalog.json"])
    for item in mapping["candidates"].values():
        if original["captures"].get(item["capture_id"]) != item["capture_reference"]:
            _fail(core, "Grouping map selects evidence outside the original training bank")
    covered = []
    for group in response["groups"]:
        if set(group) != {"candidate_ids", "shared_transformation", "applicability"}:
            _fail(core, "Unexpected native group fields")
        ids = group["candidate_ids"]
        if (not isinstance(ids, list) or len(ids) < 2 or len(set(ids)) != len(ids)
                or not set(ids) <= set(candidates)
                or any(not isinstance(group[key], str) or not group[key].strip() or len(group[key]) > 4000
                       for key in ("shared_transformation", "applicability"))):
            _fail(core, "Malformed native semantic group")
        entries = [mapping["candidates"][key] for key in ids]
        if min(len({item["task_id"] for item in entries}), len({item["owner_user_id"] for item in entries})) < 2:
            _fail(core, "Native group lacks independent original tasks and owners")
        if min(len({candidates[key][field] for key in ids}) for field in ("task_group", "contributor_group")) < 2:
            _fail(core, "Native group input aliases lack independence")
        covered.extend(ids)
    for row in response["ungrouped"]:
        if (set(row) != {"candidate_id", "reason_code", "evidence_note"}
                or row["reason_code"] not in {"NO_SEMANTIC_PARTNER", "INDEPENDENT_SUPPORT_MISSING", "INSUFFICIENT_CONTEXT"}):
            _fail(core, "Unexpected native ungrouped record")
        covered.append(row["candidate_id"])
    if len(set(covered)) != len(covered) or set(covered) != set(candidates):
        _fail(core, "Native grouping must account for every candidate exactly once")
    if completion.get("summary") != {"groups": len(response["groups"]),
            "grouped_candidates": sum(len(group["candidate_ids"]) for group in response["groups"]),
            "ungrouped_candidates": len(response["ungrouped"]), "verified_skills": 0}:
        _fail(core, "Grouping completion summary differs from the actual response")
    return previous, clone, mapping, response, response_reference


def import_projection(core, reference):
    path = core.check(reference, decode=False)
    # Deliberately outside the solver module namespace and only after frozen
    # runtime validation. Evaluation runs in a separate process.
    name = "_skhynix_offline_repair_window_projection"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    core.check(reference, decode=False)
    return module


def validate_grouping_native(core, request, response, operations):
    """Use the unchanged frozen publisher parser without exposing transcript text."""
    completion = core.check(request["grouping_completion_reference"])
    path = Path(request["grouping_completion_reference"]["path"]).parent / "events.jsonl"
    raw = path.read_bytes()
    if core.digest(raw) != completion.get("events_sha256"):
        _fail(core, "Semantic discovery native journal changed")
    events = [core.strict_json_loads(line) for line in raw.splitlines()]
    thread, text = operations.modules["publisher"].validate_events(events)
    if (thread != completion.get("thread_id") or core.strict_json_loads(text) != response
            or core.digest(text.encode()) != completion.get("response_text_sha256")):
        _fail(core, "Semantic discovery response is not the actual completed fresh native response")
    return {"thread_id": thread, "events_sha256": core.digest(raw),
        "response_text_sha256": core.digest(text.encode()),
        "completion_reference": request["grouping_completion_reference"]}


def _completed_manifest(core, path, request_reference, request, groups, mapping):
    value = core.read(path)
    if (value.get("schema") != SCHEMA or value.get("request_reference") != request_reference
            or value.get("status") not in {"READY", "NOT_READY"}
            or any(value.get(key) != request[key] for key in REFERENCE_FIELDS)
            or len(value.get("jobs", [])) != len(groups)):
        _fail(core, "Completed recovery differs from the immutable request")
    for group, job in zip(groups, value["jobs"]):
        expected = sorted(mapping["candidates"][key]["capture_id"] for key in group["candidate_ids"])
        if job["capture_ids"] != expected:
            _fail(core, "Completed recovery changed group membership")
        for key in ("reflection_reference", "configuration_reference", "completion_reference", "launcher_reference", "ingestion_reference"):
            core.check(job[key])
    if value.get("publication_reference") is not None:
        core.check(value["publication_reference"])
    return core.ref(path)


def execute(core, request, request_reference, operations, producer, clone, mapping, response, response_reference,
            *, grouping_native_proof=None):
    """Execute once per bound native group; injected operations enable offline tests."""
    output = core.absolute(request["output_root"])
    root = core.absolute(clone["destination_root"])
    learning = operations.modules["learning"]
    if grouping_native_proof is None:
        grouping_native_proof = validate_grouping_native(core, request, response, operations)
    output.mkdir(parents=True, exist_ok=True)
    with core.locked(output / "recovery.lock"):
        core.retain(output / "request-binding.json", {"schema": REQUEST_SCHEMA, "request_reference": request_reference,
            "driver_reference": core.ref(Path(__file__).resolve())})
        manifest_path = output / "reflection-recovery.json"
        if manifest_path.exists():
            return _completed_manifest(core, manifest_path, request_reference, request, response["groups"], mapping)
        if (output / "failure.json").exists():
            _fail(core, "Previous recovery infrastructure failure is retained; no automatic retry")
        try:
            return _execute_jobs(core, request, request_reference, operations, producer, clone, mapping,
                                 response, response_reference, output, root, learning, manifest_path, grouping_native_proof)
        except Exception as exc:
            core.retain(output / "failure.json", {"schema": "skhynix/semantic-publish-failure/1.0",
                "request_reference": request_reference, "error_type": type(exc).__name__, "reason": str(exc)[:2000],
                "at": time.time(), "retry": False, "outcome_retries": False})
            raise


def _execute_jobs(core, request, request_reference, operations, producer, clone, mapping,
                  response, response_reference, output, root, learning, manifest_path, grouping_native_proof):
    groups = response["groups"]
    jobs = []
    # All original available captures are loaded once for this projection pass.
    # The existing ingestion verifier independently validates source evidence.
    with learning._session(root) as (_, enrollment, registry, _):
        available = learning._available_captures(root, registry)
        for candidate in mapping["candidates"].values():
            item = available.get(candidate["capture_id"])
            if (item is None or item[0] != candidate["capture_reference"]
                    or item[1]["task"]["task_id"] != candidate["task_id"]
                    or item[1]["owner_user_id"] != candidate["owner_user_id"]):
                _fail(core, "Discovered candidate no longer matches original available TRAINING evidence")
        for index, group in enumerate(groups, 1):
            folder = output / f"group-{index:02d}"
            captures = sorted(mapping["candidates"][key]["capture_id"] for key in group["candidate_ids"])
            public, projection_map = producer.build_public_repair_windows(root, enrollment, available, captures)
            alias_by_capture = {row["capture_id"]: alias for alias, row in projection_map["sources"].items()}
            public["native_semantic_grouping"] = {"role": "UNTRUSTED_NATIVE_GROUPING_PROPOSAL_NOT_GATE_B_EVIDENCE",
                "response_reference": response_reference, "group_ordinal": index, "group": group,
                "candidate_source_aliases": {key: alias_by_capture[mapping["candidates"][key]["capture_id"]]
                                             for key in group["candidate_ids"]}}
            reflection_ref = learning._retain_reflection(root, registry, public, projection_map,
                folder / "public-reflection.json", 190000)
            jobs.append({"ordinal": index, "capture_ids": captures, "reflection_reference": reflection_ref})
    threads = set()
    for job in jobs:
        folder = output / f"group-{job['ordinal']:02d}"
        reflection_ref = job["reflection_reference"]
        config = {key: operations.training[key] for key in
                  ("model", "authentication", "reasoning_effort", "codex_binary", "windows_python")}
        if config["model"] != "gpt-6-astra" or config["reasoning_effort"] != "high" or config["authentication"] != "CHATGPT":
            _fail(core, "Reflection recovery must retain the original Astra/high/ChatGPT configuration")
        config.update(reflection_reference={"path": core.windows_path(reflection_ref["path"]), "sha256": reflection_ref["sha256"]},
            worker_output=core.windows_path(folder / "output"), worker_cwd=core.windows_path(folder / "cwd"))
        config_ref = core.retain(folder / "publisher-config.json", config)
        started = folder / "publish-started.json"
        launcher_path, completion_path = folder / "interop-completion.json", folder / "output/completion.json"
        if not started.exists():
            if launcher_path.exists() or (folder / "output").exists() or (folder / "cwd").exists() or (folder / "interop").exists():
                _fail(core, "Unbound pre-existing publisher output cannot be adopted")
            core.retain(started, {"request_reference": request_reference, "configuration_reference": config_ref,
                                 "reflection_reference": reflection_ref})
            operations.launch_publisher(config_ref, launcher_path)
        else:
            if core.read(started) != {"request_reference": request_reference, "configuration_reference": config_ref,
                                     "reflection_reference": reflection_ref}:
                _fail(core, "Publisher start differs from its immutable inputs")
            if not launcher_path.exists() or not completion_path.exists():
                _fail(core, "Started publisher has no durable completion; no automatic relaunch")
        launcher_ref, completion_ref = core.ref(launcher_path), core.ref(completion_path)
        proof = operations.validate_publisher(config_ref, completion_ref, launcher_ref, reflection_ref)
        if proof["thread_id"] in threads:
            _fail(core, "Recovery publishers reused a native thread")
        threads.add(proof["thread_id"])
        core.retain(folder / "native-proof.json", proof)
        ingest_started = folder / "ingest-started.json"
        identity = core.digest(core.canonical_bytes({"proposal": proof["proposal_reference"], "reflection": reflection_ref}))
        durable = root / "learning-ingestions" / (identity + ".json")
        ingest_binding = {"proposal_reference": proof["proposal_reference"], "reflection_reference": reflection_ref}
        if ingest_started.exists():
            if core.read(ingest_started) != ingest_binding or not durable.exists():
                _fail(core, "Interrupted ingestion lacks its exact durable receipt; no automatic replay")
            ingestion_ref = core.ref(durable)
        else:
            if durable.exists():
                _fail(core, "Unbound pre-existing recovery ingestion cannot be adopted")
            core.retain(ingest_started, ingest_binding)
            ingestion_ref = operations.ingest(root, proof["proposal_reference"], reflection_ref)
        ingestion = core.check(ingestion_ref)
        if any(ingestion.get(key) != value for key, value in ingest_binding.items()):
            _fail(core, "Ingestion receipt differs from actual native output")
        job.update(configuration_reference=config_ref, completion_reference=completion_ref,
            launcher_reference=launcher_ref, native_proof=proof, ingestion_reference=ingestion_ref)
        core.retain(folder / "job-complete.json", job)
        print(f"GROUP_COMPLETE {job['ordinal']}/{len(groups)} promotions={ingestion['promotions_added']} outcomes={len(ingestion['outcomes'])}", flush=True)
    catalog = core.read(root / "catalog.json")
    ingestions = [core.check(job["ingestion_reference"]) for job in jobs]
    driver_reference = core.read(output / "request-binding.json")["driver_reference"]
    core.check(driver_reference, decode=False)
    for field in REFERENCE_FIELDS:
        core.check(request[field], decode=False)
    result = {"schema": SCHEMA, "request_reference": request_reference,
        "driver_reference": driver_reference, "grouping_native_proof": grouping_native_proof,
        **{key: request[key] for key in REFERENCE_FIELDS}, "grouping_response_reference": response_reference,
        "status": "NOT_READY", "publication_reference": None, "jobs": jobs, "proposed_group_count": len(groups),
        "outcome_retries": False, "official_outcomes_used": False, "gate_b_waived": False,
        "native_solver_runtime_unchanged": True, "solver_runs": 0, "official_grader_runs": 0,
        "source_attempts": clone["counts"]["training_sources"], "L3_skills": len(catalog["skills"])}
    if any(row.get("status") != "PROCESSED" or row.get("failures") != [] for row in ingestions):
        result["reason"] = "INGESTION_VALIDATION_FAILURE"
    elif not catalog["skills"]:
        result["reason"] = "NO_VERIFIED_GATE_B_SKILL"
    else:
        frozen = root / "learning-frozen.json"
        if frozen.exists():
            publication_ref = core.read(frozen)
            publication = core.check(publication_ref)
            if publication.get("bank", {}).get("path") != str(output / "trained-bank.json"):
                _fail(core, "Recovered publication belongs to another output")
        else:
            bank = learning.freeze_published_bank(root, output / "trained-bank.json")
            publication_ref = bank["publication_reference"]
        result.update(status="READY", publication_reference=publication_ref)
    return core.retain(manifest_path, result)


def run(request_path):
    core = importlib.import_module("trimem_skhynix_architecture_pipeline")
    request_path = core.absolute(Path(request_path).resolve())
    request_reference, request = core.ref(request_path), core.read(request_path)
    previous, clone, mapping, response, response_reference = validate_inputs(core, request)
    operations = core.FrozenOperations(previous)
    grouping_proof = validate_grouping_native(core, request, response, operations)
    # Source identity was checked before importing any offline-only projection.
    producer = import_projection(core, request["projection_producer_reference"])
    return execute(core, request, request_reference, operations, producer, clone, mapping, response, response_reference,
                   grouping_native_proof=grouping_proof)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    arguments = parser.parse_args()
    import json
    print(json.dumps(run(arguments.request)))
