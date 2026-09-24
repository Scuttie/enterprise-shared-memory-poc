"""Synthetic native/broker/public-grade receipts; no execution or private reads."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from enterprise_memory.trimem.accounting import canonical_bytes, sha256_bytes
from enterprise_memory.trimem.skill_memory import SkillMemoryStore
from trimem_skhynix_architecture_broker import ArchitectureBroker
from trimem_skhynix_architecture_run import prompt_prefix
import trimem_skhynix_architecture_quarantine as quarantine
import trimem_skhynix_architecture_memory as memory
from test_trimem_skhynix_architecture_memory import trained


def write(path, value, *, sidecar=False):
    memory._write(path, value, fresh=True)
    if sidecar: path.with_suffix(".sha256").write_text(memory._hash(value) + "\n")
    return memory._ref(path)


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    values, target, _, frozen, _ = trained(tmp_path / "training", skills=True)
    bank_ref = {key: frozen[key] for key in ("path", "sha256")}
    targets = [{"target_id": value.task_id, "instance_id": value.task_id, "role": "TRAINING" if value is not target else "EVALUATION",
        "repository": value.repository, "base_commit": value.commit,
        "instruction_sha256": sha256_bytes(value.instruction.encode())} for value in [*values, target]]
    dataset = {"targets": targets}
    dataset_ref = write(tmp_path / "dataset.json", dataset)
    image_ref = write(tmp_path / "images.json", {})
    preflight_ref = write(tmp_path / "preflight.json", {"public_fixture": True})
    config = {"schema": "skhynix/pdf-architecture-execution/1.0", "phase": "EVALUATION_RUNTIME", "org_id": target.org_id,
        "model": "gpt-6-astra", "dataset_manifest": dataset_ref, "image_index": image_ref,
        "source_root": str(tmp_path), "source_sha256": {}, "run_root": str(tmp_path / "run"),
        "native_control_root": str(tmp_path / "native"), "training_owner_by_instance": {},
        "loader_preflight_path": preflight_ref["path"], "loader_preflight_sha256": preflight_ref["sha256"]}
    execution_ref = write(tmp_path / "execution.json", config, sidecar=True)
    def public_rows(path, *, expected_sha256, role):
        assert {"path": path, "sha256": expected_sha256} == dataset_ref and role == "EVALUATION"
        return [targets[-1]], {target.task_id: {"problem_statement": target.instruction}}, dataset
    monkeypatch.setattr(quarantine, "load_architecture_rows", public_rows)
    monkeypatch.setattr(quarantine, "EVALUATION_COUNT", 1)
    root = tmp_path / "quarantine"
    quarantine.initialize_quarantine(root, execution_reference=execution_ref, bank_reference=bank_ref)
    return SimpleNamespace(root=root, tmp=tmp_path, target=target, targets=targets,
        config=config, execution_ref=execution_ref, bank_ref=bank_ref)


def cell(ctx, arm="PDF_MEMORY", *, complete=True, green=False, empty=False, resolved=False):
    public = ctx.target.public_payload()
    directory = Path(ctx.config["run_root"]) / "cells" / "EVALUATION" / ctx.target.task_id / arm
    directory.mkdir(parents=True)
    def execute(tool, arguments):
        if tool == "read_file":
            return {"path": "source.py", "content": "def extension(path): return path\n"}
        if tool == "run_command":
            return {"stdout": "1 passed" if green else "AssertionError\n1 failed", "stderr": "", "exit_code": 0 if green else 1,
                "timed_out": False, "output_truncated": False}
        raise AssertionError(tool)
    owner = "architecture-contributor-1"
    callback = (memory.make_recall_callback(ctx.bank_ref["path"], ctx.bank_ref["sha256"], org_id=ctx.target.org_id, owner_user_id=owner)
        if ctx.bank_ref is not None else None)
    bank_sha = ctx.bank_ref["sha256"] if ctx.bank_ref is not None else quarantine.EMPTY_BANK_SHA
    broker = ArchitectureBroker.create(directory / "broker", task_public=public, arm=arm,
        workspace=SimpleNamespace(execute=execute, patch=lambda: "PUBLIC_EVALUATION_PATCH"),
        configuration_sha256=memory._hash(ctx.config), bank_sha256=bank_sha,
        memory_callback=callback, tool_schema={"public_tools": ["read_file", "run_command"]}, clock=lambda: 1789360000.0)
    cell_value = {"schema": ctx.config["schema"], "phase": "EVALUATION", "arm": arm, "task_public": public,
        "org_id": ctx.target.org_id, "owner_user_id": owner, "experiment_config": ctx.execution_ref["path"],
        "bank_reference": ctx.bank_ref, "bank_sha256": bank_sha, "target": ctx.targets[-1],
        "broker_root": str(directory / "broker")}
    cell_path = directory / "cell.json"
    write(cell_path, cell_value, sidecar=True)
    audit_workers = []
    native_root = Path(ctx.config["native_control_root"]) / "EVALUATION" / ctx.target.task_id / arm
    def launch(worker, number):
        issued = broker.issue_handoff(worker)
        folder = native_root / ("worker-" + str(number).zfill(3))
        folder.mkdir(parents=True)
        prompt = prompt_prefix("EVALUATION") + canonical_bytes(issued["packet"])
        (folder / "prompt.txt").write_bytes(prompt)
        write(folder / "packet.json", issued["packet"])
        native_launch = {"schema": "native-launch-fixture", "requested_model": "gpt-6-astra", "fresh_session": True,
            "resume_or_fork_used": False, "packet_sha256": issued["packet_sha256"], "prompt_sha256": sha256_bytes(prompt), "prompt_bytes": len(prompt)}
        write(folder / "output" / "launch.json", native_launch)
        thread = "fixture-thread-" + arm + "-" + worker
        admitted = broker.admit_worker(worker, issued["packet_sha256"], {"thread_id": thread, "fork_turns": "none", "fresh_session": True,
            "requested_model": "gpt-6-astra", "launch_evidence_sha256": memory._hash(native_launch)})
        events = canonical_bytes({"type": "thread.started", "thread_id": thread}) + b"\n" + canonical_bytes({"type": "turn.completed", "usage": {}}) + b"\n"
        (folder / "output" / "events.jsonl").write_bytes(events)
        completion = {"thread_id": thread, "admitted": True, "outside_broker_tool_events": [], "errors": [], "transport_errors": [],
            "timed_out": False, "exit_code": 0, "events_sha256": sha256_bytes(events)}
        reference = write(folder / "output" / "completion.json", completion)
        audit_workers.append({"number": number, "thread_id": thread, "completion_sha256": reference["sha256"],
            "events_sha256": sha256_bytes(events), "outcome": "COMPLETE"})
        return admitted["admission_token"]
    token = launch("planner", 1)
    if empty:
        assert broker.action("planner", token, {"request_id": "submit", "op": "submit", "summary": "No justified repository action found"})["ok"]
    else:
        assert broker.action("planner", token, {"request_id": "plan", "op": "plan_subgoals", "subgoals": [
            {"node_id": "normalize", "objective": "normalize filename extension", "operation": "normalize filename extension"}]})["ok"]
        assert broker.action("planner", token, {"request_id": "activate", "op": "activate_subgoal", "node_id": "normalize"})["ok"]
        token = launch("solver", 2)
        assert broker.action("solver", token, {"request_id": "read", "op": "tool", "name": "read_file", "arguments": {"path": "source.py"}})["ok"]
        assert broker.action("solver", token, {"request_id": "test", "op": "tool", "name": "run_command", "arguments": {"argv": ["python", "-m", "pytest", "tests/test_extension.py"]}})["ok"]
        if complete:
            assert broker.action("solver", token, {"request_id": "complete", "op": "complete_subgoal", "summary": "Observed public test outcome", "evidence_steps": [4]})["ok"]
        assert broker.action("solver", token, {"request_id": "submit", "op": "submit", "summary": "Public partial evaluation attempt"})["ok"]
    status = broker.status()
    audit = {"schema": "skhynix/architecture-execution-audit/1.0", "task_id": public["task_id"], "arm": arm,
        "event_tail_sha256": status["event_tail_sha256"], "patch_sha256": status["submission"]["patch_sha256"],
        "configuration_sha256": memory._hash(ctx.config), "workers": audit_workers, "errors": [], "passed": True}
    audit_ref = write(directory / "execution-audit.json", audit)
    result = {"schema": ctx.config["schema"], "phase": "EVALUATION", "arm": arm, "task_id": public["task_id"],
        "official": True, "resolved": resolved, "grader_status": "success", "grader_id": "official-fixture",
        "container_digest": "sha256:" + "c" * 64, "grader_wall_time_ms": 100, "patch_sha256": status["submission"]["patch_sha256"],
        "patch_bytes": status["submission"]["patch_utf8_bytes"], "event_tail_sha256": status["event_tail_sha256"], "broker_status": status,
        "grader_private_sha256": "f" * 64, "experiment_sha256": memory._hash(ctx.config), "bank_sha256": bank_sha,
        "execution_audit_sha256": audit_ref["sha256"], "requested_model": "gpt-6-astra", "separate_model_api_client_calls": 0}
    write(directory / "public-result.json", result)
    (directory / "grader-private.json").write_text("PRIVATE GRADER CONTENT MUST NEVER BE READ")
    return cell_path, result, native_root


@pytest.mark.parametrize("arm,green,resolved", [("BASELINE", False, False), ("BASELINE", True, True), ("PDF_MEMORY", False, True), ("PDF_MEMORY", True, False)])
def test_actual_public_postgrade_hook_isolates_quarantine_and_ignores_grade_for_episode_success(inputs, monkeypatch, arm, green, resolved):
    path, result, _ = cell(inputs, arm, green=green, resolved=resolved)
    original_open = Path.open
    def public_only(path, *args, **kwargs):
        if path.name == "grader-private.json": pytest.fail("Quarantine attempted to read private grading payload")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", public_only)
    before = memory._file_hash(inputs.bank_ref["path"])
    hook = quarantine.make_quarantine_hook(inputs.root)
    mirror = hook(path, result, inputs.tmp / (arm + "-receipts"))
    wrapper = memory._read(mirror["path"])
    receipt = memory._read(wrapper["capture_receipt"]["path"])
    assert wrapper["operation"] == "COHORT_CAPTURE" and receipt["schema"] == quarantine.SCHEMA
    assert receipt["operation"] == "CAPTURE_EVALUATION_CELL" and receipt["failures"] == []
    assert receipt["bank_reference"] == inputs.bank_ref
    assert receipt["admitted_to_frozen_bank"] is False and receipt["public_grade_reference"]["path"] == str(path.parent / "public-result.json")
    assert receipt["source_execution_observed"] and receipt["audit_subgoals"][0]["semantic_completion"]
    assert hook(path, result, inputs.tmp / (arm + "-receipts")) == mirror
    assert memory._file_hash(inputs.bank_ref["path"]) == before
    if arm == "BASELINE":
        assert receipt["status"] == "BASELINE_AUDIT_ONLY" and receipt["memory_records_written"] == 0
        assert receipt["captures"] == receipt["quarantine_references"] == []
        assert not (inputs.root / "private").exists()
    else:
        assert receipt["status"] == "CAPTURED" and receipt["memory_records_written"] == 1
        assert receipt["captures"][0]["receipt"]["succeeded"] == green
        assert receipt["captures"][0]["receipt"]["phase"] == "EVALUATION_QUARANTINE"
        authority_ref = next(ref for ref in receipt["quarantine_references"] if ref["path"].endswith("authority.sqlite3"))
        with memory._ReadOnlyStore(authority_ref["path"]) as store:
            episode = receipt["captures"][0]["receipt"]["episode_id"]
            assert store.get_episode(episode, org_id=inputs.target.org_id, user_id="architecture-contributor-1")
            assert store.get_episode(episode, org_id=inputs.target.org_id, user_id="other-owner") is None
        private = Path(authority_ref["path"]).parent
        with pytest.raises(memory.ArchitectureMemoryError, match="Frozen"):
            memory.freeze_training_bank(private, inputs.tmp / "forbidden-bank.json")
        bank = memory.load_frozen_bank(inputs.bank_ref["path"], inputs.bank_ref["sha256"])
        try:
            assert bank.store._db.execute("SELECT COUNT(*) FROM memory_records WHERE record_id=?", (episode,)).fetchone()[0] == 0
        finally: bank.close()


@pytest.mark.parametrize("arm", ["BASELINE", "PDF_MEMORY"])
def test_legitimate_empty_evaluation_is_audited_without_fabricated_memory(inputs, arm):
    path, result, _ = cell(inputs, arm, empty=True)
    receipt = memory._read(quarantine.capture_cell(inputs.root, path, result)["path"])
    assert receipt["status"] == ("BASELINE_AUDIT_ONLY" if arm == "BASELINE" else "NO_PUBLIC_ATTEMPTS")
    assert receipt["memory_records_written"] == 0 and receipt["source_execution_observed"]
    assert receipt["captures"] == receipt["quarantine_references"] == []


def test_terminal_active_partial_subgoal_is_retained_as_partial(inputs):
    path, result, _ = cell(inputs, complete=False)
    receipt = memory._read(quarantine.capture_cell(inputs.root, path, result)["path"])
    assert receipt["status"] == "CAPTURED" and not receipt["captures"][0]["semantic_completion"]
    capture_ref = next(ref for ref in receipt["quarantine_references"] if "/captures/" in ref["path"])
    assert "not completed" in memory._read(capture_ref["path"])["summary"]


@pytest.mark.parametrize("change", ["official", "task", "arm", "bank", "patch", "tail", "config", "privatefield", "owner", "audit", "nativeevents", "nativeprompt", "launchflags", "missingnative", "state", "pending"])
def test_unbound_grade_or_declared_audit_flags_cannot_create_eval_memory(inputs, change):
    path, result, native = cell(inputs)
    if change in ("official", "task", "arm", "bank", "patch", "tail", "config", "privatefield"):
        if change == "official": result["official"] = False
        if change == "task": result["task_id"] = "other-target"
        if change == "arm": result["arm"] = "BASELINE"
        if change == "bank": result["bank_sha256"] = "f" * 64
        if change == "patch": result["patch_sha256"] = "f" * 64
        if change == "tail": result["event_tail_sha256"] = "f" * 64
        if change == "config": result["experiment_sha256"] = "f" * 64
        if change == "privatefield": result["test_patch"] = "forbidden"
        memory._write(path.parent / "public-result.json", result)
    if change == "owner":
        value = memory._read(path)
        value["owner_user_id"] = "another-owner"
        memory._write(path, value)
        path.with_suffix(".sha256").write_text(memory._hash(value) + "\n")
    if change == "audit":
        audit_path = path.parent / "execution-audit.json"
        audit = memory._read(audit_path)
        audit["workers"] = []
        memory._write(audit_path, audit)
        result["execution_audit_sha256"] = memory._file_hash(audit_path)
        memory._write(path.parent / "public-result.json", result)
    if change == "nativeevents":
        with (native / "worker-001" / "output" / "events.jsonl").open("ab") as stream: stream.write(b"{}\n")
    if change == "nativeprompt":
        with (native / "worker-001" / "prompt.txt").open("ab") as stream: stream.write(b"extra context")
    if change == "launchflags":
        launch_path = native / "worker-001" / "output" / "launch.json"
        launch = memory._read(launch_path)
        launch["fresh_session"] = False
        memory._write(launch_path, launch)
    if change == "missingnative": (native / "worker-001" / "output" / "events.jsonl").unlink()
    if change == "state":
        state_path = path.parent / "broker" / "state.json"
        state = memory._read(state_path)
        state["actions"] += 1
        memory._write(state_path, state)
    if change == "pending": write(path.parent / "broker" / "pending.json", {"phase": "FINISHED"})
    if change == "privatefield":
        with pytest.raises(Exception): quarantine.capture_cell(inputs.root, path, result)
    else:
        receipt = memory._read(quarantine.capture_cell(inputs.root, path, result)["path"])
        assert receipt["status"] == "INVALID_SOURCE" and receipt["failures"]
        assert receipt["memory_records_written"] == 0 and receipt["captures"] == []
    assert not (inputs.root / "private").exists()


def test_quarantine_retry_rechecks_original_public_sources_and_private_record_hashes(inputs):
    path, result, _ = cell(inputs)
    reference = quarantine.capture_cell(inputs.root, path, result)
    receipt = memory._read(reference["path"])
    authority = next(ref for ref in receipt["quarantine_references"] if ref["path"].endswith("authority.sqlite3"))
    with Path(authority["path"]).open("ab") as stream: stream.write(b"changed")
    with pytest.raises(memory.ArchitectureMemoryError, match="changed"):
        quarantine.capture_cell(inputs.root, path, result)


def test_frozen_bank_revocation_blocks_even_cached_quarantine_receipt(inputs):
    path, result, _ = cell(inputs)
    quarantine.capture_cell(inputs.root, path, result)
    manifest = memory._read(inputs.bank_ref["path"])
    with SkillMemoryStore(manifest["source_authority"]["path"]) as store:
        store.invalidate_repository(org_id=inputs.target.org_id, repository=inputs.target.repository, current_revision="b" * 40)
    with pytest.raises(memory.ArchitectureMemoryError, match="changed"):
        quarantine.capture_cell(inputs.root, path, result)


def test_quarantine_initialization_requires_full_evaluation_inventory(inputs, monkeypatch):
    monkeypatch.setattr(quarantine, "EVALUATION_COUNT", 500)
    with pytest.raises(quarantine.QuarantineError, match="500"):
        quarantine.initialize_quarantine(inputs.tmp / "bad", execution_reference=inputs.execution_ref, bank_reference=inputs.bank_ref)
    assert not (inputs.tmp / "bad").exists()


def test_explicit_development_baseline_is_audited_without_any_memory_bank(inputs, monkeypatch):
    import trimem_skhynix_architecture_run as execution
    config = deepcopy(inputs.config)
    config["run_root"] = str(inputs.tmp / "dev-run")
    config["native_control_root"] = str(inputs.tmp / "dev-native")
    authority = {"purpose": "DEVELOPMENT_BASELINE", "task_ids": [inputs.target.task_id], "arms": ["BASELINE"], "bank_reference": None}
    config["scale_authority_reference"] = write(inputs.tmp / "scale-authority.json", authority)
    scope = lambda config, dataset=None: authority if config.get("scale_authority_reference") else None
    monkeypatch.setattr(execution, "execution_enrollment", scope)
    monkeypatch.setattr(quarantine, "execution_enrollment", scope)
    ref = write(inputs.tmp / "dev-execution.json", config, sidecar=True)
    root = inputs.tmp / "dev-quarantine"
    monkeypatch.setattr(memory, "load_frozen_bank", lambda *_a, **_k: pytest.fail("Bank-free baseline accessed a memory bank"))
    quarantine.initialize_quarantine(root, execution_reference=ref, bank_reference=None)
    ctx = SimpleNamespace(**{**vars(inputs), "root": root, "config": config, "execution_ref": ref, "bank_ref": None})
    path, result, _ = cell(ctx, "BASELINE", empty=True)
    receipt = memory._read(quarantine.capture_cell(root, path, result)["path"])
    assert receipt["status"] == "BASELINE_AUDIT_ONLY" and receipt["failures"] == []
    assert receipt["bank_reference"] is None and receipt["bank_sha256"] == quarantine.EMPTY_BANK_SHA
    assert receipt["captures"] == receipt["quarantine_references"] == [] and receipt["memory_records_written"] == 0
    assert not (root / "private").exists()
    wrong_path, wrong_result, _ = cell(ctx, "PDF_MEMORY", empty=True)
    rejected = memory._read(quarantine.capture_cell(root, wrong_path, wrong_result)["path"])
    assert rejected["status"] == "INVALID_SOURCE" and rejected["memory_records_written"] == 0


def test_empty_bank_does_not_bypass_ordinary_evaluation_quarantine(inputs):
    with pytest.raises(quarantine.QuarantineError, match="Only the explicitly authorized"):
        quarantine.initialize_quarantine(inputs.tmp / "empty-forbidden", execution_reference=inputs.execution_ref, bank_reference=None)
