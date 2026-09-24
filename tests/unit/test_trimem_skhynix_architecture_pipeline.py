"""Public synthetic orchestration only: no native process, grader or cleanup."""
from copy import deepcopy
from pathlib import Path, PureWindowsPath
import sys
from types import SimpleNamespace

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2] / "scripts")]
import trimem_skhynix_architecture_pipeline as pipeline
import trimem_skhynix_architecture_publisher as publisher


class FakeOperations:
    def __init__(self, root, definition, targets):
        self.root, self.definition, self.targets = root, definition, targets
        self.training_done, self.evaluation_done = 24, 0
        self.calls, self.block_phase = [], None
        self.fail_publish, self.fail_ingest, self.fail_freeze = None, None, None
        self.promote = True
        self.reused_thread = False
        self.progress_count = 0
        self.learning_root = Path(definition["learning_enrollment_reference"]["path"]).parent
        pipeline.retain(self.learning_root / "catalog.json", {"skills": {}})

    def phase(self, root):
        return "TRAINING" if str(root).endswith("training-cohort") else "EVALUATION"

    def cohort_status(self, root):
        phase = self.phase(root)
        count = self.training_done if phase == "TRAINING" else self.evaluation_done
        planned = 24 if phase == "TRAINING" else 1000
        return {"status": "COMPLETE" if count == planned else "IN_PROGRESS", "scope": "FULL_FIXED_COHORT",
                "planned_cells": planned, "completed_cells": count, "phase": phase}

    def run_cohort(self, root):
        phase = self.phase(root)
        self.calls.append(("cohort", phase))
        if self.block_phase == phase:
            return {**self.cohort_status(root), "status": "BLOCKED"}
        if phase == "TRAINING":
            self.training_done += 1
        else:
            self.evaluation_done += 1
        return self.cohort_status(root)

    def inventory(self, root):
        self.calls.append(("inventory", None))
        return [{"capture_id": target["target_id"] + "-green", "task_id": target["target_id"],
                 "repository": target["repository"], "kind": "PUBLIC_TEST_OBSERVATION", "public_test_outcome": "GREEN",
                 "cutoff_step": 5, "node_id": "repair"} for target in self.targets if target["role"] == "TRAINING"]

    def export_reflection(self, root, path, capture_ids, max_bytes):
        self.calls.append(("export", tuple(capture_ids)))
        assert len(capture_ids) == 2 and max_bytes == 190000
        return pipeline.retain(path, {"schema": "skhynix/native-architecture-public-reflection/2.0",
            "sources": [{"capture_id": value} for value in capture_ids], "trace_rows": []})

    def launch_publisher(self, configuration_reference, launcher_path):
        config = pipeline.check(configuration_reference)
        output = pipeline.linux_path(config["worker_output"])
        self.calls.append(("publish", output.parent.name))
        if self.fail_publish == "before":
            output.mkdir(parents=True)
            raise RuntimeError("interrupted native publisher")
        proposal = {"schema": "skhynix/native-architecture-reflection-proposals/1.0",
            "reflection_sha256": config["reflection_reference"]["sha256"], "proposals": []}
        proposal_ref = pipeline.retain(output / "proposals.json", proposal)
        pipeline.retain(output / "completion.json", {"thread_id": "reused" if self.reused_thread else output.parent.name,
                                                   "proposal_reference": proposal_ref})
        pipeline.retain(launcher_path, {"status": "COMPLETE", "configuration_reference": configuration_reference})
        if self.fail_publish == "after":
            raise RuntimeError("interrupted after durable native completion")

    def validate_publisher(self, configuration_reference, completion_reference, launcher_reference, reflection_reference):
        native = pipeline.check(completion_reference)
        outer = pipeline.check(launcher_reference)
        if outer["status"] != "COMPLETE" or outer["configuration_reference"] != configuration_reference:
            raise pipeline.PipelineError("outer native completion differs")
        pipeline.check(native["proposal_reference"])
        return {"thread_id": native["thread_id"], "configuration_reference": configuration_reference,
            "completion_reference": completion_reference, "launcher_reference": launcher_reference,
            "proposal_reference": native["proposal_reference"], "reflection_reference": reflection_reference}

    def ingest(self, root, proposal_reference, reflection_reference):
        identity = pipeline.digest(pipeline.canonical_bytes({"proposal": proposal_reference, "reflection": reflection_reference}))
        path = root / "learning-ingestions" / (identity + ".json")
        if path.exists():
            return pipeline.ref(path)
        self.calls.append(("ingest", proposal_reference["path"]))
        if self.fail_ingest == "before":
            raise RuntimeError("interrupted verification without durable receipt")
        result = pipeline.retain(path, {"proposal_reference": proposal_reference, "reflection_reference": reflection_reference,
            "promotions_added": int(self.promote), "failures": []})
        if self.promote:
            # Synthetic authority marker only; actual bank verification is independently tested by the memory adapter.
            (root / "catalog.json").write_bytes(pipeline.canonical_bytes({"skills": {"synthetic-verified": {}}}) + b"\n")
        if self.fail_ingest == "after":
            raise RuntimeError("interrupted after durable verification receipt")
        return result

    def freeze(self, root, path):
        self.calls.append(("freeze", None))
        if not self.promote:
            raise ValueError("The frozen bank requires at least one actually promoted Gate B skill")
        if self.fail_freeze == "before":
            raise RuntimeError("interrupted publication before complete receipt")
        bank = pipeline.retain(path, {"frozen": True, "layer_counts": {"L1_episodes": 24, "L2_nodes": 2, "L2_edges": 1, "L3_skills": 1}})
        publication = pipeline.retain(path.with_name(path.name + ".learning.json"), {"bank": bank,
            "enrollment_reference": self.definition["learning_enrollment_reference"],
            "schema": "skhynix/native-architecture-learning/1.0", "learning_version": 2,
            "operation": "PUBLISH_TRAINED_BANK", "actual_training_sources": 24})
        pipeline.retain(root / "learning-frozen.json", publication)
        if self.fail_freeze == "after":
            raise RuntimeError("interrupted after complete frozen publication")
        return {**bank, "publication_reference": publication}

    def validate_bank(self, bank_reference):
        value = pipeline.check(bank_reference)
        if not value["frozen"] or min(value["layer_counts"].values()) < 1:
            raise ValueError("bank is missing a required architecture layer")
        return value["layer_counts"]

    def prepare_evaluation(self, experiment_reference, bank_reference, cohort_root, quarantine_root, policy_path):
        self.calls.append(("prepare_evaluation", None))
        assert self.training_done == 24
        config = pipeline.check(experiment_reference)
        assert config["phase"] == "EVALUATION_RUNTIME" and config["evaluation_status"] == "EVALUATION_READY"
        return {"cohort_reference": pipeline.retain(cohort_root / "cohort.json", {"planned": 1000, "bank": bank_reference}),
            "quarantine_reference": pipeline.retain(quarantine_root / "binding.json", {"bank": bank_reference, "writes_to_bank": False}),
            "cleanup_policy_reference": pipeline.retain(policy_path, {"experiment_reference": experiment_reference})}

    def progress(self, configurations, output):
        self.calls.append(("progress", len(configurations)))
        self.progress_count += 1
        return pipeline.retain(output / f"snapshot-{self.progress_count:04d}.json", {
            "training_completed": self.training_done, "evaluation_completed": self.evaluation_done,
            "planned_training": 24, "planned_evaluation": 1000})


