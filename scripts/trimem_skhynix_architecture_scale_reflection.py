"""Deterministic public procedure candidates and bounded reflection batches.

Observed action shapes propose which traces to compare; they certify no skill.
Only the unchanged learning verifier can admit an actual Gate B promotion.
No model, repository command, grader, or evaluation outcome is invoked or read.
"""
from collections import defaultdict
from pathlib import Path, PurePosixPath
import argparse
import json

from enterprise_memory.trimem.accounting import canonical_bytes
import trimem_skhynix_architecture_learning as learning
import trimem_skhynix_architecture_memory as memory

SCHEMA = "skhynix/architecture-scale-reflection-plan/1.0"
POLICY = "PUBLIC_RED_EDIT_GREEN_ACTION_SHAPES_EARLIEST_PER_TASK_THEN_DISTINCT_OWNER_BYTE_BOUNDED_BATCHES"


def _candidate(identity, capture, item):
    history = capture["history"]
    green = next((row for row in reversed(history) if row["tool"] in memory.MUTATING), None)
    if green is None or memory._test_outcome(green) != "GREEN" or green["active_node_id"] != capture["active_node_id"]:
        return None
    red = next((row for row in reversed(history) if row["step_no"] < green["step_no"] and
        row["active_node_id"] == capture["active_node_id"] and memory._test_outcome(row) == "RED" and
        memory._argv(row) == memory._argv(green)), None)
    if red is None:
        return None
    between = [row for row in history if red["step_no"] < row["step_no"] < green["step_no"]]
    edits = [row for row in between if row["tool"] in {"replace_text", "write_file"}]
    if not edits or any(row["tool"] == "run_command" for row in between):
        return None
    shape = []
    for row in edits:
        path = PurePosixPath(row["request_payload"]["arguments"]["path"])
        if (row["active_node_id"] != capture["active_node_id"] or
                any(part in {"tests", "test", "testing"} for part in path.parts) or
                path.name.startswith("test_") or path.name.endswith("_test.py")):
            return None
        shape.append([row["tool"], path.suffix])
    argv = memory._argv(green)
    runner = [PurePosixPath(argv[0]).name]
    if "-m" in argv[:3]:
        module_index = argv.index("-m") + 1
        runner.extend(["-m", argv[module_index]])
    signature = {"repository": capture["task"]["repository"], "test_runner": runner, "edit_shape": shape}
    return {"capture_id": identity, "task_id": capture["task"]["task_id"],
        "owner_user_id": capture["owner_user_id"], "repository": capture["task"]["repository"],
        "cutoff_step": item["checkpoint"]["cutoff_step"], "red_step": red["step_no"],
        "green_step": green["step_no"], "signature": signature,
        "signature_sha256": memory._hash(signature)}


