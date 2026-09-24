"""Freeze a new scale runtime/configuration without replacing pilot evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import trimem_skhynix_host_profile as host_profile


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def read(path):
    return json.loads(Path(path).read_bytes())


def reference(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def retain(path, value):
    raw = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Setup refuses to change frozen bytes: " + str(path))
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return reference(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--dataset-24", required=True)
    parser.add_argument("--dataset-120", required=True)
    parser.add_argument("--dataset-240", required=True)
    parser.add_argument("--image-index", required=True)
    parser.add_argument("--version", type=int, required=True)
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    config_root = repo / "configs/skhynix_v1"
    old_path = config_root / "architecture_001_training_execution_v6.json"
    old = read(old_path)
    original_source = Path(old["source_root"])
    temp = host_profile.staging_root()
    source = temp / ("skhynix-architecture-scale-001-source-v" + str(args.version))
    source.mkdir(exist_ok=False)
    hashes = dict(old["source_sha256"])
    for name, expected in hashes.items():
        raw = (original_source / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("Pilot runtime bytes changed")
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    changed = ["scripts/trimem_skhynix_architecture_" + name + ".py" for name in
               ("dataset", "run", "cohort", "learning", "quarantine", "cleanup", "publisher", "pipeline", "progress",
                "scale_dataset", "scale_reflection", "scale_pipeline", "scale_registry", "scale_setup")]
    for name in changed:
        raw = (repo / name).read_bytes()
        (source / name).write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    # Every helper import and lazy official entrypoint now resolves to the same
    # new snapshot. Original configurations/source roots remain untouched.
    sys.path[:0] = [str(source / "scripts"), str(source / "src")]
    import trimem_skhynix_architecture_run as execution
    import trimem_skhynix_architecture_scale_dataset as dataset
    import trimem_skhynix_architecture_scale_pipeline as controller
    from trimem_harness_lock import prepare_harnesses
    from trimem_official_harness_loader_preflight import run_official_harness_loader_preflight
    import trimem_benchmark_run as benchmark
    run_root = host_profile.run_root()
    registry = read(args.image_index)
    protocol = read(args.protocol)
    targets = protocol["targets"]
    if {row["instance_id"] for row in registry["rows"]} != {row["instance_id"] for row in targets}:
        raise ValueError("Image inventory differs from final frozen public selection")
    if any(row["status"] != "AVAILABLE" for row in registry["rows"]):
        raise ValueError("Selected image missing; no availability-driven task replacement")
    harnesses = prepare_harnesses(Path(old["harness_root"]))
    preflight = run_official_harness_loader_preflight(python_binary=sys.executable,
        swe_harness_root=harnesses["swebench_verified"], multi_harness_root=harnesses["multi_swe_bench_mini"])
    preflight = benchmark.validate_official_harness_loader_preflight_evidence(preflight)
    loader = retain(run_root / ("preflight/official-harness-loader-v" + str(args.version) + ".json"), preflight)
    adoption = reference(repo / "artifacts/skhynix_v1/architecture_scale_001/source-adoption-002.json")
    owners = dict(old["training_owner_by_instance"])
    counts = {}
    for target in targets:
        if target["role"] != "TRAINING":
            continue
        name = target["repository"]
        rank = counts.get(name, 0)
        counts[name] = rank + 1
        owners.setdefault(target["instance_id"], rank % 2 + 1)
    stages = []
    for size in controller.SIZES:
        dataset_path = Path(getattr(args, "dataset_" + str(size))).resolve()
        manifest = dataset.validate_scale_manifest(read(dataset_path))
        if manifest["protocol_reference"] != reference(args.protocol):
            raise ValueError("Stage dataset has a different selection authority")
        dataset_ref = reference(dataset_path)
        purpose = "TRAINING_REMAINDER_24" if size == 24 else "TRAINING_INCREMENT"
        folder = run_root / ("training-" + str(size) + "-v" + str(args.version))
        authority = execution.create_execution_enrollment(folder / "execution-authority.json",
            dataset_reference=dataset_ref, purpose=purpose,
            source_adoption_reference=adoption if size == 24 else None)
        value = {**old, "source_root": str(source), "source_sha256": hashes,
            "run_root": str(folder), "native_control_root": str(temp / ("skhynix-architecture-scale-001-native-v" + str(args.version)) / ("training-" + str(size))),
            "dataset_manifest": dataset_ref, "image_index": reference(args.image_index),
            "loader_preflight_path": loader["path"], "loader_preflight_sha256": loader["sha256"],
            "training_owner_by_instance": {row["instance_id"]: owners[row["instance_id"]] for row in manifest["targets"] if row["role"] == "TRAINING"},
            "scale_authority_reference": authority,
            "prelaunch_revision": {"previous_configuration_reference": reference(old_path),
                "reason": "User-approved nested24/120/240 memory collection, separate60development, locked500final. Reuse sealed pilot attempts without re-solving.",
                "native_outcome_retries": False, "original_pilot_evidence_preserved": True}}
        value.pop("exclusion_references", None)
        path = config_root / ("architecture_002_training_" + str(size) + "_v" + str(args.version) + ".json")
        config_ref = controller.write_execution(path, value)
        execution.load_experiment(path)
        stages.append({"size": size, "execution_reference": config_ref})
    configuration = {"schema": controller.SCHEMA, "selection_policy": controller.SELECTION_POLICY,
        "outcome_retries": False, "pipeline_source_reference": reference(source / "scripts/trimem_skhynix_architecture_scale_pipeline.py"),
        "training_experiment_reference": stages[0]["execution_reference"], "training_stages": stages,
        "protocol_reference": reference(args.protocol), "source_adoption_reference": adoption,
        "reflection_source_reference": reference(source / "scripts/trimem_skhynix_architecture_scale_reflection.py"),
        "helper_references": {name: reference(source / ("scripts/trimem_skhynix_architecture_" + name + ".py"))
            for name in ("cohort", "learning", "publisher", "progress", "quarantine", "cleanup")},
        "pipeline_root": str(run_root / ("pipeline-v" + str(args.version))),
        "progress_root": str(repo / "artifacts/skhynix_v1/architecture_scale_001"),
        "reflection_native_root": str(temp / ("skhynix-architecture-scale-001-reflection-v" + str(args.version))),
        "evaluation_native_root": str(temp / ("skhynix-architecture-scale-001-evaluation-v" + str(args.version))),
        "reflection_max_bytes": 190000, "adopted_reflections": []}
    controller.validate_config(configuration, executing_source=source / "scripts/trimem_skhynix_architecture_scale_pipeline.py")
    path = config_root / ("architecture_002_pipeline_v" + str(args.version) + ".json")
    result = controller.write_execution(path, configuration)
    retain(run_root / ("preflight/runtime-freeze-v" + str(args.version) + ".json"), {
        "configuration_reference": result, "source_file_count": len(hashes), "loader_reference": loader,
        "model_calls": 0, "official_grader_runs": 0, "stage_new_source_counts": [6, 96, 120]})
    print(json.dumps({"configuration_reference": result, "source_root": str(source), "source_file_count": len(hashes),
        "loader_preflight": "PASS", "new_training_tasks": 222, "preserved_source_attempts": 18,
        "model_calls": 0, "official_grader_runs": 0}))


if __name__ == "__main__":
    main()
