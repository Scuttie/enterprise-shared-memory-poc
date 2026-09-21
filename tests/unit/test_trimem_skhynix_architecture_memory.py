from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest

from enterprise_memory.trimem.accounting import canonical_bytes, sha256_bytes
from enterprise_memory.trimem.agent_runtime import CodingTask, RuntimeFailure
from enterprise_memory.trimem.skill_memory import ProcedureTemplate, PromotionRejected, SkillMemoryStore
from enterprise_memory.trimem.skill_runtime import SkillFirstMemoryController
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph, SubtaskSpec
import trimem_skhynix_architecture_memory as memory


STAMP = "2026-09-14T00:00:00Z"
REVISION = "a" * 40
SOURCE = "def normalize_filename_extension(path):\n    return path.upper()\n"
SECOND = "def filename_extension(path):\n    return path.rsplit('.', 1)[-1]\n"


def task(name, *, revision=REVISION, owner="owner-one", repository="example/project"):
    return CodingTask(name, "organization", owner, repository, revision,
        "Normalize filename extension for " + name, {}, ())


def graph(value, objective="normalize filename extension", node_id="normalize", operation="normalize filename extension"):
    result = ShortTermWorkingGraph(value.task_id, value.instruction, value.repository)
    result.add_subtask(SubtaskSpec(objective, operation, node_id=node_id))
    result.activate(node_id)
    return result


def row(value, number, tool, arguments, result, *, status="success", node="normalize"):
    request = {"tool": tool, "arguments": arguments}
    return {"task_id": value.task_id, "arm": "PDF_MEMORY", "active_node_id": node,
        "step_no": number, "tool": tool, "status": status, "request_payload": request,
        "result_payload": result, "request": {"sha256": memory._hash(request), "bytes": len(canonical_bytes(request))},
        "result": {"sha256": memory._hash(result), "bytes": len(canonical_bytes(result))}}


def rehash(event):
    for name in ("request", "result"):
        event[name] = {"sha256": memory._hash(event[name + "_payload"]), "bytes": len(canonical_bytes(event[name + "_payload"]))}


def trace(value, *, file="source.py"):
    argv = ["python", "-m", "pytest", "tests/test_extension.py"]
    def read(number, path, content):
        return row(value, number, "read_file", {"path": path}, {"path": path, "content": content,
            "full_file_sha256": sha256_bytes(content.encode()), "total_file_bytes": len(content.encode()),
            "returned_start_line": 1, "returned_end_line": 2, "truncated": False})
    return [read(1, file, SOURCE), read(2, "helper.py", SECOND),
        row(value, 3, "run_command", {"argv": argv}, {"stdout": "AssertionError: extension differs\n1 failed in 0.2s",
            "stderr": "", "exit_code": 1, "timed_out": False, "output_truncated": False}),
        row(value, 4, "replace_text", {"path": file, "old_text": "upper", "new_text": "lower",
            "expected_file_sha256": sha256_bytes(SOURCE.encode())}, {"path": file,
            "prior_sha256": sha256_bytes(SOURCE.encode()), "new_sha256": sha256_bytes(SOURCE.replace("upper", "lower").encode()),
            "old_bytes": 5, "new_bytes": 5, "replacements": 1}),
        row(value, 5, "run_command", {"argv": argv}, {"stdout": "1 passed in 0.2s", "stderr": "",
            "exit_code": 0, "timed_out": False, "output_truncated": False})]


def template():
    return ProcedureTemplate("normalize filename extension", ("path", "test_argv"), (memory.PRECONDITION,),
        ("read_file {path}", "replace_text {path}\nold_text: upper\nnew_text: lower", "run_command {test_argv}"), "{test_argv}", "python")


def capture(root, value, history=None, *, verification_step=5):
    return memory.capture_training_trace(root, value.public_payload(), history or trace(value),
        owner_user_id=value.user_id, active_node_id="normalize", subgoal="normalize filename extension",
        summary="Observed filename extension normalization and public tests", verification_step=verification_step, created_at=STAMP)