@pytest.fixture
def case(tmp_path, monkeypatch):
    # Synthetic native path mapping keeps all fixtures in pytest's temporary directory.
    monkeypatch.setattr(pipeline, "windows_path", lambda value: "C:/fixture" + str(value))
    monkeypatch.setattr(pipeline, "linux_path", lambda value: Path(value.removeprefix("C:/fixture")))
    targets = [{"target_id": f"train-{index:02d}", "repository": f"public/repo-{index // 2:02d}",
        "role": "TRAINING", "order_index": index} for index in range(24)]
    targets += [{"target_id": f"eval-{index:03d}", "repository": "public/evaluation", "role": "EVALUATION",
        "order_index": index} for index in range(500)]
    dataset_ref = pipeline.retain(tmp_path / "dataset.json", {"targets": targets})
    training = {"phase": "TRAINING_RUNTIME", "model": "gpt-6-astra", "authentication": "CHATGPT",
        "reasoning_effort": "ultra", "codex_binary": "C:/codex.exe", "windows_python": "C:/python.exe",
        "wsl_windows_python": "/mnt/c/python.exe", "run_root": str(tmp_path / "training-run"),
        "native_control_root": str(tmp_path / "training-native"), "dataset_manifest": dataset_ref,
        "source_root": "/frozen/source-v4", "source_sha256": {"runtime.py": "0" * 64},
        "loader_preflight_path": "/frozen/loader.json", "loader_preflight_sha256": "a" * 64,
        "image_index": {"path": "/frozen/images.json", "sha256": "b" * 64},
        "limits": {"task_requests": 120, "task_seconds": 1200}}
    training_ref = pipeline.retain(tmp_path / "training-execution.json", training)
    learning_root = tmp_path / "learning-v2"
    cohort_ref = pipeline.retain(tmp_path / "training-cohort/cohort.json", {"phase": "TRAINING",
        "scope": "FULL_FIXED_COHORT", "selected_task_count": 24, "schedule": [{"task": index} for index in range(24)],
        "experiment_reference": training_ref, "learning_root": str(learning_root)})
    enrollment_ref = pipeline.retain(learning_root / "learning-enrollment.json", {
        "learning_version": 2, "execution_references": [training_ref],
        "implementation_sha256": {"learning": pipeline.digest(b"# frozen synthetic helper, never imported\n")}})
    helpers = {}
    for name in pipeline.HELPERS:
        path = tmp_path / (name + "-frozen.py")
        path.write_bytes(b"# frozen synthetic helper, never imported\n")
        helpers[name] = pipeline.ref(path)
    definition = {"training_experiment_reference": training_ref, "training_cohort_reference": cohort_ref,
        "learning_enrollment_reference": enrollment_ref, "helper_references": helpers,
        "pipeline_root": str(tmp_path / "pipeline"), "reflection_native_root": str(tmp_path / "reflection-native"),
        "evaluation_run_root": str(tmp_path / "evaluation-run"), "evaluation_native_root": str(tmp_path / "evaluation-native"),
        "progress_root": str(tmp_path / "public-progress")}
    config = tmp_path / "pipeline-config.json"
    pipeline.create_pipeline_config(config, definition)
    operations = FakeOperations(tmp_path, definition, targets)
    driver = pipeline.Pipeline(config, operations=operations, clock=lambda: 1.0)
    return driver, operations, definition


def count(operations, name):
    return sum(call[0] == name for call in operations.calls)


def reopen(driver, operations):
    return pipeline.Pipeline(driver.path, operations=operations, clock=lambda: 1.0)


def test_preexported_batch_keeps_registered_public_path_across_publisher_resume(case):
    driver, operations, _ = case
    job = driver._plan()[0]
    exported_path = driver.root / "preexported" / "batch.json"
    public_ref = operations.export_reflection(driver.learning_root, exported_path, job["capture_ids"], 190000)
    job = {**job, "reflection_reference": public_ref}
    driver._reflect(job)
    event = driver.latest("PUBLISHED", job["repository"])
    assert event["details"]["reflection_reference"] == public_ref
    config = pipeline.check(event["details"]["configuration_reference"])
    assert pipeline.linux_path(config["reflection_reference"]["path"]) == exported_path
    launches = count(operations, "publish")
    driver._reflect(job)
    assert count(operations, "publish") == launches
    assert pipeline.ref(exported_path) == public_ref


