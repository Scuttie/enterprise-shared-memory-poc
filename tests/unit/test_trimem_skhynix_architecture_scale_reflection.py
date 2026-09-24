"""Actual public trace projections and unchanged Gate B, without model execution."""
from dataclasses import asdict

import pytest

from enterprise_memory.trimem.accounting import canonical_bytes
from enterprise_memory.trimem.skill_memory import ProcedureTemplate
import trimem_skhynix_architecture_learning as learning
import trimem_skhynix_architecture_memory as memory
import trimem_skhynix_architecture_scale_reflection as reflection
from test_trimem_skhynix_architecture_learning import inputs, cell, captured, write, ARGV
from test_trimem_skhynix_architecture_scale_learning import scaled


def proposals(inputs, reference):
    public = memory._read(reference["path"])
    template = ProcedureTemplate("normalize filename extension", ("path", "test_argv"), (memory.PRECONDITION,),
        ("read_file {path}", "replace_text {path}\nold_text: upper\nnew_text: lower", "run_command {test_argv}"), "{test_argv}", "python")
    value = {"schema": learning.PROPOSALS_SCHEMA, "reflection_sha256": reference["sha256"],
        "proposals": [{"template": asdict(template), "observations": [
            {"source_alias": source["source_alias"], "bindings": {"path": "source.py", "test_argv": canonical_bytes(ARGV).decode()},
                "step_numbers": [3, 6, 7], "red_step": 5} for source in public["sources"]]}]}
    return write(inputs.tmp / "batch-proposals.json", value)


def test_batch_is_bounded_actual_projection_and_independent_gate_b_still_required(inputs):
    captured(inputs)
    before = (inputs.root / "catalog.json").read_bytes()
    reference = reflection.build_reflection_plan(inputs.root, inputs.tmp / "plan.json")
    plan = memory._read(reference["path"])
    assert plan["status"] == "READY" and len(plan["jobs"]) == 1
    assert plan["gate_b_promotions"] == plan["model_calls"] == plan["official_grader_runs"] == 0
    assert (inputs.root / "catalog.json").read_bytes() == before
    job = plan["jobs"][0]
    assert job["independent_tasks"] == job["independent_owners"] == 2
    assert job["repository"] == "example/project" and job["public_bytes"] <= 190000
    assert job["job_id"].startswith("batch-") and job["ordinal"] == 1
    public = memory._read(job["reflection_reference"]["path"])
    assert all(row["checkpoint"]["kind"] == "PUBLIC_TEST_OBSERVATION" for row in public["sources"])
    assert all(row["checkpoint"]["public_test_outcome"] == "GREEN" for row in public["sources"])
    assert reflection.build_reflection_plan(inputs.root, inputs.tmp / "plan.json") == reference
    check = learning.export_reflection(inputs.root, job["reflection_reference"]["path"], capture_ids=job["capture_ids"], max_bytes=190000)
    assert check["sha256"] == job["reflection_reference"]["sha256"]
    result = learning.ingest_proposals(inputs.root, proposals(inputs, job["reflection_reference"]),
        reflection_reference=job["reflection_reference"])
    assert memory._read(result["path"])["promotions_added"] == 1
    bank = learning.freeze_published_bank(inputs.root, inputs.tmp / "verified-bank.json")
    assert bank["layer_counts"]["L3_skills"] == 1


def test_many_tasks_become_deterministic_batches_not_one_fixed_repository_pair(inputs, monkeypatch):
    monkeypatch.setattr(learning, "SCALE_TRAINING_COUNTS", (6,))
    ctx = scaled(inputs, monkeypatch, 6)
    for index in range(1, 7):
        learning.capture_cell(ctx.root, cell(ctx, index))
    ref = reflection.build_reflection_plan(ctx.root, ctx.tmp / "many-plan.json", max_sources_per_batch=4)
    plan = memory._read(ref["path"])
    assert [len(job["capture_ids"]) for job in plan["jobs"]] == [4, 2]
    assert len({job["job_id"] for job in plan["jobs"]}) == 2
    selected_tasks = set()
    for job in plan["jobs"]:
        assert job["public_bytes"] <= 190000 and job["independent_owners"] == 2
        with learning._session(ctx.root, mutable=False) as (_, _, registry, _):
            available = learning._available_captures(ctx.root, registry)
        selected_tasks.update(available[identity][1]["task"]["task_id"] for identity in job["capture_ids"])
    assert selected_tasks == {row["target_id"] for row in ctx.targets[:6]}
    assert memory._read(ctx.root / "catalog.json")["skills"] == {}