def setup(root, *, revision=REVISION):
    values = [task("training-one", revision=revision), task("training-two", revision=revision, owner="owner-two")]
    target = task("evaluation-target", revision=revision)
    memory.initialize_training_memory(root, org_id=target.org_id,
        training_tasks=[value.public_payload() for value in values], evaluation_tasks=[target.public_payload()])
    return values, target


def observation(root, proposal, value, receipt):
    return memory.verify_skill_observation(root, proposal["proposal_id"], receipt["capture_id"],
        bindings={"path": "source.py", "test_argv": canonical_bytes(trace(value)[-1]["request_payload"]["arguments"]["argv"]).decode()},
        step_numbers=[1, 4, 5], red_step=3)


def trained(root, *, skills=False):
    values, target = setup(root)
    receipts = [capture(root, value) for value in values]
    promoted = None
    if skills:
        proposal = memory.declare_skill_proposal(root, template(), training_task_ids=[v.task_id for v in values])
        observations = [observation(root, proposal, value, receipt) for value, receipt in zip(values, receipts)]
        promoted = memory.promote_verified_skill(root, proposal["proposal_id"], [r["observation_id"] for r in observations])
    frozen = memory.freeze_training_bank(root, root.parent / (root.name + "-frozen.json"), require_verified_skill=skills)
    return values, target, receipts, frozen, promoted


def test_actual_gate_a_nodes_edges_gate_b_and_skill_priority(tmp_path):
    values, target, receipts, frozen, promoted = trained(tmp_path / "training", skills=True)
    assert promoted["status"] == "ACTUALLY_PROMOTED_BY_GATE_B"
    assert promoted["support_count"] == promoted["contributor_count"] == 2
    assert frozen["layer_counts"] == {"L1_episodes": 4, "L2_nodes": 4, "L2_edges": 2, "L3_skills": 1}
    bank = memory.load_frozen_bank(frozen["path"], frozen["sha256"], target)
    try:
        snapshot = bank.snapshot(org_id=target.org_id, user_id=target.user_id, repository=target.repository, revision=target.commit, language="python")
        assert len(snapshot.episodes) == 2
        assert {e.evidence.user_id for e in snapshot.episodes} == {"owner-one"}
        assert len(snapshot.knowledge_edges) == 2
        assert all(row.revision == REVISION for row in snapshot.repository_knowledge)
        decision = bank.controller(target).recall(graph(target), target)
        assert len(decision.injections) == 1
        assert decision.injections[0].kind.value == "SKILL"
        public = json.loads(decision.injections[0].exact_text)
        assert public["kind"] == "verified_parameterised_skill"
        assert "owner-one" not in decision.injections[0].exact_text
        assert "training-one" not in decision.injections[0].exact_text
        assert public["preconditions"] == [memory.PRECONDITION]
    finally:
        bank.close()


def test_frozen_repository_retrieval_preserves_original_bytes_and_default_configuration(tmp_path):
    _, target, _, frozen, _ = trained(tmp_path / "training")
    bank = memory.load_frozen_bank(frozen["path"], frozen["sha256"], target)
    try:
        controller = bank.controller(target)
        assert controller.content_hash == SkillFirstMemoryController(bank.store, task_id=target.task_id).content_hash
        assert controller.context_budget_bytes == 12000 and controller.max_injections_per_task == 3 and controller.min_score == .05
        result = controller.recall(graph(target, "normalize_filename_extension filename_extension source public"), target)
        assert result.injections[0].kind.value == "REPOSITORY_SEMANTIC"
        item = result.injections[0]
        original = bank.store._knowledge(bank.store._db.execute("SELECT * FROM memory_records WHERE record_id=?", (item.memory_id,)).fetchone())
        assert json.loads(item.exact_text)["content"] == original.content
        assert item.verify() and item.sha256 == sha256_bytes(item.exact_text.encode())
        handoff = memory.to_handoff_memory(item, frozen["sha256"])
        assert handoff.exact_text == item.exact_text
        assert handoff.source_content_sha256 == original.content_hash.removeprefix("sha256:")
        assert 0 < item.confidence < 1
        unrelated = graph(target, "bicycle sprocket saddle", operation="bicycle sprocket saddle")
        assert not bank.controller(target).recall(unrelated, target).injections
    finally:
        bank.close()