def test_training_limit_does_not_start_reflection_or_change_fixed_population(case):
    driver, ops, _ = case
    ops.training_done = 22
    original = pipeline.ref(driver.path)
    result = driver.run(cell_limit=1)
    assert result["status"] == "IN_PROGRESS" and ops.training_done == 23
    assert count(ops, "cohort") == 1 and count(ops, "publish") == 0
    assert pipeline.ref(driver.path) == original
    assert pipeline.check(result["public_progress_reference"])["planned_training"] == 24


def test_training_only_finishes_training_and_stops_before_any_publisher(case):
    driver, ops, _ = case
    ops.training_done = 23
    result = driver.run(training_only=True)
    assert result["training_complete"] and not result["evaluation_configured"]
    assert count(ops, "publish") == count(ops, "freeze") == 0


def test_training_block_stops_without_reflection_reselection_or_evaluation(case):
    driver, ops, _ = case
    ops.training_done, ops.block_phase = 2, "TRAINING"
    result = driver.run()
    assert result["status"] == "BLOCKED" and ops.training_done == 2
    assert count(ops, "cohort") == 1 and count(ops, "inventory") == 0


def test_realistic_phase_handoff_freezes_bank_before_first_evaluation_cell(case):
    driver, ops, definition = case
    ops.training_done = 23
    result = driver.run(cell_limit=2)
    assert result["training_complete"] and result["evaluation_configured"]
    assert count(ops, "publish") == count(ops, "ingest") == 12
    assert ops.evaluation_done == 1 and count(ops, "freeze") == 1
    steps = [name for name, _ in ops.calls]
    assert steps.index("freeze") < steps.index("prepare_evaluation")
    evaluation = pipeline.read(driver.root / "evaluation-execution.json")
    training = pipeline.check(definition["training_experiment_reference"])
    for key in ("source_root", "source_sha256", "loader_preflight_path", "loader_preflight_sha256", "image_index", "dataset_manifest", "limits"):
        assert evaluation[key] == training[key]
    assert evaluation["run_root"] != training["run_root"]
    assert evaluation["frozen_bank_reference"] == driver.latest("BANK_FROZEN")["details"]["bank_reference"]


def test_resume_never_republishes_or_reverifies_completed_repository_jobs(case):
    driver, ops, _ = case
    driver.run(cell_limit=1)
    snapshots = {path: pipeline.ref(path) for path in (driver.root / "events").glob("*.json")}
    result = reopen(driver, ops).run(cell_limit=1)
    assert result["status"] == "IN_PROGRESS" and ops.evaluation_done == 2
    assert count(ops, "publish") == count(ops, "ingest") == 12 and count(ops, "freeze") == 1
    assert {path: pipeline.ref(path) for path in snapshots} == snapshots


def test_completion_requires_all1000_cells_and_keeps_published_inputs_immutable(case):
    driver, ops, _ = case
    driver.run(cell_limit=1)
    assert driver.status()["status"] != "COMPLETE"
    ops.evaluation_done = 999  # Simulate the same enrolled cohort having durably completed the intervening cells.
    result = reopen(driver, ops).run(cell_limit=1)
    assert result["status"] == "COMPLETE" and ops.evaluation_done == 1000
    prior = list(ops.calls)
    assert reopen(driver, ops).run()["status"] == "COMPLETE"
    assert ops.calls == prior


def test_zero_verified_skills_is_terminal_not_evaluation_ready(case):
    driver, ops, _ = case
    ops.promote = False
    result = driver.run()
    assert result["status"] == "TRAINING_COMPLETE_NOT_EVALUATION_READY"
    assert result["training_complete"] and not result["evaluation_configured"]
    assert count(ops, "publish") == 12 and count(ops, "freeze") == 1
    before = list(ops.calls)
    assert reopen(driver, ops).run()["status"] == result["status"]
    assert ops.calls == before and not (driver.root / "evaluation-execution.json").exists()


@pytest.mark.parametrize("timing,recoverable", [("before", False), ("after", True)])
def test_publisher_interruption_resumes_only_with_durable_bound_native_completion(case, timing, recoverable):
    driver, ops, _ = case
    ops.fail_publish = timing
    assert driver.run()["status"] == "BLOCKED"
    assert count(ops, "publish") == 1
    ops.fail_publish = None
    result = reopen(driver, ops).run(cell_limit=1)
    assert (result["status"] != "BLOCKED") is recoverable
    assert count(ops, "publish") == (12 if recoverable else 1)


@pytest.mark.parametrize("timing,recoverable", [("before", False), ("after", True)])
def test_verification_interruption_does_not_repeat_partial_gate_operations(case, timing, recoverable):
    driver, ops, _ = case
    ops.fail_ingest = timing
    assert driver.run()["status"] == "BLOCKED"
    ops.fail_ingest = None
    result = reopen(driver, ops).run(cell_limit=1)
    assert (result["status"] != "BLOCKED") is recoverable
    assert count(ops, "ingest") == (12 if recoverable else 1)


@pytest.mark.parametrize("timing,recoverable", [("before", False), ("after", True)])
def test_publication_interruption_requires_complete_frozen_bank_receipt(case, timing, recoverable):
    driver, ops, _ = case
    ops.fail_freeze = timing
    assert driver.run()["status"] == "BLOCKED"
    ops.fail_freeze = None
    result = reopen(driver, ops).run(cell_limit=1)
    assert (result["status"] != "BLOCKED") is recoverable
    assert count(ops, "freeze") == 1