def build_reflection_plan(learning_root, output_path, *, max_bytes=190000, max_sources_per_batch=8):
    """Freeze actual bounded exports plus jobs with ordinal/repository/job_id/capture_ids.

    Every enrolled source must already have a sealed observed attempt. A source
    with no public actions remains accounted for and creates no artificial
    candidate. Later stages use separate learning roots, independent of whether
    an earlier bank found a transferable procedure.
    """
    if type(max_bytes) is not int or not 1024 <= max_bytes <= 190000:
        raise learning.LearningError("Batch byte cap must leave room for the native reflection wrapper")
    if type(max_sources_per_batch) is not int or not 2 <= max_sources_per_batch <= 24:
        raise learning.LearningError("Reflection batches require 2 to 24 bounded source attempts")
    output = memory._path(output_path)
    with learning._session(learning_root) as (root, enrollment, registry, configs):
        available = learning._available_captures(root, registry)
        cells = sorted(registry["cells"].values(), key=lambda ref: ref["path"])
        receipts = [learning._checked_cell_receipt(ref) for ref in cells]
        attempted = {row.get("task_id") for row in receipts if row["status"] in {"CAPTURED", "NO_PUBLIC_ATTEMPTS"}
            and row.get("source_execution_observed")}
        if attempted != set(enrollment["training_tasks"]) or any(row["failures"] for row in receipts):
            raise learning.LearningError("Reflection planning requires actual validated attempts from every enrolled source")
        binding = {"enrollment_reference": memory._ref(root / "learning-enrollment.json"),
            "source_cell_references": cells, "source_capture_references": {key: value[0] for key, value in sorted(available.items())},
            "implementation_sha256": {"planner": memory._file_hash(__file__), "learning": memory._file_hash(learning.__file__)},
            "max_bytes": max_bytes, "max_sources_per_batch": max_sources_per_batch}
        if output.exists():
            prior = memory._read(output)
            if prior.get("schema") != SCHEMA or prior.get("policy") != POLICY or prior.get("binding") != binding:
                raise learning.LearningError("Existing reflection plan differs from its exact source snapshot or policy")
            for job in prior["jobs"]:
                learning._reference(job["reflection_reference"])
                registered = registry["reflections"].get(job["reflection_reference"]["sha256"])
                if registered is None or registered["public"] != job["reflection_reference"]:
                    raise learning.LearningError("Frozen batch export is not registered in this authority")
                learning._reference(registered["private"])
            return memory._ref(output)
        groups, skipped, representatives = defaultdict(list), [], {}
        for identity, (_, capture, item, _) in sorted(available.items()):
            candidate = _candidate(identity, capture, item)
            if candidate is None:
                skipped.append({"capture_id": identity, "reason": "NO_PUBLIC_RED_EDIT_GREEN_CANDIDATE"})
                continue
            key = candidate["signature_sha256"], candidate["task_id"]
            previous = representatives.get(key)
            if previous is None or (candidate["cutoff_step"], identity) < (previous["cutoff_step"], previous["capture_id"]):
                if previous:
                    skipped.append({"capture_id": previous["capture_id"], "reason": "LATER_DUPLICATE_TASK_ACTION_SHAPE"})
                representatives[key] = candidate
            else:
                skipped.append({"capture_id": identity, "reason": "LATER_DUPLICATE_TASK_ACTION_SHAPE"})
        for (signature, _), candidate in sorted(representatives.items()):
            groups[signature].append(candidate)
        jobs, planned = [], []
        for signature, group in sorted(groups.items()):
            group.sort(key=lambda row: (row["task_id"], row["cutoff_step"], row["capture_id"]))
            if len({row["owner_user_id"] for row in group}) < 2:
                skipped.extend({"capture_id": row["capture_id"], "reason": "INSUFFICIENT_INDEPENDENT_OWNERS_FOR_ACTION_SHAPE"} for row in group)
                continue
            pending = list(group)
            def documents(rows):
                ids = sorted(row["capture_id"] for row in rows)
                public, mapping = learning._reflection_documents(root, enrollment, available, ids)
                return public, mapping, len(canonical_bytes(public)) + 1
            while pending:
                seed = pending.pop(0)
                partners = [row for row in pending if row["owner_user_id"] != seed["owner_user_id"]]
                partners += [row for row in group if row not in pending and row["owner_user_id"] != seed["owner_user_id"]]
                partner = next((row for row in partners if documents([seed, row])[2] <= max_bytes), None)
                if partner is None:
                    skipped.append({"capture_id": seed["capture_id"], "reason": "NO_INDEPENDENT_PAIR_FITS_EXACT_CONTEXT_CAP"})
                    continue
                selected = [seed, partner]
                if partner in pending:
                    pending.remove(partner)
                for row in list(pending):
                    if len(selected) == max_sources_per_batch:
                        break
                    if documents(selected + [row])[2] <= max_bytes:
                        selected.append(row)
                        pending.remove(row)
                public, mapping, size = documents(selected)
                ids = sorted(row["capture_id"] for row in selected)
                job_id = "batch-" + memory._hash({"enrollment_sha256": binding["enrollment_reference"]["sha256"],
                    "signature": signature, "capture_ids": ids})[:24]
                ordinal = len(planned) + 1
                path = output.parent / (output.stem + "-exports") / (job_id + ".json")
                planned.append((public, mapping, path))
                jobs.append({"ordinal": ordinal, "repository": seed["repository"], "job_id": job_id,
                    "status": "READY", "capture_ids": ids, "signature": seed["signature"],
                    "signature_sha256": signature, "public_bytes": size,
                    "independent_tasks": len({row["task_id"] for row in selected}),
                    "independent_owners": len({row["owner_user_id"] for row in selected})})
        for job, (public, mapping, path) in zip(jobs, planned):
            job["reflection_reference"] = learning._retain_reflection(root, registry, public, mapping, path, max_bytes)
        value = {"schema": SCHEMA, "policy": POLICY, "binding": binding,
            "status": "READY" if jobs else "NO_REPEAT_PROCEDURE_CANDIDATES", "jobs": jobs,
            "skipped_candidates": sorted(skipped, key=lambda row: (row["capture_id"], row["reason"])),
            "all_original_captures_retained": True, "official_outcomes_used": False,
            "candidate_shapes_are_verification": False, "gate_b_promotions": 0,
            "model_calls": 0, "official_grader_runs": 0}
        memory._write(output, value, fresh=True)
        return memory._ref(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--learning-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-bytes", type=int, default=190000)
    parser.add_argument("--max-sources-per-batch", type=int, default=8)
    arguments = parser.parse_args()
    print(json.dumps(build_reflection_plan(arguments.learning_root, arguments.output,
        max_bytes=arguments.max_bytes, max_sources_per_batch=arguments.max_sources_per_batch)))