def test_owner_episodes_follow_repository_abstention_without_cross_owner_leak(tmp_path):
    values, target = setup(tmp_path / "training")
    for value in values:
        history = trace(value)[2:]
        capture(tmp_path / "training", value, history)
    frozen = memory.freeze_training_bank(tmp_path / "training", tmp_path / "bank.json")
    bank = memory.load_frozen_bank(frozen["path"], frozen["sha256"])
    try:
        decision = bank.controller(target).recall(graph(target), target)
        assert decision.injections[0].kind.value == "EPISODIC"
        other = replace(target, user_id="unseen-owner")
        assert not bank.controller(other).recall(graph(other), other).injections
        assert [r["bank"] for r in decision.bank_trace] == ["SKILL", "REPOSITORY_SEMANTIC", "EPISODIC"]
    finally:
        bank.close()


def test_callback_restores_node_receipts_and_taskwide_budget(tmp_path):
    _, target, _, frozen, _ = trained(tmp_path / "training")
    callback = memory.make_recall_callback(frozen["path"], frozen["sha256"], org_id=target.org_id, owner_user_id=target.user_id)
    checkpoint = None
    exposures = []
    for n in range(5):
        working = graph(target, "normalize_filename_extension filename_extension source public", node_id=f"extension-{n}")
        result = callback(target.public_payload(), working, None, checkpoint)
        checkpoint = result["checkpoint"]
        exposures += list(result["injections"])
        repeated = callback(target.public_payload(), working, None, checkpoint)
        assert not repeated["injections"]
    assert len(exposures) == 3 and len({item.memory_id for item in exposures}) == 3
    assert sum(len(item.exact_text.encode()) for item in exposures) <= 12000
    with pytest.raises(memory.ArchitectureMemoryError, match="query"):
        callback(target.public_payload(), graph(target), {"objective": "forced unrelated query"}, checkpoint)
    changed = deepcopy(checkpoint)
    changed["binding"]["owner_user_id"] = "owner-two"
    with pytest.raises(memory.ArchitectureMemoryError, match="checkpoint"):
        callback(target.public_payload(), graph(target), None, changed)
    changed = deepcopy(checkpoint)
    ledger = changed["controller"]["ledger"]
    assert ledger
    ledger[0]["exact_text"] += " changed"
    with pytest.raises((ValueError, RuntimeFailure)):
        callback(target.public_payload(), graph(target), None, changed)


@pytest.mark.parametrize("field,value", [("task_id", "wrong-task"), ("repository", "other/repository"), ("commit", "b" * 40), ("instruction", "another issue")])
def test_frozen_task_binding_fails_closed(tmp_path, field, value):
    _, target, _, frozen, _ = trained(tmp_path / "training")
    with pytest.raises(memory.ArchitectureMemoryError, match="scope"):
        memory.load_frozen_bank(frozen["path"], frozen["sha256"], replace(target, **{field: value}))
    with pytest.raises(memory.ArchitectureMemoryError, match="scope"):
        memory.load_frozen_bank(frozen["path"], frozen["sha256"], replace(target, org_id="other-org"))