def test_different_repository_reflections_cannot_share_one_native_thread(case):
    driver, ops, _ = case
    ops.reused_thread = True
    result = driver.run()
    assert result["status"] == "BLOCKED" and count(ops, "publish") == 2
    assert count(ops, "ingest") == 1 and count(ops, "freeze") == 0


def test_public_selection_prefers_earliest_green_and_preserves_all_capture_counts(case):
    _, ops, _ = case
    captures = ops.inventory(ops.learning_root)
    extra = {**captures[0], "capture_id": "earlier-completion", "kind": "COMPLETED_SUBGOAL",
             "public_test_outcome": None, "cutoff_step": 2}
    later = {**captures[0], "capture_id": "later-green", "cutoff_step": 9}
    jobs = pipeline.select_reflection_jobs(ops.targets, captures + [extra, later])
    source = jobs[0]["sources"][0]
    assert source["selected"]["cutoff_step"] == 5 and source["capture_count_retained"] == 3
    captures[0].update(kind="PUBLIC_TEST_OBSERVATION", public_test_outcome="RED")
    jobs = pipeline.select_reflection_jobs(ops.targets, captures + [extra])
    assert jobs[0]["sources"][0]["selected"]["capture_id"] == "earlier-completion"
    assert jobs[0]["sources"][0]["selection"] == "EARLIEST_COMPLETED_OR_TERMINAL"


def test_missing_public_capture_does_not_fabricate_a_second_source(case):
    driver, ops, _ = case
    original = ops.inventory
    ops.inventory = lambda root: original(root)[1:]
    result = driver.run(cell_limit=1)
    assert result["reflection_repositories_skipped"] == 1 and count(ops, "publish") == 11
    job = pipeline.read(driver.root / "reflection-plan.json")["jobs"][0]
    assert job["status"] == "INSUFFICIENT_PUBLIC_SOURCES" and len(job["capture_ids"]) == 1


@pytest.mark.parametrize("kind", ["helper", "config", "journal"])
def test_frozen_source_configuration_and_journal_tampering_fail_closed(case, kind):
    driver, ops, definition = case
    if kind == "helper":
        Path(definition["helper_references"]["publisher"]["path"]).write_bytes(b"changed helper")
        with pytest.raises(pipeline.PipelineError, match="reference changed"):
            driver.run()
    elif kind == "config":
        driver.path.write_bytes(b"{}")
        with pytest.raises(pipeline.PipelineError, match="reference changed"):
            driver.run()
    else:
        driver.record("FIXTURE", {})
        path = driver.root / "events/00000001.json"
        value = pipeline.read(path)
        value["stage"] = "PIPELINE_COMPLETE"
        path.write_bytes(pipeline.canonical_bytes(value))
        with pytest.raises(pipeline.PipelineError, match="event chain changed"):
            driver.status()
    assert count(ops, "publish") == count(ops, "cohort") == 0


def test_evaluation_block_never_returns_to_training_or_reflection(case):
    driver, ops, _ = case
    ops.block_phase = "EVALUATION"
    result = driver.run()
    assert result["status"] == "BLOCKED" and result["evaluation_configured"]
    assert count(ops, "publish") == 12 and ops.evaluation_done == 0
    assert [phase for name, phase in ops.calls if name == "cohort"] == ["EVALUATION"]


def test_explicit_bound_publisher_adoption_does_not_launch_that_repository_again(case):
    driver, ops, definition = case
    capture_ids = [row["capture_id"] for row in ops.inventory(ops.learning_root)[:2]]
    folder = ops.root / "explicit-native-adoption"
    reflection = ops.export_reflection(ops.learning_root, folder / "public-reflection.json", capture_ids, 190000)
    training = pipeline.check(definition["training_experiment_reference"])
    config = {key: training[key] for key in ("model", "authentication", "reasoning_effort", "codex_binary", "windows_python")}
    config.update(reflection_reference={"path": pipeline.windows_path(reflection["path"]), "sha256": reflection["sha256"]},
                  worker_output=pipeline.windows_path(folder / "output"), worker_cwd=pipeline.windows_path(folder / "cwd"))
    configuration_ref = pipeline.retain(folder / "publisher-config.json", config)
    ops.launch_publisher(configuration_ref, folder / "interop-completion.json")
    definition = {**definition, "pipeline_root": str(ops.root / "explicit-adoption-pipeline"),
        "adopted_reflections": [{"repository": "public/repo-00",
        "configuration_reference": configuration_ref, "completion_reference": pipeline.ref(folder / "output/completion.json"),
        "launcher_reference": pipeline.ref(folder / "interop-completion.json")}]}
    path = ops.root / "pipeline-with-explicit-adoption.json"
    pipeline.create_pipeline_config(path, definition)
    adopted = pipeline.Pipeline(path, operations=ops)
    result = adopted.run(cell_limit=1)
    assert result["status"] != "BLOCKED" and count(ops, "publish") == 12
    assert [job for name, job in ops.calls if name == "publish"].count("explicit-native-adoption") == 1


def test_unregistered_native_output_directory_is_preserved_without_retry(case):
    driver, ops, definition = case
    output = Path(definition["reflection_native_root"]) / "repo-01/output"
    output.mkdir(parents=True)
    evidence = output / "old-attempt.txt"
    evidence.write_text("retained evidence")
    result = driver.run()
    assert result["status"] == "BLOCKED" and count(ops, "publish") == 0
    assert evidence.read_text() == "retained evidence"


