from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace
import time
import pytest

import trimem_skhynix_architecture_scale_pipeline as scale


def report(size, resolved):
    return {"scope": "DEVELOPMENT", "planned": 60, "completed": 60,
            "size": size, "resolved": resolved, "task_ids": [f"task-{n}" for n in range(60)],
            "bank_reference": {"path": f"/bank-{size}.json", "sha256": str(size)}, "status": "COMPLETE"}


def test_choice_uses_dev_resolution_then_smaller_bank_and_can_report_harm():
    baseline = report(240, 40)
    chosen = scale.selection([report(240, 39), report(120, 39), report(24, 38)], baseline)
    assert chosen["selected_size"] == 120
    assert chosen["development_delta_percentage_points"] == pytest.approx(-100 / 60)
    assert chosen["final_outcomes_used"] is False


def test_not_ready_pilot_does_not_block_larger_valid_bank():
    chosen = scale.selection([{"size": 24, "status": "NOT_READY"}, report(120, 42)], report(240, 40))
    assert chosen["selected_size"] == 120


@pytest.mark.parametrize("purpose", ["DEVELOPMENT_BASELINE", "DEVELOPMENT_BANK", "FINAL_EVALUATION"])
def test_evaluation_removes_training_grade_hold_policy_from_every_future_arm(tmp_path, monkeypatch, purpose):
    p = scale.ScalePipeline.__new__(scale.ScalePipeline)
    p.root = tmp_path / "pipeline"
    template = {"dataset_manifest": {"path": "/dataset", "sha256": "d" * 64},
        "training_grade_hold_policy": scale.TRAINING_GRADE_HOLD_POLICY,
        "source_root": "/source", "source_sha256": {}, "loader_preflight_path": "/loader",
        "loader_preflight_sha256": "e" * 64, "codex_binary": "C:/codex.exe"}
    reference = scale.core.retain(tmp_path / "template.json", template)
    p.config = {"grading_continuation_reference": reference, "training_experiment_reference": reference,
                "evaluation_native_root": str(tmp_path / "native")}
    p.reference = reference
    p.operations = SimpleNamespace(modules={"cohort": SimpleNamespace(execution=SimpleNamespace(
        create_execution_enrollment=lambda *a, **kw: {"path": "/authority", "sha256": "a" * 64}))})
    class CapturedEvaluation(Exception):
        pass
    def capture(path, value):
        assert value["phase"] == "EVALUATION_RUNTIME"
        assert "training_grade_hold_policy" not in value
        assert value["source_root"] == template["source_root"]
        raise CapturedEvaluation()
    monkeypatch.setattr(scale, "write_execution", capture)
    with pytest.raises(CapturedEvaluation):
        p._evaluation(purpose, {"size": 120, "execution_reference": reference}, None, "test")


@pytest.mark.parametrize("mutation", [
    {"scope": "FINAL"}, {"completed": 59}, {"planned": 500},
    {"resolved": True}, {"resolved": 61}, {"task_ids": ["other"]}, {"size": 500},
])
def test_selection_rejects_final_partial_invalid_or_different_targets(mutation):
    candidate = {**report(120, 42), **mutation}
    with pytest.raises(scale.core.PipelineError):
        scale.selection([candidate], report(240, 40))


def test_selection_rejects_duplicate_bank_sizes_and_no_ready_bank():
    for candidates in ([report(120, 41), report(120, 42)], [{"size": 24, "status": "NOT_READY"}]):
        with pytest.raises(scale.core.PipelineError):
            scale.selection(candidates, report(240, 40))


@pytest.mark.parametrize("mutation", [{"scope": "FINAL"}, {"completed": 59}, {"planned": 500}])
def test_baseline_must_be_complete_development(mutation):
    baseline = {**report(240, 40), **mutation}
    with pytest.raises(scale.core.PipelineError):
        scale.selection([report(120, 42)], baseline)


def fake_pipeline(tmp_path, readiness):
    p = scale.ScalePipeline.__new__(scale.ScalePipeline)
    p.root = tmp_path / "scale"
    p.root.mkdir()
    p.clock = time.time
    p.config = {"training_stages": [{"size": n} for n in scale.SIZES],
                "protocol_reference": {"path": "/protocol", "sha256": "protocol"}}
    p.reference = scale.core.retain(p.root / "config.json", p.config)
    tail = scale.core.retain(tmp_path / "old/events/00000001.json", {"stage": "BLOCKED"})
    p.adoption = {"original_pipeline_event_tail_reference": tail}
    p.calls = []
    p.progress = lambda: None
    p.status = lambda: {"complete": p.latest("PIPELINE_COMPLETE") is not None,
                         "not_ready": p.latest("NO_READY_MEMORY_BANK") is not None}

    def bank(stage):
        p.calls.append(("collect", stage["size"]))
        return {"size": stage["size"], "status": readiness[stage["size"]],
                "bank_reference": {"path": f"/bank-{stage['size']}", "sha256": "bank"}}

    def evaluate(purpose, stage, bank_reference, name):
        p.calls.append((purpose, stage["size"]))
        r = report(stage["size"], 40 if purpose == "DEVELOPMENT_BASELINE" else 42)
        r["bank_reference"] = bank_reference
        return r, scale.core.retain(p.root / (name + ".json"), r)

    p._bank, p._evaluation = bank, evaluate
    return p