@pytest.mark.parametrize("change", ["task", "hash", "duplicate", "mixedarm", "hidden", "sourcehash"])
def test_capture_rejects_corrupted_or_hidden_receipts(tmp_path, change):
    values, _ = setup(tmp_path / "training")
    history = trace(values[0])
    if change == "task": history[0]["task_id"] = "other"
    if change == "hash": history[0]["result_payload"]["content"] += " changed"
    if change == "duplicate": history[1]["step_no"] = 1
    if change == "mixedarm": history[1]["arm"] = "BASELINE"
    if change == "hidden":
        history[0]["result_payload"]["test_patch"] = "forbidden"
        rehash(history[0])
    if change == "sourcehash":
        history[0]["result_payload"]["full_file_sha256"] = "f" * 64
        rehash(history[0])
    with pytest.raises(ValueError):
        capture(tmp_path / "training", values[0], history)


@pytest.mark.parametrize("change", ["exit-only", "red-only", "differentargv", "skipped", "truncated", "noassertion", "noop", "testsedit", "lateedit", "intervening"])
def test_gate_b_rejects_unproven_public_test_workflows(tmp_path, change):
    root = tmp_path / "training"
    values, _ = setup(root)
    proposal = memory.declare_skill_proposal(root, template(), training_task_ids=[v.task_id for v in values])
    history = trace(values[0])
    if change == "exit-only": history[-1]["result_payload"]["stdout"] = "fine"
    if change == "red-only": history[-1]["result_payload"].update(exit_code=1, stdout="AssertionError\n1 failed")
    if change == "differentargv": history[2]["request_payload"]["arguments"]["argv"] = ["python", "-m", "pytest", "tests/unrelated.py"]
    if change == "skipped": history[-1]["result_payload"]["stdout"] = "1 passed, 1 skipped"
    if change == "truncated": history[-1]["result_payload"]["output_truncated"] = True
    if change == "noassertion": history[2]["result_payload"]["stdout"] = "ImportError\n1 failed"
    if change == "noop": history[3]["request_payload"]["arguments"]["new_text"] = "upper"
    if change == "testsedit":
        for index in (0, 3):
            history[index]["request_payload"]["arguments"]["path"] = "tests/source.py"
            history[index]["result_payload"]["path"] = "tests/source.py"
    if change == "lateedit": history.append(row(values[0], 6, "write_file", {"path": "source.py", "content": "x"}, {"path": "source.py"}))
    if change == "intervening":
        history.insert(3, row(values[0], 4, "run_command", {"argv": ["python", "-c", "print('x')"]}, {"exit_code": 0}))
        history[4]["step_no"] = 5
        history[5]["step_no"] = 6
    for event in history: rehash(event)
    receipt = capture(root, values[0], history, verification_step=6 if change == "intervening" else 5)
    with pytest.raises((memory.ArchitectureMemoryError, ValueError)):
        memory.verify_skill_observation(root, proposal["proposal_id"], receipt["capture_id"],
            bindings={"path": "tests/source.py" if change == "testsedit" else "source.py",
                "test_argv": canonical_bytes(trace(values[0])[-1]["request_payload"]["arguments"]["argv"]).decode()},
            step_numbers=[1, 5, 6] if change == "intervening" else [1, 4, 5], red_step=3)


def test_real_gate_b_rejects_single_support_and_same_owner(tmp_path):
    root = tmp_path / "training"
    values, _ = setup(root)
    values[1] = replace(values[1], user_id=values[0].user_id)
    proposal = memory.declare_skill_proposal(root, template(), training_task_ids=[v.task_id for v in values])
    observations = [observation(root, proposal, value, capture(root, value)) for value in values]
    with pytest.raises(PromotionRejected, match="two"):
        memory.promote_verified_skill(root, proposal["proposal_id"], [observations[0]["observation_id"]])
    with pytest.raises(PromotionRejected, match="distinct"):
        memory.promote_verified_skill(root, proposal["proposal_id"], [r["observation_id"] for r in observations])


def test_path_only_edits_cannot_claim_a_verified_parameterized_transformation(tmp_path):
    root = tmp_path / "training"
    values, _ = setup(root)
    incomplete = replace(template(), steps=("read_file {path}", "replace_text {path}", "run_command {test_argv}"))
    with pytest.raises(memory.ArchitectureMemoryError, match="transformation"):
        memory.declare_skill_proposal(root, incomplete, training_task_ids=[value.task_id for value in values])