def test_complete_bank_receipt_from_fewer_than24_sources_cannot_start_evaluation(case):
    driver, ops, _ = case
    original = ops.freeze

    def wrong_publication(root, path):
        result = original(root, path)
        publication_path = Path(result["publication_reference"]["path"])
        value = pipeline.read(publication_path)
        value["actual_training_sources"] = 23
        publication_path.write_bytes(pipeline.canonical_bytes(value))
        result["publication_reference"] = pipeline.ref(publication_path)
        return result

    ops.freeze = wrong_publication
    result = driver.run()
    assert result["status"] == "BLOCKED" and not result["evaluation_configured"]
    assert count(ops, "prepare_evaluation") == 0


def test_pending_cleanup_can_complete_cohort_without_advancing_another_solver(case):
    driver, ops, _ = case
    original_status = ops.cohort_status
    pending = {"cleanup": True}

    def status(root):
        result = original_status(root)
        return {**result, "status": "BLOCKED"} if ops.phase(root) == "TRAINING" and pending["cleanup"] else result

    def advance(root):
        assert ops.phase(root) == "TRAINING"
        pending["cleanup"] = False
        return original_status(root)

    ops.cohort_status, ops.run_cohort = status, advance
    result = driver.run(training_only=True)
    assert result["training_complete"] and result["status"] == "IN_PROGRESS"
    assert ops.training_done == 24 and count(ops, "publish") == 0


def test_second_configuration_cannot_reuse_an_existing_pipeline_journal(case):
    driver, ops, definition = case
    driver.record("FIXTURE_COMPLETED_STAGE", {})
    alternate = ops.root / "another-valid-config.json"
    changed = {**definition, "progress_root": str(ops.root / "other-progress")}
    pipeline.create_pipeline_config(alternate, changed)
    with pytest.raises(pipeline.PipelineError, match="immutable pipeline evidence"):
        pipeline.Pipeline(alternate, operations=ops)
    assert ops.calls == []
    assert len(driver.events()) == 1


def test_existing_unbound_journal_cannot_be_adopted_implicitly(case):
    driver, ops, definition = case
    orphan_root = ops.root / "orphan-pipeline"
    pipeline.retain(orphan_root / "events/00000001.json", {"prior": "preserved"})
    alternate = ops.root / "orphan-config.json"
    pipeline.create_pipeline_config(alternate, {**definition, "pipeline_root": str(orphan_root)})
    with pytest.raises(pipeline.PipelineError, match="no matching immutable root binding"):
        pipeline.Pipeline(alternate, operations=ops)
    assert not (orphan_root / "pipeline-binding.json").exists()
    assert ops.calls == []


def test_different_controller_file_cannot_claim_frozen_pipeline_source(case):
    driver, ops, _ = case
    foreign = ops.root / "different-pipeline.py"
    foreign.write_bytes(b"# another controller implementation\n")
    value = {**driver.config, "pipeline_source_reference": pipeline.ref(foreign)}
    with pytest.raises(pipeline.PipelineError, match="executing pipeline source differs"):
        pipeline._validate_config(value)
    assert ops.calls == []


def test_frozen_operations_retains_one_controller_per_exact_cohort_root(tmp_path):
    opened = []

    class Runner:
        def status(self):
            return self

        def run(self, *, cell_limit):
            assert cell_limit == 1
            return self

    def open_runner(root):
        opened.append(root)
        return Runner()

    operations = pipeline.FrozenOperations.__new__(pipeline.FrozenOperations)
    operations.cohorts = {}
    operations.modules = {"cohort": SimpleNamespace(_open=open_runner)}
    first = operations.cohort_status(tmp_path / "training")
    assert operations.run_cohort(tmp_path / "training") is first
    assert operations.run_cohort(tmp_path / "training") is first
    assert operations.cohort_status(tmp_path / "evaluation") is not first
    assert opened == [tmp_path / "training", tmp_path / "evaluation"]
    with pytest.raises(pipeline.PipelineError, match="canonical absolute"):
        operations.run_cohort(tmp_path / "training" / ".." / "evaluation")


def test_new_evaluation_controller_keeps_real_quarantine_hook_when_cached(tmp_path):
    calls = []
    hook = lambda *args: calls.append(args)
    experiment = pipeline.retain(tmp_path / "execution.json", {"run_root": str(tmp_path / "evaluation")})
    bank = pipeline.retain(tmp_path / "bank.json", {"immutable": True})
    root = tmp_path / "evaluation/cohort"

    def create(path, **kwargs):
        assert kwargs["quarantine_root"] == tmp_path / "quarantine"
        assert kwargs["quarantine_hook"] is hook
        pipeline.retain(path / "cohort.json", {"enrolled": 1000})
        return SimpleNamespace(schedule=list(range(1000)), quarantine_hook=kwargs["quarantine_hook"])

    operations = pipeline.FrozenOperations.__new__(pipeline.FrozenOperations)
    operations.cohorts = {}
    operations.modules = {
        "cohort": SimpleNamespace(CohortRunner=SimpleNamespace(create=create)),
        "quarantine": SimpleNamespace(make_quarantine_hook=lambda path: hook,
            initialize_quarantine=lambda path, **kwargs: pipeline.retain(path / "binding.json", kwargs)),
        "cleanup": SimpleNamespace(create_cleanup_policy=lambda path, **kwargs: pipeline.retain(path, kwargs))}
    operations.prepare_evaluation(experiment, bank, root, tmp_path / "quarantine", tmp_path / "cleanup.json")
    runner = operations._cohort(root)
    runner.quarantine_hook("synthetic public cell")
    assert calls == [("synthetic public cell",)]


