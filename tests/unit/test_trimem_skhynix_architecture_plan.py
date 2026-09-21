"""Strict preparation contracts using labelled synthetic public metadata only."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

import trimem_skhynix_architecture_plan as architecture


def write(path, value):
    path.write_bytes(architecture.canonical(value) + b"\n")
    return {"path": str(path), "sha256": architecture.file_sha(path)}


def task(index):
    return {"instance_id": f"fixture__repo-{index:04d}", "repository": "fixture/repo",
        "base_commit": f"{index:040x}", "created_at": "2026-01-01T00:00:00Z",
        "instruction_sha256": architecture.sha(f"Synthetic public instruction {index}".encode())}


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    # Test-only pin substitution: production constants retain the actual Verified
    # revision/hash/size. Opaque binary bytes must never be decoded as dataset rows.
    source = tmp_path / "synthetic-source.bin"
    source.write_bytes(b"\x00\xff\xfe synthetic opaque fixture bytes")
    pin = {**architecture.EVALUATION_SOURCE, "sha256": architecture.file_sha(source), "bytes": source.stat().st_size}
    monkeypatch.setattr(architecture, "EVALUATION_SOURCE", pin)
    value = {"schema": architecture.INVENTORY_SCHEMA,
        "dataset": {**pin, "path": str(source)}, "tasks": [task(index) for index in range(500)]}
    monkeypatch.setattr(architecture, "EVALUATION_TASKS_SHA256", architecture.sha(architecture.canonical(value["tasks"])))
    path = tmp_path / "evaluation.json"
    return {"reference": write(path, value), "value": value, "path": path, "source": source,
        "output": tmp_path / "design.json"}


def training_inventory(tmp_path, indices=(500, 501), name="training"):
    source = tmp_path / f"{name}.bin"
    source.write_bytes(("Synthetic training source " + name).encode())
    value = {"schema": architecture.INVENTORY_SCHEMA,
        "dataset": {"dataset_id": "SWE-bench/SWE-bench", "revision": "b" * 40, "split": "dev",
            "path": str(source), "sha256": architecture.file_sha(source), "bytes": source.stat().st_size},
        "tasks": [task(index) for index in indices]}
    path = tmp_path / f"{name}.json"
    return write(path, value), value, path


def build(inventory, **kwargs):
    return architecture.build_architecture_design(inventory["reference"], output=inventory["output"], **kwargs)


def reference(receipt):
    return {key: receipt[key] for key in ("path", "sha256")}


def load(receipt):
    return architecture.load_architecture_design(receipt["path"], receipt["sha256"])


def test_full500_two_arm_design_has_shared_whole_task_limits_and_no_invented_readiness(inventory):
    receipt = build(inventory)
    design = load(receipt)
    assert receipt["status"] == design["status"] == "NOT_EVALUATION_READY"
    assert design["phase"] == "PREPARATION"
    assert set(design["arms"]) == {"A", "C"}
    baseline, pdf = design["arms"]["A"], design["arms"]["C"]
    assert baseline["name"] == "BASELINE" and baseline["external_memory"] == "DISABLED"
    assert baseline["context"] == "FLAT_BOUNDED_PUBLIC_HISTORY"
    assert pdf["name"] == "PDF_MEMORY" and pdf["external_memory"] == "ENABLED"
    assert pdf["retrieval_order"] == ["SKILL", "REPOSITORY_KG", "EPISODE"]
    assert pdf["l1"]["scope"] == ["org_id", "owner_user_id", "repository"]
    assert pdf["l2"]["ranking"] == "PPR"
    assert pdf["l3"]["minimum_verified_skill_count"] == 1
    assert baseline["limits"] == pdf["limits"] == design["common_limits"]
    assert design["common_limits"]["requests_per_task"] == 120
    assert design["common_limits"]["wall_seconds_per_task"] == 1200
    assert design["common_limits"]["context_utf8_bytes"] == 196608
    assert design["common_limits"]["accounting_scope"] == "WHOLE_TASK_ACROSS_ALL_WORKERS"
    assert design["common_limits"]["reset_on_worker_transition"] is False
    assert baseline["worker_policy"] == pdf["worker_policy"]
    assert baseline["worker_policy"]["fork_turns"] == "none"
    assert design["model"] == {"requested": "gpt-6-astra", "actual_snapshot_attested": False,
        "actual_tokens": None, "actual_cost": None}
    assert design["evaluation"]["task_count"] == len(design["evaluation"]["tasks"]) == 500
    assert {row["instance_id"] for row in design["evaluation"]["tasks"]} == {row["instance_id"] for row in inventory["value"]["tasks"]}
    assert receipt["planned_cells"] == 1000
    assert design["evaluation_gate_a"]["admit_to_frozen_retrieval_bank"] is False
    assert design["evaluation_gate_a"]["cross_target_retrieval"] is False
    assert design["model_calls"] == design["grader_calls"] == design["training_runs"] == 0


def test_omitted_training_inventory_is_an_explicit_preparation_gap(inventory):
    receipt = build(inventory)
    report = architecture.inspect_readiness(reference(receipt))
    assert report["status"] == "NOT_EVALUATION_READY"
    assert report["live_integration_verified"] is False
    assert report["actual_tokens"] is report["actual_cost"] is None
    assert report["training_candidate_tasks"] == 0
    checks = {row["requirement"]: row for row in report["checks"]}
    assert checks["full_target_inventory"]["status"] == "VERIFIED_PUBLIC_INVENTORY_BINDING"
    assert checks["training_enrollment"]["status"] == "MISSING_EVIDENCE"
    assert "No training candidate inventory" in checks["training_enrollment"]["pending_reason"]
    assert {row["requirement"] for row in report["pending_reasons"]} == set(architecture.REQUIREMENTS) - {"full_target_inventory"}


def test_two_disjoint_training_candidate_inventories_are_not_training_or_a_verified_bank(inventory, tmp_path):
    first, _, _ = training_inventory(tmp_path)
    second, _, _ = training_inventory(tmp_path, (502, 503), "second")
    receipt = build(inventory, training_inventory=[first, second])
    design = load(receipt)
    assert design["training"]["candidate_task_count"] == 4
    assert design["training"]["role"] == "CANDIDATES_ONLY_NOT_ENROLLED_OR_EXECUTED"
    assert design["training"]["training_execution"] == design["training"]["trained_bank"] == "NOT_BOUND"
    report = architecture.inspect_readiness(reference(receipt))
    assert report["status"] == "NOT_EVALUATION_READY"
    assert report["training_candidate_tasks"] == 4
    assert all(row["status"] == "MISSING_EVIDENCE" for row in report["checks"] if row["requirement"] != "full_target_inventory")


@pytest.mark.parametrize("mutation", ["omit", "duplicate", "unsorted", "foreign_repo", "extra_task"])
def test_evaluation_inventory_rejects_omissions_duplicates_and_scope_substitutions(inventory, mutation):
    value = deepcopy(inventory["value"])
    if mutation == "omit":
        value["tasks"].pop()
    elif mutation == "duplicate":
        value["tasks"][-1] = deepcopy(value["tasks"][0])
    elif mutation == "unsorted":
        value["tasks"][0], value["tasks"][1] = value["tasks"][1], value["tasks"][0]
    elif mutation == "foreign_repo":
        value["tasks"][0]["repository"] = "other/repo"
    else:
        value["tasks"].append(task(500))
    inventory["reference"] = write(inventory["path"], value)
    with pytest.raises(architecture.ArchitecturePlanError):
        build(inventory)
    assert not inventory["output"].exists()


@pytest.mark.parametrize("field", ["instance_id", "instruction_sha256", "created_at", "base_commit"])
def test_exact_public_projection_pin_rejects_valid_same_count_descriptor_substitution(inventory, field):
    value = deepcopy(inventory["value"])
    value["tasks"][-1][field] = {"instance_id": "fixture__repo-0500", "instruction_sha256": "e" * 64,
        "created_at": "2026-01-02T00:00:00Z", "base_commit": "f" * 40}[field]
    assert len(value["tasks"]) == 500
    inventory["reference"] = write(inventory["path"], value)
    with pytest.raises(architecture.ArchitecturePlanError, match="pinned exact 500-task inventory"):
        build(inventory)
    assert not inventory["output"].exists()


@pytest.mark.parametrize("field", ["patch", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS", "problem_statement", "task_id"])
def test_inventory_refuses_extra_or_hidden_columns_without_decoding_source_rows(inventory, field, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyarrow", None)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", None)
    value = deepcopy(inventory["value"])
    value["tasks"][0][field] = "forbidden fixture field"
    inventory["reference"] = write(inventory["path"], value)
    with pytest.raises(architecture.ArchitecturePlanError, match="forbidden fields"):
        build(inventory)


def test_training_original_instance_overlap_is_rejected_even_with_different_task_prefix(inventory, tmp_path):
    candidate, _, _ = training_inventory(tmp_path, (12, 500))
    with pytest.raises(architecture.ArchitecturePlanError, match="original source-instance"):
        build(inventory, training_inventory=candidate)


def test_training_public_instruction_alias_is_rejected_despite_different_original_id(inventory, tmp_path):
    candidate, value, path = training_inventory(tmp_path)
    value["tasks"][0]["instruction_sha256"] = inventory["value"]["tasks"][0]["instruction_sha256"]
    candidate = write(path, value)
    with pytest.raises(architecture.ArchitecturePlanError, match="instruction hashes"):
        build(inventory, training_inventory=candidate)


def test_training_duplicates_across_candidate_files_are_rejected(inventory, tmp_path):
    first, _, _ = training_inventory(tmp_path)
    second, _, _ = training_inventory(tmp_path, (501, 502), "second")
    with pytest.raises(architecture.ArchitecturePlanError, match="unique and disjoint"):
        build(inventory, training_inventory=[first, second])


@pytest.mark.parametrize("field", ["dataset_id", "revision", "split", "sha256", "bytes"])
def test_evaluation_dataset_pin_cannot_be_replaced_by_rehashed_inventory(inventory, field):
    value = deepcopy(inventory["value"])
    value["dataset"][field] = 1 if field == "bytes" else "a" * 40 if field == "revision" else "a" * 64 if field == "sha256" else "different"
    inventory["reference"] = write(inventory["path"], value)
    with pytest.raises(architecture.ArchitecturePlanError, match="pinned full Verified"):
        build(inventory)


@pytest.mark.parametrize("which", ["inventory", "source"])
def test_changed_inventory_or_opaque_source_bytes_are_rejected(inventory, which):
    path = inventory["path"] if which == "inventory" else inventory["source"]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(architecture.ArchitecturePlanError, match="changed|byte hash"):
        build(inventory)


@pytest.mark.parametrize("mutation", ["B", "forced_delivery", "score_override", "manual_assignment", "unequal_requests",
    "unequal_context", "budget_reset", "omit_target", "substitute_target", "ready", "quarantine", "declared_trained", "model", "zero_gate_b"])
def test_rehashed_design_cannot_change_arms_targets_budgets_or_claim_integration(inventory, mutation):
    receipt = build(inventory)
    design = load(receipt)
    pdf = design["arms"]["C"]
    if mutation == "B":
        design["arms"]["B"] = deepcopy(pdf)
    elif mutation in ("forced_delivery", "score_override"):
        pdf[mutation] = True
    elif mutation == "manual_assignment":
        design["lesson_assignments"] = [{"relevant": "arbitrary lesson"}]
    elif mutation == "unequal_requests":
        pdf["limits"]["requests_per_task"] = 121
    elif mutation == "unequal_context":
        pdf["limits"]["context_utf8_bytes"] += 1
    elif mutation == "budget_reset":
        pdf["limits"]["reset_on_worker_transition"] = True
    elif mutation == "omit_target":
        design["evaluation"]["tasks"].pop()
    elif mutation == "substitute_target":
        design["evaluation"]["tasks"][-1] = {"task_id": "swebench_verified--fixture__repo-9999", **task(9999)}
    elif mutation == "ready":
        design["status"] = "EVALUATION_READY"
    elif mutation == "quarantine":
        design["evaluation_gate_a"]["admit_to_frozen_retrieval_bank"] = True
    elif mutation == "declared_trained":
        design["training"]["trained_bank"] = "READY"
    elif mutation == "model":
        design["model"]["requested"] = "another-model"
    else:
        pdf["l3"]["minimum_verified_skill_count"] = 0
    changed = write(Path(receipt["path"]), design)
    with pytest.raises(architecture.ArchitecturePlanError, match="immutable public inventory"):
        load(changed)


@pytest.mark.parametrize("cap", [False, 0, 4095, 196609, "196608"])
def test_common_context_cap_requires_bounded_integer(inventory, cap):
    with pytest.raises(architecture.ArchitecturePlanError, match="Common context"):
        build(inventory, context_budget_bytes=cap)


def test_custom_common_context_cap_is_identical_in_both_arms(inventory):
    design = load(build(inventory, context_budget_bytes=96000))
    assert design["arms"]["A"]["limits"] == design["arms"]["C"]["limits"]
    assert design["common_limits"]["context_utf8_bytes"] == 96000


@pytest.mark.parametrize("evidence", [{"ready": True}, {"native_context_handoff": True},
    {"gate_b": {"verified_skill_count": 12}}, {"generic_runtime_manifest": {"status": "PASS"}}])
def test_readiness_refuses_declared_switches_and_counts(inventory, evidence):
    receipt = build(inventory)
    with pytest.raises(architecture.ArchitecturePlanError):
        architecture.inspect_readiness(reference(receipt), evidence)


def test_even_hash_bound_ready_claims_and_unit_receipts_do_not_prove_live_integration(inventory, tmp_path):
    receipt = build(inventory)
    proof = write(tmp_path / "declared-ready.json", {"status": "PASS", "ready": True,
        "all_layers_integrated": True, "verified_skill_count": 99, "unit_tests_passed": 999})
    evidence = {key: proof for key in architecture.REQUIREMENTS if key != "full_target_inventory"}
    evidence["full_target_inventory"] = inventory["reference"]
    before = inventory["output"].read_bytes()
    report = architecture.inspect_readiness(reference(receipt), evidence)
    assert report["status"] == "NOT_EVALUATION_READY" and report["live_integration_verified"] is False
    assert len(report["pending_reasons"]) == 7
    assert all(row["status"] == "HASH_BOUND_UNVERIFIED" for row in report["checks"] if row["requirement"] != "full_target_inventory")
    assert inventory["output"].read_bytes() == before


def test_readiness_rejects_changed_evidence_reference(inventory, tmp_path):
    receipt = build(inventory)
    evidence = write(tmp_path / "test-receipt.json", {"tests": 1})
    Path(evidence["path"]).write_bytes(b"changed")
    with pytest.raises(architecture.ArchitecturePlanError, match="bytes changed"):
        architecture.inspect_readiness(reference(receipt), {"live_l1": evidence})


def test_readiness_inventory_reference_cannot_substitute_a_different_500_list(inventory, tmp_path):
    receipt = build(inventory)
    another = write(tmp_path / "another.json", inventory["value"])
    with pytest.raises(architecture.ArchitecturePlanError, match="fixed full 500"):
        architecture.inspect_readiness(reference(receipt), {"full_target_inventory": another})


def test_output_is_immutable_and_rejects_linked_inventory(inventory, tmp_path):
    receipt = build(inventory)
    before = inventory["output"].read_bytes()
    with pytest.raises(architecture.ArchitecturePlanError, match="overwrite"):
        build(inventory)
    assert inventory["output"].read_bytes() == before
    link = tmp_path / "linked.json"
    link.symlink_to(inventory["path"])
    with pytest.raises(architecture.ArchitecturePlanError, match="Linked"):
        architecture.load_public_inventory({"path": str(link), "sha256": inventory["reference"]["sha256"]}, evaluation=True)
    assert load(receipt)["status"] == "NOT_EVALUATION_READY"


def test_duplicate_json_fields_are_rejected_before_using_a_declared_inventory(inventory):
    inventory["path"].write_text('{"schema":"one","schema":"two"}')
    inventory["reference"]["sha256"] = architecture.file_sha(inventory["path"])
    with pytest.raises(architecture.ArchitecturePlanError, match="Duplicate JSON"):
        build(inventory)