def test_scaled_bank_preserves_all_development_and_final_scope_with_real_promotion(inputs, monkeypatch):
    monkeypatch.setattr(learning, "SCALE_TRAINING_COUNTS", (2,))
    ctx = scaled(inputs, monkeypatch, 2)
    captured(ctx)
    ref = reflection.build_reflection_plan(ctx.root, ctx.tmp / "scale-bank-plan.json")
    job = memory._read(ref["path"])["jobs"][0]
    verification = learning.ingest_proposals(ctx.root, proposals(ctx, job["reflection_reference"]),
        reflection_reference=job["reflection_reference"])
    assert memory._read(verification["path"])["promotions_added"] == 1
    frozen = learning.freeze_published_bank(ctx.root, ctx.tmp / "scale-bank.json")
    bank = memory.load_frozen_bank(frozen["path"], frozen["sha256"])
    try:
        assert len(bank.manifest["scope"]["evaluation_tasks"]) == 560
        assert len(bank.manifest["scope"]["training_tasks"]) == 2
        assert all(value > 0 for value in bank.manifest["layer_counts"].values())
    finally:
        bank.close()


def test_reused_original_captures_receive_distinct_jobs_in_each_cumulative_authority(inputs, monkeypatch):
    paths, _ = captured(inputs)
    old = memory._read(reflection.build_reflection_plan(inputs.root, inputs.tmp / "original-plan.json")["path"])
    monkeypatch.setattr(learning, "SCALE_TRAINING_COUNTS", (2,))
    ctx = scaled(inputs, monkeypatch, 2)
    for path in paths:
        learning.capture_cell(ctx.root, path)
    new = memory._read(reflection.build_reflection_plan(ctx.root, ctx.tmp / "expanded-plan.json")["path"])
    assert old["jobs"][0]["capture_ids"] == new["jobs"][0]["capture_ids"]
    assert old["jobs"][0]["job_id"] != new["jobs"][0]["job_id"]


def test_cap_never_truncates_certifying_rows_or_invents_a_pair(inputs):
    captured(inputs)
    before = (inputs.root / "catalog.json").read_bytes()
    plan = memory._read(reflection.build_reflection_plan(inputs.root, inputs.tmp / "too-small.json", max_bytes=1024)["path"])
    assert plan["status"] == "NO_REPEAT_PROCEDURE_CANDIDATES" and plan["jobs"] == []
    assert any(row["reason"] == "NO_INDEPENDENT_PAIR_FITS_EXACT_CONTEXT_CAP" for row in plan["skipped_candidates"])
    assert (inputs.root / "catalog.json").read_bytes() == before
    assert not (inputs.tmp / "too-small-exports").exists()


def test_no_verified_repeat_is_honest_and_does_not_freeze_learning(inputs):
    captured(inputs, second_green=False)
    plan = memory._read(reflection.build_reflection_plan(inputs.root, inputs.tmp / "no-repeat.json")["path"])
    assert plan["jobs"] == [] and plan["gate_b_promotions"] == 0
    assert not (inputs.root / "learning-frozen.json").exists()
    with pytest.raises(learning.LearningError, match="reflection proposal"):
        learning.freeze_published_bank(inputs.root, inputs.tmp / "unverified-bank.json")


def test_incomplete_sources_cannot_be_selected_as_a_completed_stage(inputs):
    learning.capture_cell(inputs.root, cell(inputs, 1))
    with pytest.raises(learning.LearningError, match="every enrolled source"):
        reflection.build_reflection_plan(inputs.root, inputs.tmp / "premature.json")
    assert not (inputs.tmp / "premature.json").exists()


@pytest.mark.parametrize("change", ["export", "policy", "source"])
def test_frozen_plan_rejects_replay_with_changed_evidence_or_limits(inputs, change):
    paths, _ = captured(inputs)
    path = inputs.tmp / "plan.json"
    ref = reflection.build_reflection_plan(inputs.root, path)
    plan = memory._read(ref["path"])
    if change == "export":
        with open(plan["jobs"][0]["reflection_reference"]["path"], "ab") as stream:
            stream.write(b" ")
    elif change == "source":
        with (paths[0].parent / "broker/events.jsonl").open("ab") as stream:
            stream.write(b"{}\n")
    with pytest.raises(ValueError):
        reflection.build_reflection_plan(inputs.root, path, max_sources_per_batch=2 if change == "policy" else 8)


@pytest.mark.parametrize("arguments", [{"max_bytes": 190001}, {"max_bytes": True},
    {"max_sources_per_batch": 1}, {"max_sources_per_batch": 25}])
def test_invalid_context_and_source_limits_fail_before_export(inputs, arguments):
    with pytest.raises(learning.LearningError):
        reflection.build_reflection_plan(inputs.root, inputs.tmp / "invalid.json", **arguments)
