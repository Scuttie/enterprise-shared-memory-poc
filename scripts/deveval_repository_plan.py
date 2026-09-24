"""Metadata-only, deterministic repository-local DevEval pilot enrollment.

No model or grader is called. Task/test/source bodies are never printed. Public
repository context must be materialized separately after masking every enrolled
benchmark target in each repository, not merely this pilot's selected targets.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
from itertools import combinations
import json
from pathlib import Path

import deveval_prepare as assets

SCHEMA = "deveval/repository-plan/1"
SEED = "deveval-repository-private-memory-pilot-002"
PROJECTS = ("Internet/pyramid", "Multimedia/mingus", "System/mrjob")
PHASE_QUOTAS = {"DISCOVERY": 4, "VERIFICATION": 2, "VALID": 2, "TEST": 2}
PHASE_SELECTION_ORDER = ("VALID", "TEST", "VERIFICATION", "DISCOVERY")
ARMS = {
    "OFF": [], "L1_ONLY": ["L1"], "NO_L2": ["L1", "L3"],
    "NO_L3": ["L1", "L2"], "FULL": ["L1", "L2", "L3"],
}
CANONICAL_ARMS = tuple(ARMS)


def require(value, code):
    if not value:
        raise ValueError(code)


def digest(value):
    return hashlib.sha256(assets.canonical(value)).hexdigest()


def ranked(*parts):
    return hashlib.sha256("\0".join((SEED, *parts)).encode("utf-8")).hexdigest()


def portable_reference(path, repository_root):
    path, repository_root = Path(path).resolve(), Path(repository_root).resolve()
    require(path.is_relative_to(repository_root), "REFERENCE_OUTSIDE_REPOSITORY")
    return {"path": path.relative_to(repository_root).as_posix(), "sha256": assets.file_sha(path), "bytes": path.stat().st_size}


def metadata_rows(path):
    rows = [json.loads(line) for line in Path(path).read_bytes().splitlines() if line.strip()]
    require(len(rows) == 1825 and len({r["namespace"] for r in rows}) == 1825, "OFFICIAL_METADATA_ENROLLMENT_CHANGED")
    return rows


def check_rows(rows):
    require(len({r["namespace"] for r in rows}) == len(rows), "DUPLICATE_TASK_ID")
    for row in rows:
        for key in ("namespace", "project_path", "completion_path", "type"):
            require(isinstance(row.get(key), str) and row[key], "INVALID_METADATA_IDENTITY")
        project = assets.safe_relative(row["project_path"])
        source = assets.safe_relative(row["completion_path"])
        require(source.parts[:len(project.parts)] == project.parts and len(source.parts) > len(project.parts), "SOURCE_OUTSIDE_PROJECT")
        require(row["type"] in ("function", "method"), "UNKNOWN_TARGET_TYPE")
        for name in ("signature_position", "body_position"):
            span = row.get(name)
            require(isinstance(span, list) and len(span) == 2 and all(type(n) is int and n > 0 for n in span) and span[0] <= span[1], "INVALID_SOURCE_SPAN")
        require(row["signature_position"][1] < row["body_position"][0], "SIGNATURE_BODY_OVERLAP")
        require(isinstance(row.get("requirement"), dict) and set(row["requirement"]) == {"Functionality", "Arguments"} and
                all(isinstance(v, str) for v in row["requirement"].values()), "INVALID_PUBLIC_REQUIREMENT")
        require(isinstance(row.get("tests"), list) and all(isinstance(v, str) for v in row["tests"]), "INVALID_PRIVATE_TEST_SELECTORS")
        require(isinstance(row.get("dependency"), dict) and set(row["dependency"]) == {"intra_class", "intra_file", "cross_file"} and
                all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in row["dependency"].values()), "INVALID_DECLARED_DEPENDENCIES")


def eligible_groups(rows, projects):
    """Group by source file and exact public requirement; cross-repo clones excluded."""
    eligible = [r for r in rows if r["project_path"] in projects and r["tests"] and r["dependency"]["cross_file"]]
    parent = {}

    def find(key):
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)

    requirement_files = {}
    for row in eligible:
        file_id = row["completion_path"]
        find(file_id)
        instruction = digest(row["requirement"])
        if instruction in requirement_files:
            union(file_id, requirement_files[instruction])
        else:
            requirement_files[instruction] = file_id
    grouped = defaultdict(list)
    for row in eligible:
        grouped[find(row["completion_path"])].append(row)
    per_project, excluded = defaultdict(list), []
    for group in grouped.values():
        member_projects = {r["project_path"] for r in group}
        identity = digest(sorted({r["completion_path"] for r in group}))
        if len(member_projects) != 1:
            excluded.extend(r["namespace"] for r in group)
            continue
        project = next(iter(member_projects))
        per_project[project].append({"id": identity, "rows": group})
    for project in per_project:
        per_project[project].sort(key=lambda group: ranked(project, "file-group", group["id"]))
    return per_project, sorted(excluded)


def partition_project(groups, quotas):
    """First deterministic feasible whole-group phase assignment, exact task quota."""
    phases = tuple(p for p in PHASE_SELECTION_ORDER if quotas.get(p, 0))

    def search(index, available):
        if index == len(phases):
            return {}
        phase, needed = phases[index], quotas[phases[index]]
        for group_count in range(1, min(needed, len(available)) + 1):
            for indices in combinations(range(len(available)), group_count):
                chosen = [available[i] for i in indices]
                capacity = sum(len(g["rows"]) for g in chosen)
                if capacity < needed or any(capacity-len(g["rows"]) >= needed for g in chosen):
                    continue
                remaining = [g for i,g in enumerate(available) if i not in indices]
                if len(remaining) < len(phases)-index-1:
                    continue
                suffix = search(index+1, remaining)
                if suffix is not None:
                    ranked_rows = sorted(((r, g["id"]) for g in chosen for r in g["rows"]),
                                         key=lambda pair: ranked(phase, pair[0]["namespace"]))
                    return {phase: ranked_rows[:needed], **suffix}
        return None

    selected = search(0, list(groups))
    require(selected is not None, "NO_FILE_DISJOINT_PHASE_ASSIGNMENT")
    return selected


def descriptor(row, phase, group_id):
    return {"task_id": row["namespace"], "project": row["project_path"], "phase": phase,
            "metadata_row_sha256": digest(row), "public_requirement_sha256": digest(row["requirement"]),
            "completion_path_sha256": hashlib.sha256(row["completion_path"].encode()).hexdigest(),
            "file_group_id": group_id, "task_type": row["type"], "private_test_selector_count": len(row["tests"]),
            "declared_dependency_counts": {key: len(value) for key,value in row["dependency"].items()}}


def build_plan(rows, *, metadata_reference, source_archive_reference, projects=PROJECTS, quotas=PHASE_QUOTAS):
    check_rows(rows)
    projects = tuple(projects)
    require(len(set(projects)) == len(projects) and not set(projects) & set(assets.PROJECTS), "CONTROL_PROJECT_REUSE_FORBIDDEN")
    require(set(quotas) == set(PHASE_QUOTAS) and all(type(n) is int and n > 0 for n in quotas.values()), "INVALID_PHASE_QUOTAS")
    grouped, excluded = eligible_groups(rows, projects)
    tasks, project_rows = [], []
    target_names = {r["namespace"] for r in rows}
    for project in projects:
        all_project = [r for r in rows if r["project_path"] == project]
        require(all_project, "UNKNOWN_PROJECT")
        chosen = partition_project(grouped[project], quotas)
        tasks.extend(descriptor(row, phase, identity) for phase in PHASE_QUOTAS for row,identity in chosen[phase])
        selected_rows = [row for pairs in chosen.values() for row,_ in pairs]
        dep_counts = Counter("also_benchmark_target" if dep in target_names else "not_benchmark_target"
                             for row in selected_rows for dep in row["dependency"]["cross_file"])
        project_rows.append({"project": project, "all_benchmark_target_count": len(all_project),
            "all_benchmark_target_metadata_sha256": digest(sorted([digest(r) for r in all_project])),
            "all_benchmark_source_file_count": len({r["completion_path"] for r in all_project}),
            "cross_file_eligible_count": sum(bool(r["tests"] and r["dependency"]["cross_file"]) for r in all_project),
            "file_instruction_group_count": len(grouped[project]), "phase_task_counts": dict(quotas),
            "selected_declared_cross_file_dependency_target_overlap": dict(dep_counts),
            "remaining_resolved_visible_cross_file_calls": None,
            "context_audit_status": "PENDING_SANITIZED_AST_EXTRACTION"})
    tasks.sort(key=lambda row: (tuple(PHASE_QUOTAS).index(row["phase"]), ranked(row["phase"], row["task_id"])))
    target_schedule = []
    for phase in ("VALID", "TEST"):
        phase_tasks = [r for r in tasks if r["phase"] == phase]
        for position in range(len(CANONICAL_ARMS)):
            for index, task in enumerate(phase_tasks):
                arm = CANONICAL_ARMS[(position+index) % len(CANONICAL_ARMS)]
                target_schedule.append({"launch_ordinal": len(target_schedule)+1, "task_id": task["task_id"],
                    "project": task["project"], "phase": phase, "arm": arm, "repeat": 1})
    source_schedule = [{"launch_ordinal": i+1, "task_id": task["task_id"], "project": task["project"], "phase": task["phase"], "arm": "SOURCE"}
                       for i,task in enumerate(t for t in tasks if t["phase"] in ("DISCOVERY", "VERIFICATION"))]
    return {"schema": SCHEMA, "experiment_id": "deveval_002", "status": "TASKS_FROZEN_RUNTIME_AND_CONTEXT_AUDIT_PENDING",
        "reference_path_base": "repository_root", "seed": SEED, "selection_uses_model_outcomes": False,
        "github_commit": assets.GITHUB_COMMIT, "hf_commit": assets.HF_COMMIT,
        "metadata_reference": metadata_reference, "source_archive_reference": source_archive_reference,
        "projects": project_rows, "tasks": tasks, "phase_task_counts": dict(Counter(r["phase"] for r in tasks)),
        "all_project_targets_to_mask": sum(r["all_benchmark_target_count"] for r in project_rows),
        "cross_repository_exact_requirement_clone_exclusions": excluded,
        "source_schedule": source_schedule, "target_schedule": target_schedule,
        "arms": ARMS, "repeats": 1, "model_sessions_planned": len(source_schedule)+len(target_schedule),
        "model": {"provider": "native_codex", "model": "gpt-5.6-luna", "reasoning_effort": "low", "glm_calls": 0},
        "budgets": {"task_seconds": 600, "tool_actions": 24, "generated_test_runs": 4, "native_sessions": 4,
                    "max_workers": 2, "parallel_same_task_forbidden": True, "parallel_same_working_repository_forbidden": True},
        "scope": {"repository_identity_shared_across_phases": True, "completion_file_disjoint_between_phases": True,
                  "exact_public_requirement_disjoint_between_phases": True, "repo_held_out_generalization_claim": False,
                  "validation_and_test_bank_writes": False, "validation_outcomes_may_change_test_policy": False,
                  "control_repositories_excluded": list(assets.PROJECTS), "same_owner_private_only": True,
                  "legacy_lcb_bank_retagging_forbidden": True},
        "visibility": {"policy_revision": 2, "mask_all_project_benchmark_target_bodies": True,
                       "remove_tests_fixtures_vcs_noncode": True,
                       "exclude_examples_docs_setup_except_masked_benchmark_target_source": True,
                       "benchmark_source_exception_never_applies_to_private_test_fixture_or_selector_files": True,
                       "l2_extracted_after_masking_only": True, "official_dependency_annotations_model_visible": False,
                       "all_arms_same_public_snapshot_and_read_api": True, "generated_execution_sanitized_only": True,
                       "private_grading_after_all_target_solves": True, "grader_output_to_bank": False},
        "l3_policy": {"claim": "OBSERVED_TESTING_WORKFLOW_NOT_ALGORITHM_OR_ORACLE_CORRECTNESS",
                      "public_test_oracle_available": False, "oracle_scope": "MODEL_GENERATED_EXPECTATIONS",
                      "discovery": "ACTUAL_ASSERTION_RED_CHANGED_CANDIDATE_EXACT_SAME_GENERATED_TEST_SCRIPT_GREEN_FINAL_CANDIDATE_MATCHES_GREEN_LESSON_ANCHORS_BOTH",
                      "verification": "FILE_DISJOINT_TRAIN_TASK_PREASSIGNED_PROCEDURE_ID_ACTUALLY_INVOKED_SAME_DECLARED_METHOD_ID_GENERATED_TEST_SCRIPT_GREEN_ON_FINAL_CANDIDATE",
                      "artificial_red_prohibited": True, "official_public_green_claim": False,
                      "zero_skills_blocks_l2_evaluation": False, "zero_skills_full_equivalent_to_no_l3": True,
                      "comparison_requires_actual_l3_exposure": True},
        "memory_protocol": {"l0": "ShortTermWorkingGraph", "max_subtasks": 3,
                            "layer_priority": ["L3", "L2", "L1"], "units_per_active_node": 1,
                            "total_injection_bytes": 12000, "disabled_layers_skipped": True,
                            "actual_exposure_required_in_report": True, "l2_snapshot_revision_must_match": True},
        "admission": {"all_selected_native_reference_controls_required": True, "negative_controls_required": True,
                      "environment_failure_policy": "BLOCK_SAME_FROZEN_COHORT_NO_SUBSTITUTION",
                      "context_hash_and_masking_audit_required": True, "l2_visible_relation_coverage_required": True,
                      "reference_control_observations_are_not_model_scores": True},
        "metrics": {"primary": "ACCEPTED_SUBMISSION_AND_OFFICIAL_PRIVATE_PASS",
                    "secondary": ["SUBMISSION_RATE", "ACTUAL_LAYER_EXPOSURE", "ALL_ATTEMPT_SECONDS", "TOKEN_AND_TOOL_USE"],
                    "generation_failure_resolved": False, "unknown_infrastructure_resolved": None,
                    "analysis": "PAIRED_TASK_DESCRIPTIVE_AND_REPO_STRATIFIED_TINY_PILOT",
                    "valid_test_report_separate": True, "unavailable_and_infrastructure_counts_retained": True}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.repository_root.resolve()
    metadata = root/"data/deveval_001/upstream/data.jsonl"
    archive = root/"data/deveval_001/Source_Code.tar.gz"
    require(assets.file_sha(archive) == assets.SOURCE_SHA256 and archive.stat().st_size == assets.SOURCE_BYTES, "SOURCE_ARCHIVE_CHANGED")
    # The official data member is independently pinned by the downloaded archive.
    import tarfile
    data_archive = metadata.parent/"data.tar.gz"
    require(assets.file_sha(data_archive) == assets.UPSTREAM_FILES["data.tar.gz"], "OFFICIAL_METADATA_ARCHIVE_CHANGED")
    with tarfile.open(data_archive, "r:gz") as source:
        require(source.extractfile("data.jsonl").read() == metadata.read_bytes(), "OFFICIAL_METADATA_MEMBER_CHANGED")
    plan = build_plan(metadata_rows(metadata), metadata_reference=portable_reference(metadata, root),
                      source_archive_reference=portable_reference(archive, root))
    plan["planner_reference"] = portable_reference(__file__, root)
    plan["asset_helper_reference"] = portable_reference(Path(assets.__file__), root)
    output = args.output or root/"configs/skhynix_v1/deveval_002_plan.json"
    assets.write_new(output, plan)
    print(json.dumps({"status": plan["status"], "reference": portable_reference(output, root),
        "projects": [p["project"] for p in plan["projects"]], "phase_task_counts": plan["phase_task_counts"],
        "model_sessions_planned": plan["model_sessions_planned"], "all_project_targets_to_mask": plan["all_project_targets_to_mask"]}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "ERROR", "exception_type": type(error).__name__}))
        raise SystemExit(1)