@pytest.mark.parametrize("fails", [False, True])
def test_helper_import_restores_runtime_path_even_after_import_failure(tmp_path, fails):
    path = tmp_path / "publisher.py"
    path.write_text("import sys\nsys.path[:0] = ['/foreign/publisher/src', '/foreign/publisher/scripts']\n" +
                    ("raise RuntimeError('failed helper import')\n" if fails else "marker = 'loaded'\n"))
    prior_paths = list(sys.path)
    module_name = "trimem_skhynix_architecture_fixture_path_test"
    try:
        if fails:
            with pytest.raises(RuntimeError, match="failed helper"):
                pipeline.import_frozen_helper("fixture_path_test", pipeline.ref(path), prior_paths)
            assert module_name not in sys.modules
        else:
            assert pipeline.import_frozen_helper("fixture_path_test", pipeline.ref(path), prior_paths).marker == "loaded"
        assert sys.path == prior_paths
    finally:
        sys.path[:] = prior_paths
        sys.modules.pop(module_name, None)


@pytest.mark.parametrize("failure", [None, "foreign_cached_module", "wrong_bytes", "entrypoint"])
def test_lazy_runtime_imports_bind_exact_source_and_official_entrypoint(tmp_path, monkeypatch, failure):
    source = tmp_path / "source-v4"
    entrypoint = source / "scripts/trimem_swe_bench_entrypoint.py"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("# frozen entrypoint\n")
    modules, hashes = {}, {}
    for name in pipeline.RUNTIME_IMPORTS:
        path = source / "scripts" / (name + ".py")
        path.write_text("# frozen runtime\n")
        hashes[path.relative_to(source).as_posix()] = pipeline.digest(path.read_bytes())
        modules[name] = SimpleNamespace(__file__=str(path), SWE_ENTRYPOINT=entrypoint)
    if failure == "foreign_cached_module":
        foreign = tmp_path / "publisher-copy.py"
        foreign.write_text("# frozen runtime\n")  # Identical bytes still have a different loader identity.
        modules["trimem_skhynix_architecture_environment"].__file__ = str(foreign)
    elif failure == "wrong_bytes":
        Path(modules["trimem_skhynix_environment"].__file__).write_text("changed runtime\n")
    elif failure == "entrypoint":
        modules["trimem_official_grader"].SWE_ENTRYPOINT = tmp_path / "publisher/scripts/trimem_swe_bench_entrypoint.py"
    monkeypatch.setattr(pipeline, "sys", SimpleNamespace(modules=modules))
    if failure:
        with pytest.raises(pipeline.PipelineError, match="frozen|entrypoint"):
            pipeline.validate_runtime_imports({"source_root": str(source), "source_sha256": hashes})
    else:
        evidence = pipeline.validate_runtime_imports({"source_root": str(source), "source_sha256": hashes})
        assert set(evidence) == set(pipeline.RUNTIME_IMPORTS)


def superseding_driver(case):
    old, operations, definition = case
    old.record("PIPELINE_BLOCKED", {"reason": "synthetic zero-action infrastructure failure"})
    definition = {**definition, "pipeline_root": str(operations.root / "pipeline-v2"),
        "supersedes": {"configuration_reference": old.reference,
            "event_tail_reference": pipeline.ref(old.root / "events/00000001.json")}}
    path = operations.root / "pipeline-v2-config.json"
    pipeline.create_pipeline_config(path, definition)
    return old, pipeline.Pipeline(path, operations=operations), definition


def test_explicit_supersession_continues_same_cohort_and_preserves_old_journal(case):
    old, new, definition = superseding_driver(case)
    old_refs = [pipeline.ref(path) for path in (old.root / "events").glob("*.json")]
    new.operations.training_done = 23
    assert new.run(training_only=True)["training_complete"]
    receipt = new.latest("CONTROLLER_SUPERSESSION")
    assert receipt["details"]["predecessor"] == definition["supersedes"]
    assert new.training_cohort == old.training_cohort
    assert [pipeline.ref(path) for path in (old.root / "events").glob("*.json")] == old_refs
    assert count(new.operations, "publish") == 0


def test_supersession_rejects_appended_predecessor_history_before_any_work(case):
    old, new, _ = superseding_driver(case)
    old.record("COHORT_ADVANCE_STARTED", {"phase": "TRAINING"})
    with pytest.raises(pipeline.PipelineError, match="event tail changed"):
        new.run(training_only=True)
    assert new.operations.calls == []


def test_supersession_refuses_a_running_predecessor(case):
    old, new, _ = superseding_driver(case)
    with pipeline.locked(old.root / "run.lock"):
        with pytest.raises(pipeline.PipelineError, match="still running"):
            new.run(training_only=True)
    assert new.operations.calls == []


def test_supersession_cannot_adopt_reflection_stage_or_change_training_identity(case):
    old, new, definition = superseding_driver(case)
    old.record("REFLECTION_PLAN", {"reference": {}})
    definition["supersedes"]["event_tail_reference"] = pipeline.ref(old.root / "events/00000002.json")
    with pytest.raises(pipeline.PipelineError, match="before any reflection"):
        pipeline.create_pipeline_config(new.operations.root / "forbidden.json", definition)
    changed = {**new.config, "training_experiment_reference": {"path": "/foreign", "sha256": "a" * 64}}
    with pytest.raises(pipeline.PipelineError, match="training enrollment"):
        pipeline.validate_predecessor(changed)


