"""Synthetic sealed broker/native evidence; no model, checkout, or grading calls."""
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
import trimem_skhynix_architecture_broker as broker_module
import trimem_skhynix_architecture_native as native
import trimem_skhynix_architecture_run as execution


POLICY = "CAPTURE_KNOWN_TERMINAL_AMBIGUITY_AND_CONTINUE"
INSTANCE = "fixture__repo-1"
TASK = "swebench--" + INSTANCE
PATCH = "diff --git a/public.py b/public.py\n--- a/public.py\n+++ b/public.py\n@@ -1 +1 @@\n-old\n+new\n"


def write(path, value, *, sidecar=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(execution.canonical(value) + b"\n")
    if sidecar:
        path.with_suffix(".sha256").write_text(execution.digest(execution.canonical(value)) + "\n")
    return {"path": str(path), "sha256": execution.digest(path.read_bytes())}


def mutate(path, **changes):
    value = execution.read(path)
    value.update(changes)
    write(path, value)


def aggregate(reason="no_tests_collected"):
    return {"schema_version": 2, "total_instances": 1, "submitted_instances": 1,
        "submitted_ids": [INSTANCE], "completed_instances": 1, "completed_ids": [INSTANCE],
        "resolved_instances": 0, "resolved_ids": [], "unresolved_instances": 1,
        "unresolved_ids": [INSTANCE], "ambiguous_failure_instances": 1,
        "ambiguous_failure_ids": [INSTANCE], "failure_reasons": {INSTANCE: reason},
        "infra_failure_instances": 0, "infra_failure_ids": [], "error_instances": 0,
        "error_ids": [], "empty_patch_instances": 0, "empty_patch_ids": [],
        "incomplete_ids": [], "unstopped_instances": 0, "unstopped_containers": [],
        "unremoved_images": ["swebench/sweb.eval.x86_64.fixture_1776_repo-1:latest"]}


@pytest.fixture
def terminal_factory(tmp_path, monkeypatch):
    """Use the real broker journal and native audit, mocking only the public workspace."""
    serial = [0]
    monkeypatch.setattr(execution, "load_experiment", lambda path: execution.read(path))

    def build(*, budget=False, reason="no_tests_collected", policy=True, phase="TRAINING", native_reason=None, cleanup_ready=False):
        serial[0] += 1
        root = tmp_path / str(serial[0])
        root.mkdir()
        run_root = root / "run"
        config = {"schema": execution.SCHEMA, "phase": phase + "_RUNTIME",
            "run_root": str(run_root), "native_control_root": str(root / "native"),
            "source_root": str(root / "source"), "source_sha256": {},
            "model": "gpt-6-astra", "reasoning_effort": "high", "codex_binary": "C:/fixture/codex.exe",
            "windows_python": "C:/fixture/python.exe", "wsl_windows_python": "/mnt/c/fixture/python.exe"}
        if policy:
            config["training_grade_hold_policy"] = POLICY
        public_instruction="Repair the public synthetic regression."
        target={'target_id':TASK,'instance_id':INSTANCE,'repository':'fixture/repo','base_commit':'a'*40,
            'role':phase,'instruction_sha256':execution.digest(public_instruction.encode())}
        image="fixture/image@sha256:"+"c"*64
        if cleanup_ready:
            from trimem_skhynix_architecture_dataset import official_image_tag
            image=official_image_tag(INSTANCE).removesuffix(':latest')+'@sha256:'+'c'*64
            targets=[target]
            for role,count in (('TRAINING',23),('EVALUATION',500)):
                targets.extend({**target,'target_id':role.lower()+'-'+str(n),'instance_id':role.lower()+'-'+str(n),
                    'role':role} for n in range(count))
            config['dataset_manifest']=write(root/'dataset.json',{'training_count':24,'evaluation_count':500,'targets':targets})
            config['image_index']=write(root/'images.json',{'rows':[{'instance_id':INSTANCE,'image':image}]})
        config_path = root / "execution.json"
        write(config_path, config, sidecar=True)
        folder = run_root / "cells" / phase / TASK / "PDF_MEMORY"
        folder.mkdir(parents=True)
        cell_path = folder / "cell.json"
        checkout = run_root/'workspaces/PDF_MEMORY'/TASK/'checkouts'/TASK if cleanup_ready else root / "checkout"
        checkout.mkdir(parents=True)
        (checkout / "public.py").write_text("public synthetic workspace\n")
        public = {"task_id": TASK, "repository": "fixture/repo", "commit": "a" * 40,
            "instruction": public_instruction}
        workspace_config = {"checkout_root": str(checkout), "image": image}
        if cleanup_ready:
            workspace_config['command_runner_sha256']='d'*64
        clock = [1000.0]
        broker = broker_module.ArchitectureBroker.create(folder / "broker", task_public=public,
            arm="PDF_MEMORY", workspace=SimpleNamespace(patch=lambda: PATCH),
            configuration_sha256=execution.digest(execution.canonical(config)), bank_sha256="b" * 64,
            tool_schema={"read_file": {"type": "object"}}, clock=lambda: clock[0],
            workspace_configuration=workspace_config)
        output_root = run_root / "environment" / phase / "cells/PDF_MEMORY" / TASK
        cell = {"schema": execution.SCHEMA, "phase": phase, "arm": "PDF_MEMORY",
            "experiment_config": str(config_path), "task_public": public,
            "target": target,
            "broker_root": str(broker.root), "bank_sha256": "b" * 64, "bank_reference": None,
            "workspace_configuration": workspace_config, "prepared_output_root": str(output_root)}
        if cleanup_ready:
            cell.update(owner_user_id='synthetic-owner',owned_images={})
            write(output_root/'control/checkout-preflight.json',{'head':'a'*40,'initial_status':'',
                'checkout_origin':'FRESH_BASE_ONLY_FETCH','history_isolation':{'status':'SYNTHETIC_VALID_BASE_ONLY'},
                'command_sandbox_content_hash':'d'*64})
            for name in ('solver-sandbox-preflight.json','public-python-preflight.json'):
                write(output_root/'control'/name,{'status':'PASS','command_sandbox_content_hash':'d'*64})
        write(cell_path, cell, sidecar=True)
        worker_id = "fixture-worker-1"
        issued = broker.issue_handoff(worker_id)
        worker = root / "native" / phase / INSTANCE / "PDF_MEMORY/worker-001"
        output = worker / "output"
        output.mkdir(parents=True)
        prompt = execution.prompt_prefix(phase) + execution.canonical(issued["packet"])
        (worker / "prompt.txt").write_bytes(prompt)
        write(worker / "packet.json", issued["packet"])
        worker_config = {"schema": execution.SCHEMA, "linux_source_root": config["source_root"],
            "linux_cell_config": str(cell_path), "worker_id": worker_id,
            "worker_output": str(output), "worker_cwd": str(worker / "cwd"),
            "admission_path": str(worker / "admission.json"), "prompt_path": str(worker / "prompt.txt"),
            "prompt_sha256": execution.digest(prompt), "packet_sha256": issued["packet_sha256"],
            "codex_binary": config["codex_binary"], "windows_python": config["windows_python"],
            "model": config["model"], "reasoning_effort": config["reasoning_effort"],
            "authentication": "CHATGPT", "worker_timeout_seconds": 1200}
        write(worker / "config.json", worker_config)
        launch = {"schema": native.SCHEMA, "worker_id": worker_id, "requested_model": config["model"],
            "reasoning_effort": config["reasoning_effort"], "authentication": "CHATGPT_FORCED",
            "prompt_sha256": execution.digest(prompt), "prompt_bytes": len(prompt),
            "packet_sha256": issued["packet_sha256"], "fresh_session": True, "resume_or_fork_used": False,
            "separate_model_api_client_calls": 0, "started_at": clock[0],
            "command_sha256": execution.digest(execution.canonical(native.worker_command(worker_config, worker / "config.json")))}
        write(output / "launch.json", launch)
        admitted = broker.admit_worker(worker_id, issued["packet_sha256"], {
            "thread_id": "fixture-thread-1", "fresh_session": True, "fork_turns": "none",
            "requested_model": config["model"], "launch_evidence_sha256": execution.digest(execution.canonical(launch))})
        token = admitted.pop("admission_token")
        write(worker / "admission.json", {**admitted, "token": token})
        if budget:
            clock[0] += 1201
            broker.seal_partial(reason=native_reason or "NATIVE_WORKER_WALL_LIMIT")
        else:
            assert broker.action(worker_id, token, {"request_id": "submit-1", "op": "submit",
                "summary": "A sealed synthetic public patch."})["ok"]
        events = execution.canonical({"type": "thread.started", "thread_id": "fixture-thread-1"}) + b"\n"
        (output / "events.jsonl").write_bytes(events)
        completion = {"thread_id": "fixture-thread-1", "admitted": True,
            "outside_broker_tool_events": [], "errors": [], "transport_errors": [],
            "timed_out": budget, "exit_code": -9 if budget else 0, "ended_at": clock[0],
            "wall_seconds": 1201 if budget else 0.1, "events_sha256": execution.digest(events), "usage": None}
        write(output / "completion.json", completion)
        monkeypatch.setattr(execution, "open_cell", lambda *args, **kwargs: (cell, config, broker))
        audit = execution.execution_audit(cell_path)
        assert audit["passed"] is True
        monkeypatch.setattr(execution, "open_cell", lambda *args, **kwargs:
            pytest.fail("Terminal evidence validation must not reopen the checkout"))
        write(folder / "grader-pending.json", {"patch_sha256": execution.digest(PATCH.encode()), "started_at": clock[0] + 1})
        model = "trimem-v1-PDF_MEMORY"
        run_id = execution.digest((TASK + ":" + model).encode())[:20]
        report = output_root / "official-grader" / TASK / "report" / (model + "." + run_id + ".json")
        write(report, aggregate(reason))
        return SimpleNamespace(root=root, folder=folder, cell_path=cell_path, config=config,
            config_path=config_path, cell=cell, broker=broker, worker=worker, output=output,
            checkout=checkout, report=report, proof=folder / "training-grade-undetermined.json")

    return build


@pytest.mark.parametrize("budget", [False, True])
def test_sealed_native_submission_can_be_verified_without_workspace(terminal_factory, budget):
    ctx = terminal_factory(budget=budget)
    before = (ctx.folder / "broker/submission.json").read_bytes()
    proof = execution.validate_training_submission(ctx.cell_path)
    assert proof["audit"]["passed"] is True
    assert proof["state"]["submission"]["agent_completed"] is (not budget)
    assert (ctx.folder / "broker/submission.json").read_bytes() == before


def test_submission_validation_does_not_require_new_training_policy(terminal_factory):
    ctx = terminal_factory(budget=True, policy=False)
    value = execution.validate_training_submission(ctx.cell_path)
    assert value["audit"]["passed"] is True
    assert value["state"]["submission"]["agent_completed"] is False


@pytest.mark.parametrize("budget", [False, True])
def test_known_terminal_ambiguity_proof_is_immutable_idempotent_and_unscored(terminal_factory, budget):
    ctx = terminal_factory(budget=budget)
    assert execution.training_grade_undetermined(ctx.cell_path, create=False) is None
    assert not ctx.proof.exists()
    payload, reference = execution.training_grade_undetermined(ctx.cell_path, create=True)
    before = ctx.proof.read_bytes()
    assert payload["resolved"] is None and payload["official_outcome"] == "UNDETERMINED"
    assert payload["task_id"] == TASK
    assert reference == {"path": str(ctx.proof), "sha256": execution.digest(before)}
    assert execution.training_grade_undetermined(ctx.cell_path, create=True) == (payload, reference)
    assert execution.training_grade_undetermined(ctx.cell_path, create=False) == (payload, reference)
    assert ctx.proof.read_bytes() == before
    assert not (ctx.folder / "public-result.json").exists()


@pytest.mark.parametrize("reason", ["no_tests_collected", "missing_module"])
def test_both_reviewed_aggregate_classes_can_continue_training(terminal_factory, reason):
    ctx = terminal_factory(reason=reason)
    payload, _ = execution.training_grade_undetermined(ctx.cell_path, create=True)
    assert payload["classification"] == "AMBIGUOUS_" + reason.upper()
    assert payload["resolved"] is None


def test_unknown_aggregate_reason_stays_blocked_without_new_evidence(terminal_factory):
    ctx = terminal_factory(reason="unrecognized_harness_failure")
    assert execution.training_grade_undetermined(ctx.cell_path, create=True) is None
    assert not ctx.proof.exists()


def test_no_pending_invocation_cannot_be_classified(terminal_factory):
    ctx = terminal_factory()
    (ctx.folder / "grader-pending.json").unlink()
    assert execution.training_grade_undetermined(ctx.cell_path, create=True) is None
    assert not ctx.proof.exists()


@pytest.mark.parametrize("changes", [
    {"total_instances": 2}, {"completed_instances": 0}, {"submitted_instances": True},
    {"resolved_instances": 1}, {"infra_failure_instances": 1}, {"error_instances": 1},
    {"ambiguous_failure_ids": ["other__repo-1"]}, {"completed_ids": ["other__repo-1"]},
    {"submitted_ids": []}, {"unresolved_ids": []}, {"incomplete_ids": [INSTANCE]},
    {"unstopped_containers": ["retained-container"]}, {"failure_reasons": {"other__repo-1": "no_tests_collected"}},
])
def test_inconsistent_terminal_aggregate_cannot_authorize_continuation(terminal_factory, changes):
    ctx = terminal_factory()
    mutate(ctx.report, **changes)
    with pytest.raises((ValueError, RuntimeError)):
        execution.training_grade_undetermined(ctx.cell_path, create=True)
    assert not ctx.proof.exists()


@pytest.mark.parametrize("target", ["aggregate", "patch", "completion", "events", "launch", "admission", "worker_config", "broker_state"])
def test_later_evidence_mutation_invalidates_retained_proof(terminal_factory, target):
    ctx = terminal_factory()
    execution.training_grade_undetermined(ctx.cell_path, create=True)
    paths = {"aggregate": ctx.report, "patch": ctx.folder / "broker/submission.diff",
        "completion": ctx.output / "completion.json", "events": ctx.output / "events.jsonl",
        "launch": ctx.output / "launch.json", "admission": ctx.worker / "admission.json",
        "worker_config": ctx.worker / "config.json", "broker_state": ctx.folder / "broker/state.json"}
    path = paths[target]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises((ValueError, RuntimeError)):
        execution.training_grade_undetermined(ctx.cell_path, create=False)


def test_retained_proof_remains_valid_after_checkout_cleanup(terminal_factory):
    ctx = terminal_factory()
    proof = execution.training_grade_undetermined(ctx.cell_path, create=True)
    (ctx.checkout / "public.py").unlink()
    ctx.checkout.rmdir()
    assert execution.training_grade_undetermined(ctx.cell_path, create=False) == proof


def test_retained_snapshot_status_matches_original_broker_status(terminal_factory):
    ctx = terminal_factory(budget=True)
    result = execution.validate_training_submission(ctx.cell_path)
    assert result['status'] == ctx.broker.status()


@pytest.mark.parametrize('exclusive', [False, True])
def test_borrowed_real_broker_descriptor_remains_owned_after_validation(terminal_factory, exclusive):
    import fcntl
    ctx = terminal_factory()
    expected = execution.training_grade_undetermined(ctx.cell_path, create=True)
    lock = ctx.folder/'broker/broker.lock'
    with lock.open('rb') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        assert execution.training_grade_undetermined(ctx.cell_path, create=False, _broker_lock=stream) == expected
        with lock.open('rb') as competing:
            with pytest.raises(BlockingIOError):
                fcntl.flock(competing,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(stream,fcntl.LOCK_UN)


def test_borrowed_descriptor_cannot_name_another_file_or_skip_lock_with_boolean(terminal_factory):
    ctx = terminal_factory()
    execution.training_grade_undetermined(ctx.cell_path, create=True)
    with (ctx.root/'wrong.lock').open('w+b') as wrong:
        with pytest.raises(ValueError, match='another file'):
            execution.training_grade_undetermined(ctx.cell_path, create=False, _broker_lock=wrong)
    with pytest.raises(ValueError, match='descriptor'):
        execution.training_grade_undetermined(ctx.cell_path, create=False, _broker_lock=True)


@pytest.mark.parametrize('budget', [False, True])
def test_real_terminal_proof_capture_cleanup_and_revalidation_finish_under_real_locks(terminal_factory, monkeypatch, budget):
    """Run all cleanup lock modes in a child; a nested-flock regression times out."""
    import multiprocessing
    import traceback
    import trimem_benchmark_run as benchmark
    import trimem_skhynix_architecture_cleanup as cleanup
    ctx = terminal_factory(budget=budget,cleanup_ready=True)
    proof = execution.training_grade_undetermined(ctx.cell_path,create=True)
    source_refs={'cell.json':execution._retained_reference(ctx.cell_path)}
    source_refs.update({name:execution._retained_reference(ctx.folder/'broker'/name)
        for name in ('state.json','events.jsonl','submission.diff')})
    capture=write(ctx.root/'capture.json',{'schema':'skhynix/native-architecture-learning/1.0',
        'operation':'CAPTURE_CELL','cell_path':str(ctx.cell_path),'task_id':TASK,'owner_user_id':'synthetic-owner',
        'status':'NO_PUBLIC_ATTEMPTS','failures':[],'captures':[],'source_execution_observed':True,
        'source_references':source_refs})
    policy=cleanup.create_cleanup_policy(ctx.root/'cleanup-policy.json',
        experiment_reference=execution._retained_reference(ctx.config_path),release_owned_images=False)
    monkeypatch.setattr(benchmark,'_valid_history_isolation_evidence',lambda value,**kwargs:
        value=={'status':'SYNTHETIC_VALID_BASE_ONLY'})
    def snapshot(path,commit):
        stat=path.stat()
        return {'path':str(path),'device':stat.st_dev,'inode':stat.st_ino,'base_commit':commit,
            'patch_sha256':execution.digest(PATCH.encode()),'inventory_sha256':'e'*64}
    monkeypatch.setattr(cleanup,'_workspace_snapshot',snapshot)
    parent,child=multiprocessing.Pipe(duplex=False)
    def perform():
        try:
            registrations={'PDF_MEMORY':{'cell_path':str(ctx.cell_path),
                'experiment_reference':execution._retained_reference(ctx.config_path),
                'result_reference':proof[1],'capture_reference':capture}}
            cleanup.plan_target_cleanup(policy,TASK,registrations=registrations)
            result=cleanup.cleanup_completed_cell(ctx.cell_path,proof[1],capture,policy_reference=policy)
            assert result['status']=='COMPLETE' and not ctx.checkout.exists()
            retained=cleanup.validate_completed_cleanup(ctx.cell_path,proof[1],capture)
            assert retained['broker_status']['submission']['agent_completed'] is (not budget)
            assert execution.training_grade_undetermined(ctx.cell_path,create=False)==proof
            assert not (ctx.folder/'public-result.json').exists()
            child.send('PASS')
        except BaseException:
            child.send(traceback.format_exc())
            raise
        finally:
            child.close()
    process=multiprocessing.get_context('fork').Process(target=perform)
    process.start()
    child.close()
    process.join(timeout=10)
    if process.is_alive():
        process.terminate()
        process.join(timeout=3)
        pytest.fail('Terminal training cleanup deadlocked while reusing broker locks')
    result=parent.recv() if parent.poll(1) else 'child produced no result'
    parent.close()
    assert process.exitcode==0 and result=='PASS',result


@pytest.mark.parametrize("phase,policy", [("EVALUATION", True), ("EVALUATION", False), ("TRAINING", False)])
def test_policy_does_not_extend_to_evaluation_or_unamended_training(terminal_factory, phase, policy):
    ctx = terminal_factory(phase=phase, policy=policy)
    assert execution.training_grade_undetermined(ctx.cell_path, create=True) is None
    assert not ctx.proof.exists()


def test_official_result_and_undetermined_proof_cannot_coexist(terminal_factory):
    ctx = terminal_factory()
    execution.training_grade_undetermined(ctx.cell_path, create=True)
    write(ctx.folder / "public-result.json", {"task_id": TASK, "resolved": False, "official": True})
    with pytest.raises((ValueError, RuntimeError)):
        execution.training_grade_undetermined(ctx.cell_path, create=False)


@pytest.mark.parametrize("changes", [
    {"admitted": False}, {"errors": ["invalid stream"]}, {"transport_errors": ["MCP failure"]},
    {"outside_broker_tool_events": ["shell_command"]}, {"exit_code": 1},
])
def test_native_delivery_errors_cannot_become_training_ambiguity(terminal_factory, changes):
    ctx = terminal_factory()
    mutate(ctx.output / "completion.json", **changes)
    with pytest.raises((ValueError, RuntimeError)):
        execution.training_grade_undetermined(ctx.cell_path, create=True)
    assert not ctx.proof.exists()


def test_persisted_native_failure_cannot_become_training_ambiguity(terminal_factory):
    ctx = terminal_factory()
    write(ctx.folder / "native-execution-failure.json", {"launcher_returncode": 1})
    with pytest.raises((ValueError, RuntimeError)):
        execution.training_grade_undetermined(ctx.cell_path, create=True)
    assert not ctx.proof.exists()


@pytest.mark.parametrize("reason", ["NATIVE_WORKER_INFRASTRUCTURE_FAILURE", "NATIVE_WORKER_TIMEOUT", "UNREVIEWED_STOP"])
def test_unapproved_native_partial_reason_cannot_be_adopted(terminal_factory, reason):
    ctx = terminal_factory(budget=True, native_reason=reason)
    with pytest.raises((ValueError, RuntimeError)):
        execution.validate_training_submission(ctx.cell_path)
    assert not ctx.proof.exists()


def test_private_grade_artifact_conflict_is_rejected_without_reading_its_payload(terminal_factory):
    ctx = terminal_factory()
    (ctx.folder / "grader-private.json").write_bytes(b"not JSON; must never be opened by source capture")
    with pytest.raises(ValueError, match="conflicts with a recorded grade"):
        execution.training_grade_undetermined(ctx.cell_path, create=True)
    assert not ctx.proof.exists()


def test_creating_the_receipt_cannot_launch_a_worker_or_retry_grading(terminal_factory, monkeypatch):
    ctx = terminal_factory()
    def forbidden(*args, **kwargs):
        pytest.fail("Retained source proof attempted a native or grading operation")
    monkeypatch.setattr(execution, "run_workers", forbidden)
    monkeypatch.setattr(execution, "grade_cell", forbidden)
    monkeypatch.setattr(execution.subprocess, "run", forbidden)
    payload, _ = execution.training_grade_undetermined(ctx.cell_path, create=True)
    assert payload["resolved"] is None