def test_positive_gate_b_freeze_requires_actual_promoted_authority(tmp_path):
    root = tmp_path / "training"
    values, _ = setup(root)
    for value in values:
        capture(root, value)
    memory.declare_skill_proposal(root, template(), training_task_ids=[value.task_id for value in values])
    with pytest.raises(memory.ArchitectureMemoryError, match="actually promoted"):
        memory.freeze_training_bank(root, tmp_path / "bank.json", require_verified_skill=True)
    assert not (tmp_path / "bank.json").exists()
    assert not (tmp_path / "bank.private.sqlite3").exists()
    assert not (root / "frozen.json").exists()


@pytest.mark.parametrize("change", ["id", "instruction", "originalinstance"])
def test_training_disjoint_from_all_evaluation_identity_and_instruction(tmp_path, change):
    source, target = task("train--source"), task("eval--target")
    if change == "id": source = replace(source, task_id=target.task_id)
    if change == "instruction": source = replace(source, instruction=target.instruction)
    if change == "originalinstance": source = replace(source, task_id="train--target")
    with pytest.raises(memory.ArchitectureMemoryError, match="overlap|disjoint"):
        memory.initialize_training_memory(tmp_path / "training", org_id=target.org_id,
            training_tasks=[source.public_payload()], evaluation_tasks=[target.public_payload()])


@pytest.mark.parametrize("what", ["manifest", "authority", "source_authority", "capture"])
def test_frozen_evidence_tampering_fails_before_recall(tmp_path, what):
    _, target, _, frozen, _ = trained(tmp_path / "training")
    callback = memory.make_recall_callback(frozen["path"], frozen["sha256"], org_id=target.org_id, owner_user_id=target.user_id)
    checkpoint = callback(target.public_payload(), graph(target), None, None)["checkpoint"]
    manifest = memory._read(frozen["path"])
    reference = frozen if what == "manifest" else next(iter(manifest["catalog"]["captures"].values())) if what == "capture" else manifest[what]
    with Path(reference["path"]).open("ab") as stream: stream.write(b"changed")
    with pytest.raises(memory.ArchitectureMemoryError, match="changed"):
        callback(target.public_payload(), graph(target), None, checkpoint)


@pytest.mark.parametrize("key,value", [("forced_delivery", True), ("source_revisions_retagged", True), ("retrieval", "EXACT_TASK_DIAGNOSTIC_ROUTE"), ("evaluation_writes", "TRAINING"), ("layer_counts", {"L3_skills": 10})])
def test_rehashed_manual_policy_and_false_counts_are_rejected(tmp_path, key, value):
    _, _, _, frozen, _ = trained(tmp_path / "training")
    manifest = memory._read(frozen["path"])
    manifest[key] = value
    path = tmp_path / "bad.json"
    memory._write(path, manifest, fresh=True)
    with pytest.raises(memory.ArchitectureMemoryError):
        memory.load_frozen_bank(path, memory._file_hash(path))


def test_unregistered_manual_memory_and_revocation_cannot_be_frozen(tmp_path):
    root = tmp_path / "training"
    _, target = setup(root)
    with SkillMemoryStore(root / "authority.sqlite3") as store:
        store.put_repository_knowledge(org_id=target.org_id, repository=target.repository, revision=target.commit,
            title="manual lesson", content="forced target instruction")
    with pytest.raises(memory.ArchitectureMemoryError, match="ungrounded"):
        memory.freeze_training_bank(root, tmp_path / "bank.json")


def test_source_revocation_invalidates_restored_frozen_retrieval(tmp_path):
    _, target, _, frozen, _ = trained(tmp_path / "training")
    callback = memory.make_recall_callback(frozen["path"], frozen["sha256"], org_id=target.org_id, owner_user_id=target.user_id)
    checkpoint = callback(target.public_payload(), graph(target), None, None)["checkpoint"]
    with SkillMemoryStore(tmp_path / "training" / "authority.sqlite3") as store:
        store.invalidate_repository(org_id=target.org_id, repository=target.repository, current_revision="b" * 40)
    with pytest.raises(memory.ArchitectureMemoryError, match="changed or was revoked"):
        callback(target.public_payload(), graph(target), None, checkpoint)


