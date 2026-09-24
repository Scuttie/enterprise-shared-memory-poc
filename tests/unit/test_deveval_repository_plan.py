"""Synthetic metadata only: no model, hidden payload, or evaluator calls."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"scripts"))
import deveval_repository_plan as plan


def rows():
    result = []
    for project in plan.PROJECTS:
        for file_index in range(6):
            for task_index in range(3):
                identity = f"{project}.module{file_index}.function{task_index}"
                result.append({"namespace": identity, "project_path": project,
                    "completion_path": f"{project}/module{file_index}.py", "type": "function",
                    "signature_position": [task_index*5+1, task_index*5+1],
                    "body_position": [task_index*5+2, task_index*5+4], "indent": 4,
                    "dependency": {"intra_class": [], "intra_file": [], "cross_file": ["synthetic.other.helper"]},
                    "tests": ["SYNTHETIC_PRIVATE_SELECTOR_DO_NOT_EXPORT"],
                    "requirement": {"Functionality": "SYNTHETIC_TASK_TEXT_DO_NOT_EXPORT_"+identity, "Arguments": "opaque"}})
    return result


def build(data):
    return plan.build_plan(data, metadata_reference={"path": "data/meta", "sha256": "a"*64, "bytes": 1},
                           source_archive_reference={"path": "data/archive", "sha256": "b"*64, "bytes": 1})


def assignments(value):
    return [(row["task_id"], row["phase"]) for row in value["tasks"]]


def test_fixed_enrollment_does_not_use_input_order_or_outcome_fields():
    original = rows()
    changed = deepcopy(original[::-1])
    for index,row in enumerate(changed):
        row["unrelated_model_outcome"] = index % 2
    assert assignments(build(original)) == assignments(build(changed))


def test_exact_phase_counts_file_and_requirement_disjoint():
    result = build(rows())
    assert result["phase_task_counts"] == {"DISCOVERY": 12, "VERIFICATION": 6, "VALID": 6, "TEST": 6}
    assert result["model_sessions_planned"] == 78
    phase_by_file, phase_by_requirement = {}, {}
    for task in result["tasks"]:
        for mapping,key in ((phase_by_file, "completion_path_sha256"), (phase_by_requirement, "public_requirement_sha256")):
            assert mapping.setdefault(task[key], task["phase"]) == task["phase"]


def test_all_target_bodies_masked_including_unselected_and_no_payload_export():
    data = rows()
    result = build(data)
    assert result["all_project_targets_to_mask"] == len(data) > len(result["tasks"])
    serialized = json.dumps(result)
    assert "SYNTHETIC_TASK_TEXT_DO_NOT_EXPORT" not in serialized
    assert "SYNTHETIC_PRIVATE_SELECTOR_DO_NOT_EXPORT" not in serialized
    assert result["visibility"]["official_dependency_annotations_model_visible"] is False
    assert result["visibility"]["l2_extracted_after_masking_only"] is True
    assert result["visibility"]["exclude_examples_docs_setup_except_masked_benchmark_target_source"] is True
    assert result["visibility"]["benchmark_source_exception_never_applies_to_private_test_fixture_or_selector_files"] is True


def test_every_target_gets_all_five_arms_once_and_valid_test_remain_separate():
    result = build(rows())
    scheduled = result["target_schedule"]
    assert [r["launch_ordinal"] for r in scheduled] == list(range(1,61))
    assert Counter(r["phase"] for r in scheduled) == {"VALID":30, "TEST":30}
    target_ids = {r["task_id"] for r in result["tasks"] if r["phase"] in ("VALID", "TEST")}
    assert {r["task_id"] for r in scheduled} == target_ids
    for identity in target_ids:
        assert Counter(r["arm"] for r in scheduled if r["task_id"] == identity) == Counter(plan.ARMS.keys())
    assert result["scope"]["validation_outcomes_may_change_test_policy"] is False


def test_cross_file_declaration_is_required_for_selection_but_not_a_visible_graph_claim():
    data = rows()
    for row in data:
        if row["completion_path"].endswith("module0.py"):
            row["dependency"]["cross_file"] = []
    result = build(data)
    forbidden = {r["namespace"] for r in data if not r["dependency"]["cross_file"]}
    assert not forbidden & {r["task_id"] for r in result["tasks"]}
    assert all(p["remaining_resolved_visible_cross_file_calls"] is None for p in result["projects"])


def test_duplicate_public_requirement_files_cannot_cross_phases():
    data = rows()
    data[3]["requirement"] = deepcopy(data[0]["requirement"])
    result = build(data)
    by_task = {r["task_id"]:r for r in result["tasks"]}
    first_files = {r["completion_path"] for r in (data[0],data[3])}
    chosen = [by_task[r["namespace"]] for r in data if r["completion_path"] in first_files and r["namespace"] in by_task]
    assert len({r["phase"] for r in chosen}) <= 1


def test_cross_repository_exact_requirement_clones_exclude_whole_source_files():
    data = rows()
    data[18]["requirement"] = deepcopy(data[0]["requirement"])
    result = build(data)
    excluded = {r["namespace"] for r in data if r["completion_path"] in {data[0]["completion_path"], data[18]["completion_path"]}}
    assert set(result["cross_repository_exact_requirement_clone_exclusions"]) == excluded
    assert not excluded & {r["task_id"] for r in result["tasks"]}


def test_insufficient_file_groups_fail_without_task_or_project_substitution():
    data = rows()
    for row in data:
        row["completion_path"] = row["project_path"]+"/single_file.py"
    with pytest.raises(ValueError, match="NO_FILE_DISJOINT"):
        build(data)


def test_old_control_repository_reuse_is_rejected():
    with pytest.raises(ValueError, match="CONTROL_PROJECT_REUSE"):
        plan.build_plan(rows(), metadata_reference={}, source_archive_reference={}, projects=(plan.assets.PROJECTS[0],))


def test_zero_l3_does_not_block_l2_or_claim_l3_comparison():
    result = build(rows())
    assert result["l3_policy"]["zero_skills_blocks_l2_evaluation"] is False
    assert result["l3_policy"]["zero_skills_full_equivalent_to_no_l3"] is True
    assert result["l3_policy"]["comparison_requires_actual_l3_exposure"] is True
    assert result["l3_policy"]["official_public_green_claim"] is False
    assert result["memory_protocol"]["layer_priority"] == ["L3", "L2", "L1"]


def test_no_external_or_platform_specific_reference_paths(tmp_path):
    path=tmp_path/"inside"/"file.json"
    path.parent.mkdir(); path.write_text("{}")
    reference = plan.portable_reference(path,tmp_path)
    assert reference["path"] == "inside/file.json"
    with pytest.raises(ValueError,match="REFERENCE_OUTSIDE_REPOSITORY"):
        plan.portable_reference(path,tmp_path/"other")