def test_run_collects_all_sizes_reuses_one_dev_baseline_and_selects_before_final(tmp_path):
    p = fake_pipeline(tmp_path, {24: "NOT_READY", 120: "READY", 240: "READY"})
    assert p.run()["complete"] is True
    assert p.calls == [("collect", 24), ("collect", 120), ("collect", 240),
                       ("DEVELOPMENT_BASELINE", 24), ("DEVELOPMENT_BANK", 120),
                       ("DEVELOPMENT_BANK", 240), ("FINAL_EVALUATION", 120)]
    assert scale.core.read(p.root / "bank-selection.json")["selected_size"] == 120
    before = list(p.calls)
    p.run()
    assert p.calls == before  # completed pipeline does not solve again


def test_all_banks_not_ready_still_collects240_but_never_launches_final(tmp_path):
    p = fake_pipeline(tmp_path, {n: "NOT_READY" for n in scale.SIZES})
    assert p.run()["not_ready"] is True
    assert p.calls == [("collect", 24), ("collect", 120), ("collect", 240)]
    assert not (p.root / "bank-selection.json").exists()


def test_completed_publication_recovery_precedes_mutable_learning(tmp_path):
    p = scale.ScalePipeline.__new__(scale.ScalePipeline)
    p.root, p.base_reflection_root = tmp_path / "scale", str(tmp_path / "native")
    p.operations = SimpleNamespace()
    p.config = {}
    p.latest = lambda *args: None
    p._learning = lambda *args: pytest.fail("frozen learning must not be initialized/captured again")
    p._finish_bank = lambda stage, publication, plan: {"size": stage["size"], "publication": publication, "plan": plan}
    execution = scale.core.retain(tmp_path / "execution.json", {"run_root": str(tmp_path / "run")})
    published = scale.core.retain(p.root / "publication.json", {"status": "FROZEN"})
    scale.core.retain(p.root / "learning-24/learning-frozen.json", published)
    plan = scale.core.retain(Path(p.base_reflection_root) / "bank-24/reflection-plan.json", {"jobs": []})
    recovered = p._bank({"size": 24, "execution_reference": execution})
    assert recovered == {"size": 24, "publication": published, "plan": plan}


def test_recovery_holds_all_predecessors_until_run_finishes(tmp_path, monkeypatch):
    p = fake_pipeline(tmp_path, {n: "NOT_READY" for n in scale.SIZES})
    extra = scale.core.retain(tmp_path / "previous-scale/events/00000007.json", {"stage": "BLOCKED"})
    p.adoption["predecessor_pipeline_event_tail_references"] = [extra]
    held = set()

    @contextmanager
    def observed_lock(path):
        assert path not in held
        held.add(path)
        try:
            yield
        finally:
            held.remove(path)

    monkeypatch.setattr(scale, "locked", observed_lock)
    expected = {tmp_path / "old/run.lock", tmp_path / "previous-scale/run.lock", p.root / "run.lock"}
    original_bank = p._bank

    def bank(stage):
        assert held == expected
        return original_bank(stage)

    p._bank = bank
    assert p.run()["not_ready"] is True
    assert held == set()


@pytest.mark.parametrize("mutation", ["advanced", "modified", "duplicate", "self", "not_list"])
def test_recovery_rejects_changed_or_invalid_predecessors_before_model_work(tmp_path, mutation):
    p = fake_pipeline(tmp_path, {n: "NOT_READY" for n in scale.SIZES})
    extra = scale.core.retain(tmp_path / "previous-scale/events/00000007.json", {"stage": "BLOCKED"})
    p.adoption["predecessor_pipeline_event_tail_references"] = [extra]
    if mutation == "advanced":
        scale.core.retain(tmp_path / "previous-scale/events/00000008.json", {"stage": "RESUMED"})
    elif mutation == "modified":
        Path(extra["path"]).write_text('{}\n')
    elif mutation == "duplicate":
        p.adoption["predecessor_pipeline_event_tail_references"].append(extra)
    elif mutation == "self":
        p.adoption["predecessor_pipeline_event_tail_references"] = [scale.core.retain(p.root / "events/00000001.json", {})]
    else:
        p.adoption["predecessor_pipeline_event_tail_references"] = extra
    with pytest.raises(scale.core.PipelineError):
        p.run()
    assert p.calls == []