@pytest.fixture(params=["ultra", "high"])
def native_proof(tmp_path, request):
    def mapper(value):
        relative = PureWindowsPath(value).relative_to("C:/fixture")
        return tmp_path.joinpath(*relative.parts)

    public = {"schema": "skhynix/native-architecture-public-reflection/2.0", "sources": [], "trace_rows": []}
    reflection_ref = pipeline.retain(tmp_path / "public.json", public)
    config = {"model": "gpt-6-astra", "authentication": "CHATGPT", "reasoning_effort": request.param,
        "codex_binary": "C:/codex.exe", "windows_python": "C:/python.exe", "worker_cwd": "C:/fixture/cwd",
        "worker_output": "C:/fixture/output", "reflection_reference": {"path": "C:/fixture/public.json", "sha256": reflection_ref["sha256"]}}
    config_ref = pipeline.retain(tmp_path / "config.json", config)
    publisher_ref = pipeline.ref(Path(publisher.__file__).resolve())
    proposal = {"schema": "skhynix/native-architecture-reflection-proposals/1.0", "reflection_sha256": reflection_ref["sha256"], "proposals": []}
    response = pipeline.canonical_bytes(proposal).decode()
    events = [{"type": "thread.started", "thread_id": "actual-fresh-thread"}, {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": response}}, {"type": "turn.completed"}]
    output = tmp_path / "output"
    output.mkdir()
    raw = b"\n".join(pipeline.canonical_bytes(event) for event in events) + b"\n"
    (output / "events.jsonl").write_bytes(raw)
    prompt = publisher.PREFIX.encode() + pipeline.canonical_bytes({"reflection_sha256": reflection_ref["sha256"], "public_training_export": public})
    (output / "prompt.txt").write_bytes(prompt)
    launch = {"schema": "skhynix/native-reflection-launch/1.0", "configuration_sha256": config_ref["sha256"],
        "implementation_sha256": publisher_ref["sha256"], "reflection_reference": config["reflection_reference"],
        "reflection_sha256": reflection_ref["sha256"], "prompt_sha256": pipeline.digest(prompt), "prompt_bytes": len(prompt),
        "command_sha256": pipeline.digest(pipeline.canonical_bytes(publisher.publisher_command(config, PureWindowsPath(config["worker_output"])))),
        "fresh_session": True, "requested_model": "gpt-6-astra", "reasoning_effort": request.param, "separate_model_api_client_calls": 0}
    launch_ref = pipeline.retain(output / "launch.json", launch)
    proposal_ref = pipeline.retain(output / "proposals.json", proposal)
    complete = {"schema": "skhynix/native-reflection-completion/1.0", "thread_id": "actual-fresh-thread",
        "events_sha256": pipeline.digest(raw), "configuration_sha256": config_ref["sha256"],
        "reflection_sha256": reflection_ref["sha256"], "response_text_sha256": pipeline.digest(response.encode()),
        "proposal_sha256": proposal_ref["sha256"], "separate_model_api_client_calls": 0, "validation_required": True,
        "gate_b_promotions": 0, "proposal_count": 0,
        "launch_reference": {"path": "C:/fixture/output/launch.json", "sha256": launch_ref["sha256"]},
        "proposal_reference": {"path": "C:/fixture/output/proposals.json", "sha256": proposal_ref["sha256"]}}
    complete_ref = pipeline.retain(output / "completion.json", complete)
    outer_ref = pipeline.retain(tmp_path / "interop.json", {"schema": "skhynix/pipeline-native-launch/1.0", "status": "COMPLETE",
        "returncode": 0, "configuration_reference": config_ref, "publisher_reference": publisher_ref, "output_references": {}})
    args = [config_ref, complete_ref, outer_ref]
    kwargs = {"reflection_reference": reflection_ref, "publisher_reference": publisher_ref, "publisher_module": publisher, "mapper": mapper}
    return args, kwargs, output


def test_real_native_proof_validation_binds_exact_actual_response_and_windows_paths(native_proof):
    args, kwargs, output = native_proof
    result = pipeline.validate_native_publication(*args, **kwargs)
    assert result["thread_id"] == "actual-fresh-thread"
    assert result["proposal_reference"] == pipeline.ref(output / "proposals.json")


@pytest.mark.parametrize("failure", ["prompt", "events", "proposal", "outer_failure", "source", "native_failure", "completion_thread", "effort"])
def test_native_receipt_cannot_certify_changed_output_or_failed_launcher(native_proof, failure):
    args, kwargs, output = native_proof
    if failure in {"prompt", "events", "proposal"}:
        file = {"prompt": "prompt.txt", "events": "events.jsonl", "proposal": "proposals.json"}[failure]
        (output / file).write_bytes(b"changed bytes")
    elif failure == "outer_failure":
        value = pipeline.check(args[2])
        value["returncode"] = 1
        Path(args[2]["path"]).write_bytes(pipeline.canonical_bytes(value))
        args[2] = pipeline.ref(args[2]["path"])
    elif failure == "source":
        kwargs["publisher_reference"] = {**kwargs["publisher_reference"], "sha256": "f" * 64}
    elif failure == "native_failure":
        pipeline.retain(output / "failure.json", {"reason": "REFLECTION_TIMEOUT"})
    elif failure == "effort":
        launch = pipeline.read(output / "launch.json")
        launch["reasoning_effort"] = "high" if launch["reasoning_effort"] == "ultra" else "ultra"
        (output / "launch.json").write_bytes(pipeline.canonical_bytes(launch))
        complete = pipeline.read(output / "completion.json")
        complete["launch_reference"]["sha256"] = pipeline.ref(output / "launch.json")["sha256"]
        (output / "completion.json").write_bytes(pipeline.canonical_bytes(complete))
        args[1] = pipeline.ref(output / "completion.json")
    else:
        value = pipeline.check(args[1])
        value["thread_id"] = "foreign-thread"
        (output / "completion.json").write_bytes(pipeline.canonical_bytes(value))
        args[1] = pipeline.ref(output / "completion.json")
    with pytest.raises((pipeline.PipelineError, ValueError)):
        pipeline.validate_native_publication(*args, **kwargs)


def high_transition(case, *, predecessor=None):
    original, old_ops, original_definition = case
    old = predecessor or original
    if not old.events():
        old.record("PIPELINE_BLOCKED", {"reason": "synthetic forward-only user settings transition"})
    old_training = original_definition["training_experiment_reference"]
    training = {**pipeline.check(old_training), "reasoning_effort": "high", "reasoning_source": "user request",
        "prelaunch_revision": "v6"}
    new_training = pipeline.retain(old_ops.root / "training-execution-v6.json", training)
    old_enrollment = original_definition["learning_enrollment_reference"]
    enrollment = {**pipeline.check(old_enrollment), "execution_references": [old_training, new_training]}
    new_enrollment = pipeline.retain(old_ops.root / "learning-v3/learning-enrollment.json", enrollment)
    # Synthetic declaration for pure pipeline binding tests; real journal/partition proof is audited by cohort tests.
    declaration = {"schema": "skhynix/architecture-reasoning-effort-transition/1.0",
        "operation": "ADOPT_FORWARD_REASONING_EFFORT", "cohort_reference": original_definition["training_cohort_reference"],
        "previous_experiment_reference": old_training, "experiment_reference": new_training,
        "previous_learning_enrollment_reference": old_enrollment, "learning_enrollment_reference": new_enrollment,
        "controller_source_reference": original_definition["helper_references"]["cohort"],
        "preserved_ultra_ordinals": list(range(1, 9)), "high_ordinals": list(range(9, 25)),
        "model_calls": 0, "official_grader_runs": 0, "outcome_retries": False}
    transition_ref = pipeline.retain(old.training_cohort / "reasoning-effort-transition.json", declaration)
    definition = {**original_definition, "pipeline_root": str(old_ops.root / "pipeline-high"),
        "training_experiment_reference": new_training, "learning_enrollment_reference": new_enrollment,
        "execution_transition_reference": transition_ref,
        "supersedes": {"configuration_reference": old.reference,
            "event_tail_reference": pipeline.ref(old.root / "events" / f"{len(old.events()):08d}.json")}}
    path = old_ops.root / "pipeline-high.json"
    pipeline.create_pipeline_config(path, definition)
    operations = FakeOperations(old_ops.root, definition, old_ops.targets)
    operations.progress_count = old.operations.progress_count  # Real exporter uses fresh timestamped snapshot names.
    return pipeline.Pipeline(path, operations=operations), operations, definition


def test_forward_high_transition_keeps_training_history_and_uses_high_for_all_future_phases(case):
    old, old_operations, _ = case
    driver, operations, definition = high_transition(case)
    old_history = [pipeline.ref(path) for path in (old.root / "events").glob("*.json")]
    operations.training_done = 8
    assert driver.run(cell_limit=1, training_only=True)["status"] == "IN_PROGRESS"
    assert operations.training_done == 9 and count(operations, "publish") == 0
    assert driver.training_cohort == old.training_cohort
    assert count(operations, "cohort") == 1 and count(old_operations, "cohort") == 0
    assert ("progress", 2) in operations.calls
    operations.training_done = 24  # Synthetic accounting for the same enrolled remaining training tasks.
    result = driver.run(cell_limit=1)
    assert result["evaluation_configured"] and count(operations, "publish") == 12
    configs = list(Path(definition["reflection_native_root"]).glob("repo-*/publisher-config.json"))
    assert len(configs) == 12 and all(pipeline.read(path)["reasoning_effort"] == "high" for path in configs)
    evaluation = pipeline.read(driver.root / "evaluation-execution.json")
    assert evaluation["reasoning_effort"] == "high"
    assert evaluation["limits"] == old.training["limits"] and evaluation["source_sha256"] == old.training["source_sha256"]
    assert ("progress", 3) in operations.calls
    assert [pipeline.ref(path) for path in (old.root / "events").glob("*.json")] == old_history


def test_high_transition_accepts_only_an_exact_prior_controller_supersession(case):
    old, middle, _ = superseding_driver(case)
    middle.operations.training_done = 8
    middle.run(cell_limit=1, training_only=True)
    assert middle.latest("CONTROLLER_SUPERSESSION")
    driver, operations, _ = high_transition(case, predecessor=middle)
    operations.training_done = 9
    assert driver.run(cell_limit=1, training_only=True)["status"] == "IN_PROGRESS"
    assert operations.training_done == 10 and count(operations, "publish") == 0


@pytest.mark.parametrize("failure", ["budget", "bank_authority", "missing_transition", "opposite_effort", "other_cohort"])
def test_forward_transition_cannot_change_population_budgets_or_learning_authority(case, failure):
    driver, operations, _ = high_transition(case)
    config = deepcopy(driver.config)
    transition = pipeline.check(config["execution_transition_reference"])
    if failure == "missing_transition":
        del config["execution_transition_reference"]
    elif failure in {"budget", "opposite_effort"}:
        path = Path(config["training_experiment_reference"]["path"])
        value = pipeline.read(path)
        if failure == "budget":
            value["limits"]["task_requests"] += 1
        else:
            value["reasoning_effort"] = "ultra"
        path.write_bytes(pipeline.canonical_bytes(value))
        config["training_experiment_reference"] = transition["experiment_reference"] = pipeline.ref(path)
    elif failure == "bank_authority":
        path = Path(config["learning_enrollment_reference"]["path"])
        value = pipeline.read(path)
        value["additional_training_source"] = "foreign-task"
        path.write_bytes(pipeline.canonical_bytes(value))
        config["learning_enrollment_reference"] = transition["learning_enrollment_reference"] = pipeline.ref(path)
    else:
        transition["cohort_reference"] = {"path": "/foreign/cohort.json", "sha256": "f" * 64}
    if failure != "missing_transition":
        path = Path(config["execution_transition_reference"]["path"])
        path.write_bytes(pipeline.canonical_bytes(transition))
        config["execution_transition_reference"] = pipeline.ref(path)
    with pytest.raises(pipeline.PipelineError, match="transition|authority|training cohort"):
        pipeline._validate_config(config)
    assert operations.calls == []