def test_failed_gate_a_is_idempotent_and_large_private_view_abstains(tmp_path):
    root = tmp_path / "training"
    values, target = setup(root)
    history = [row(values[0], 1, "run_command", {"argv": ["python", "-c", "x" * 13000]},
        {"stdout": "", "stderr": "failed", "exit_code": 1, "timed_out": False, "output_truncated": False})]
    first = capture(root, values[0], history, verification_step=None)
    assert capture(root, values[0], history, verification_step=None) == first
    assert not first["succeeded"] and not first["knowledge_ids"]
    frozen = memory.freeze_training_bank(root, tmp_path / "bank.json")
    bank = memory.load_frozen_bank(frozen["path"], frozen["sha256"])
    try:
        decision = bank.controller(target).recall(graph(target), target)
        assert not decision.injections
        assert any(row["reason"] == "CONTEXT_INJECTION_BUDGET" for row in decision.rejections)
        assert frozen["layer_counts"]["L1_episodes"] == 1
    finally: bank.close()


@pytest.mark.parametrize("arm", ["BASELINE", "PDF_MEMORY"])
def test_actual_broker_callback_packet_and_cached_worker_recall(tmp_path, arm):
    from trimem_skhynix_architecture_broker import ArchitectureBroker
    _, target, _, frozen, _ = trained(tmp_path / "training", skills=True)
    actual = memory.make_recall_callback(frozen["path"], frozen["sha256"], org_id=target.org_id, owner_user_id=target.user_id)
    calls = []
    def callback(*args):
        calls.append(args[2])
        return actual(*args)
    workspace = SimpleNamespace(execute=lambda *args: {}, patch=lambda: "")
    broker = ArchitectureBroker.create(tmp_path / arm, task_public=target.public_payload(), arm=arm,
        workspace=workspace, configuration_sha256="c" * 64, bank_sha256=frozen["sha256"],
        tool_schema={"read_file": {"type": "object"}}, memory_callback=callback)
    def admit(worker):
        issued = broker.issue_handoff(worker)
        response = broker.admit_worker(worker, issued["packet_sha256"], {"thread_id": "fixture-thread-" + worker,
            "fork_turns": "none", "fresh_session": True, "requested_model": "gpt-6-astra", "launch_evidence_sha256": "d" * 64})
        return issued, response["admission_token"]
    _, token = admit("planner")
    assert broker.action("planner", token, {"request_id": "plan", "op": "plan_subgoals", "subgoals": [
        {"node_id": "normalize", "objective": "normalize filename extension", "operation": "normalize filename extension"}]})["ok"]
    assert broker.action("planner", token, {"request_id": "activate", "op": "activate_subgoal", "node_id": "normalize"})["ok"]
    packet, token = admit("solver")
    delivered = packet["packet"]["body"]["memory_injections"]
    assert len(delivered) == (1 if arm == "PDF_MEMORY" else 0)
    assert len(calls) == (1 if arm == "PDF_MEMORY" else 0)
    if delivered:
        assert delivered[0]["kind"] == "SKILL"
        assert delivered[0]["sha256"] == sha256_bytes(delivered[0]["exact_text"].encode())
    reopened = ArchitectureBroker(tmp_path / arm, workspace=workspace,
        configuration_sha256="c" * 64, bank_sha256=frozen["sha256"])
    for number in range(2):
        response = reopened.action("solver", token, {"request_id": f"recall-{number}", "op": "recall"})
        assert response["ok"]
    assert len(calls) == (1 if arm == "PDF_MEMORY" else 0)
    assert reopened.status()["memory_injections"] == (1 if arm == "PDF_MEMORY" else 0)


def test_evaluation_gate_a_is_private_quarantine_and_bank_cannot_change(tmp_path):
    _, target, _, frozen, _ = trained(tmp_path / "training")
    before = memory._file_hash(frozen["path"])
    quarantine = tmp_path / "quarantine"
    receipt = memory.capture_evaluation_trace(quarantine, frozen["path"], frozen["sha256"], target.public_payload(), trace(target),
        owner_user_id=target.user_id, active_node_id="normalize", subgoal="normalize filename extension",
        summary="evaluation tool attempt", verification_step=5, created_at=STAMP)
    assert receipt["phase"] == "EVALUATION_QUARANTINE" and receipt["knowledge_ids"] == []
    with SkillMemoryStore(quarantine / "authority.sqlite3") as store:
        assert store.get_episode(receipt["episode_id"], org_id=target.org_id, user_id=target.user_id)
        assert store.get_episode(receipt["episode_id"], org_id=target.org_id, user_id="other-owner") is None
    with pytest.raises(memory.ArchitectureMemoryError, match="quarantine"):
        memory.freeze_training_bank(quarantine, tmp_path / "forbidden.json")
    with pytest.raises(memory.ArchitectureMemoryError, match="Frozen"):
        capture(tmp_path / "training", target)
    assert memory._file_hash(frozen["path"]) == before
    bank = memory.load_frozen_bank(frozen["path"], frozen["sha256"])
    try:
        snapshot = bank.snapshot(org_id=target.org_id, user_id=target.user_id, repository=target.repository, revision=target.commit, language="python")
        assert receipt["episode_id"] not in {row.episode_id for row in snapshot.episodes}
    finally: bank.close()


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.mark.parametrize("same_file", [True, False])
def test_historical_source_applicability_requires_identical_base_file_without_retag(tmp_path, same_file):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    git(checkout, "init", "-q")
    (checkout / "source.py").write_text(SOURCE)
    (checkout / "helper.py").write_text(SECOND)
    git(checkout, "add", ".")
    git(checkout, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "source")
    source_revision = git(checkout, "rev-parse", "HEAD")
    (checkout / "unrelated.txt").write_text("new target revision")
    if not same_file:
        (checkout / "source.py").write_text("changed source\n")
        (checkout / "helper.py").write_text("changed helper\n")
    git(checkout, "add", ".")
    git(checkout, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "target")
    target_revision = git(checkout, "rev-parse", "HEAD")
    source, target = task("source", revision=source_revision), task("target", revision=target_revision)
    root = tmp_path / "training"
    memory.initialize_training_memory(root, org_id=target.org_id, training_tasks=[source.public_payload()], evaluation_tasks=[target.public_payload()])
    capture(root, source)
    frozen = memory.freeze_training_bank(root, tmp_path / "bank.json")
    for supplied_checkout in (None, checkout):
        bank = memory.load_frozen_bank(frozen["path"], frozen["sha256"], target, checkout_root=supplied_checkout)
        try:
            snapshot = bank.snapshot(org_id=target.org_id, user_id=target.user_id, repository=target.repository, revision=target.commit, language="python")
            assert bool(snapshot.repository_knowledge) == (same_file and supplied_checkout is not None)
            assert all(row.revision == source_revision for row in snapshot.repository_knowledge)
            assert all(json.loads(row.content)["source_revision"] == source_revision for row in snapshot.repository_knowledge)
            assert len(snapshot.knowledge_edges) == (1 if same_file and supplied_checkout is not None else 0)
        finally: bank.close()
    git(checkout, "checkout", "-q", source_revision)
    bank = memory.load_frozen_bank(frozen["path"], frozen["sha256"], target, checkout_root=checkout)
    try:
        with pytest.raises(memory.ArchitectureMemoryError, match="base commit"):
            bank.snapshot(org_id=target.org_id, user_id=target.user_id, repository=target.repository, revision=target.commit, language="python")
    finally: bank.close()
