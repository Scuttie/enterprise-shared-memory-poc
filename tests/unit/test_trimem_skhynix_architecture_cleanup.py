"""Cleanup boundaries with synthetic records; all removals/image calls simulated."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

import trimem_skhynix_architecture_cleanup as cleanup
import trimem_skhynix_architecture_broker as broker_module
import trimem_skhynix_architecture_run as execution
import trimem_benchmark_run as benchmark


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cleanup._canonical(value) + b"\n")
    return cleanup._reference(path)


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup.sys, "platform", "linux")
    monkeypatch.setattr(benchmark, "_valid_history_isolation_evidence",
        lambda value, **kwargs: value == {"status": "SYNTHETIC_VALID_BASE_ONLY"})
    def build(phase="TRAINING", *, own=True, scale_arms=None, grade_hold=False):
        root = tmp_path / phase
        root.mkdir()
        targets = []
        for role, count, start in (("TRAINING", 24, 1), ("EVALUATION", 500, 1000)):
            prefix = "swebench--" if role == "TRAINING" else "swebench_verified--"
            for number in range(start, start + count):
                targets.append({"target_id": prefix + f"fixture__repo-{number}",
                    "instance_id": f"fixture__repo-{number}", "role": role, "repository": "fixture/repo",
                    "base_commit": "a" * 40, "instruction_sha256": cleanup._sha(b"Synthetic public issue")})
        target = next(row for row in targets if row["role"] == phase)
        manifest_ref = write(root / "dataset.json", {"targets": targets, "training_count": 24, "evaluation_count": 500})
        tag = "swebench/sweb.eval.x86_64." + target["instance_id"].replace("__", "_1776_") + ":latest"
        image = tag.removesuffix(":latest") + "@sha256:" + "c" * 64
        images_ref = write(root / "images.json", {"rows": [{"instance_id": target["instance_id"], "image": image}]})
        config = {"run_root": str(root), "native_control_root": str(root / "native-control"),
            "dataset_manifest": manifest_ref, "image_index": images_ref}
        if grade_hold:
            config.update(phase=phase + "_RUNTIME", training_grade_hold_policy="CAPTURE_KNOWN_TERMINAL_AMBIGUITY_AND_CONTINUE")
        if scale_arms is not None:
            config.update(phase=phase + "_RUNTIME", scale_authority_reference=write(root / "scale-authority.json",
                {"arms": list(scale_arms), "task_ids": [target["target_id"]]}))
            monkeypatch.setattr(execution, "execution_enrollment", lambda config, dataset=None:
                cleanup._checked(config["scale_authority_reference"]) if config.get("scale_authority_reference") else None)
        config_path = root / "execution.json"
        config_ref = write(config_path, config)
        monkeypatch.setattr(execution, "load_experiment", lambda path: cleanup._read(path))
        policy_ref = cleanup.create_cleanup_policy(root / "cleanup-policy.json", experiment_reference=config_ref)
        result = {"root": root, "target": target, "config": config, "policy": policy_ref,
            "image": image, "tag": tag, "cells": {}, "registrations": {}}
        arms = scale_arms or cleanup.PHASE_ARMS[phase]
        for arm in arms:
            task_id = target["target_id"]
            cell_path = root / "cells" / phase / task_id / arm / "cell.json"
            cell_path.parent.mkdir(parents=True)
            checkout = root / "workspaces" / arm / task_id / "checkouts" / task_id
            checkout.mkdir(parents=True)
            (checkout / "public.txt").write_bytes(b"Synthetic public worktree\n")
            output = root / "environment" / phase / "cells" / arm / task_id
            public = {"task_id": task_id, "repository": "fixture/repo", "commit": "a" * 40,
                "instruction": "Synthetic public issue"}
            patch = "diff --git a/public.txt b/public.txt\nSynthetic public patch\n"
            bank_sha = "d" * 64
            broker_root = cell_path.parent / "broker"
            broker = broker_module.ArchitectureBroker.create(broker_root, task_public=public, arm=arm,
                workspace=SimpleNamespace(patch=lambda: patch), configuration_sha256=cleanup._sha(cleanup._canonical(config)),
                bank_sha256=bank_sha, tool_schema={"read_file": {"path": "relative public path"}})
            state, events = broker._load()
            thread_id = "synthetic-thread-" + arm
            state["workers"]["synthetic-worker"] = {"thread_id": thread_id}
            broker._commit(state, events, kind="SYNTHETIC_ADMISSION", request={}, response={})
            broker.seal_partial(reason="SYNTHETIC_COMPLETED_ATTEMPT", summary="Synthetic terminal attempt")
            status = broker.status()
            cell = {"phase": phase, "arm": arm, "task_public": public, "owner_user_id": "owner-1",
                "experiment_config": str(config_path), "broker_root": str(broker_root), "bank_sha256": bank_sha,
                "workspace_configuration": {"checkout_root": str(checkout), "image": image, "command_runner_sha256": "b" * 64},
                "prepared_output_root": str(output), "owned_images": {image: [tag]} if own and arm == arms[0] else {}}
            write(cell_path, cell)
            cell_path.with_suffix(".sha256").write_text(cleanup._sha(cleanup._canonical(cell)) + "\n")
            write(output / "control" / "checkout-preflight.json", {"head": "a" * 40, "initial_status": "",
                "checkout_origin": "FRESH_BASE_ONLY_FETCH", "history_isolation": {"status": "SYNTHETIC_VALID_BASE_ONLY"},
                "command_sandbox_content_hash": "b" * 64})
            for name in ("solver-sandbox-preflight.json", "public-python-preflight.json"):
                write(output / "control" / name, {"status": "PASS", "command_sandbox_content_hash": "b" * 64})
            write(output / "official-grader" / "retained-private-evidence.json", {"synthetic_private": "never decode"})
            native = root / "native-control" / phase / target["instance_id"] / arm / "worker-001" / "output"
            events_ref = write(native / "events.jsonl", {"type": "thread.started", "thread_id": thread_id})
            completion_ref = write(native / "completion.json", {"events_sha256": events_ref["sha256"],
                "thread_id": thread_id, "admitted": True, "errors": [], "outside_broker_tool_events": [],
                "exit_code": 0, "timed_out": False})
            audit_ref = write(cell_path.parent / "execution-audit.json", {"passed": True, "errors": [],
                "task_id": task_id, "arm": arm, "configuration_sha256": cleanup._sha(cleanup._canonical(config)),
                "event_tail_sha256": status["event_tail_sha256"], "patch_sha256": cleanup._sha(patch.encode()),
                "workers": [{"number": 1, "thread_id": thread_id, "completion_sha256": completion_ref["sha256"],
                    "events_sha256": events_ref["sha256"], "outcome": "COMPLETE"}]})
            private = cell_path.parent / "grader-private.json"
            private.write_bytes(b"Synthetic private evaluator bytes, intentionally not JSON")
            public_result = {"task_id": task_id, "phase": phase, "arm": arm, "official": True, "resolved": False,
                "grader_status": "success", "experiment_sha256": cleanup._sha(cleanup._canonical(config)),
                "bank_sha256": bank_sha, "container_digest": image, "patch_sha256": cleanup._sha(patch.encode()),
                "event_tail_sha256": status["event_tail_sha256"], "broker_status": status,
                "execution_audit_sha256": audit_ref["sha256"], "grader_private_sha256": cleanup._file_hash(private)}
            if grade_hold:
                public_result.update(official=False, resolved=None, official_outcome="UNDETERMINED", grader_status="undetermined")
                public_result.pop("grader_private_sha256")
                private.unlink()
            public_ref = write(cell_path.parent / ("training-grade-undetermined.json" if grade_hold else "public-result.json"), public_result)
            if grade_hold:
                def proof(path, *, create=False, _broker_lock=None):
                    assert create is False
                    retained = Path(path).parent / "training-grade-undetermined.json"
                    return cleanup._read(retained), cleanup._reference(retained)
                monkeypatch.setattr(execution, "training_grade_undetermined", proof, raising=False)
            source_refs = {name: cleanup._reference(broker_root / name) for name in
                ("manifest.json", "manifest.sha256", "initial-state.json", "state.json", "events.jsonl", "submission.json", "submission.diff")}
            source_refs["cell.json"] = cleanup._reference(cell_path)
            capture = {"cell_path": str(cell_path), "task_id": task_id, "source_references": source_refs, "failures": []}
            if phase == "TRAINING":
                capture.update(schema="skhynix/native-architecture-learning/1.0", operation="CAPTURE_CELL", status="CAPTURED",
                    owner_user_id="owner-1", captures=[{"synthetic": "retained attempt"}], source_execution_observed=True)
            else:
                capture.update(schema=cleanup.EVALUATION_CAPTURE_SCHEMA, operation="CAPTURE_EVALUATION_CELL",
                    arm=arm, bank_sha256=bank_sha, admitted_to_frozen_bank=False,
                    status="BASELINE_AUDIT_ONLY" if arm == "BASELINE" else "NO_PUBLIC_ATTEMPTS", quarantine_references=[])
            capture_ref = write(root / "captures" / (arm + ".json"), capture)
            registration = {"cell_path": str(cell_path), "experiment_reference": config_ref,
                "result_reference": public_ref, "capture_reference": capture_ref}
            result["cells"][arm] = {"path": cell_path, "cell": cell, "checkout": checkout,
                "result": public_result, "capture": capture, "registration": registration}
            result["registrations"][arm] = registration
        def snapshot(path, commit):
            info = path.stat()
            return {"path": str(path), "device": info.st_dev, "inode": info.st_ino, "base_commit": commit,
                "patch_sha256": cleanup._sha(patch.encode()), "inventory_sha256": "e" * 64}
        monkeypatch.setattr(cleanup, "_workspace_snapshot", snapshot)
        return result
    return build


def invoke(value, arm=None):
    arm = arm or next(iter(value["cells"]))
    item = value["cells"][arm]
    return cleanup.cleanup_completed_cell(item["path"], item["registration"]["result_reference"],
        item["registration"]["capture_reference"], policy_reference=value["policy"])


@pytest.fixture
def simulated_removal(monkeypatch):
    absent, calls = set(), []
    actual_exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda path: False if str(path) in absent else actual_exists(path))
    def remove(snapshot):
        path = Path(snapshot["path"])
        root, task_id = path.parents[4], path.name
        assert (root / "cleanup" / task_id / "intent.json").is_file()
        calls.append(("checkout", snapshot["path"]))
        absent.add(snapshot["path"])
        return {"path": snapshot["path"], "status": "REMOVED_GENERATED_CHECKOUT"}
    def images(owned):
        calls.append(("images", deepcopy(owned)))
        return [{"image": image, "removed": True} for image in owned]
    monkeypatch.setattr(cleanup, "_remove_checkout", remove)
    monkeypatch.setattr(cleanup, "_release_owned_images", images)
    return absent, calls


def test_read_only_plan_binds_base_patch_private_grader_and_capture_without_decoding_private(factory, monkeypatch):
    value = factory()
    monkeypatch.setattr(cleanup, "_remove_checkout", lambda *a: pytest.fail("Read-only plan removed checkout"))
    monkeypatch.setattr(cleanup, "_release_owned_images", lambda *a: pytest.fail("Read-only plan released image"))
    plan = cleanup.plan_target_cleanup(value["policy"], value["target"]["target_id"], registrations=value["registrations"])
    assert plan["cells"][0]["source_commit"] == "a" * 40
    assert plan["cells"][0]["patch_sha256"] == cleanup._file_hash(plan["cells"][0]["patch_reference"]["path"])
    assert any(ref["path"].endswith("grader-private.json") for ref in plan["preserved_references"])
    assert not (value["root"] / "cleanup").exists()


def test_training_unscored_cleanup_preserves_terminal_evidence_without_fabricating_official_grade(factory, simulated_removal):
    value = factory(grade_hold=True)
    item = value["cells"]["PDF_MEMORY"]
    assert invoke(value)["status"] == "COMPLETE"
    payload = cleanup._checked(item["registration"]["result_reference"])
    assert payload["official"] is False and payload["resolved"] is None
    assert not (item["path"].parent / "public-result.json").exists()
    assert not (item["path"].parent / "grader-private.json").exists()
    completion = cleanup.validate_completed_cleanup(item["path"], item["registration"]["result_reference"], item["registration"]["capture_reference"])
    assert completion["broker_status"]["status"] == "SUBMITTED"


def test_unscored_cleanup_never_accepts_evaluation(factory, simulated_removal):
    value = factory("EVALUATION", grade_hold=True)
    with pytest.raises(cleanup.CleanupError, match="training-only"):
        cleanup.plan_target_cleanup(value["policy"], value["target"]["target_id"], registrations=value["registrations"])
    assert simulated_removal[1] == []


def test_unscored_cleanup_requires_independent_terminal_proof(factory, simulated_removal, monkeypatch):
    value = factory(grade_hold=True)
    monkeypatch.setattr(execution, "training_grade_undetermined", lambda *args, **kwargs: None)
    with pytest.raises(cleanup.CleanupError, match="terminal evidence"):
        invoke(value)
    assert simulated_removal[1] == []


@pytest.mark.parametrize("field,value", [("official", True), ("resolved", False), ("grader_status", "success")])
def test_unscored_cleanup_cannot_relabel_an_unknown_outcome(factory, simulated_removal, field, value):
    case = factory(grade_hold=True)
    item = case["cells"]["PDF_MEMORY"]
    item["result"][field] = value
    item["registration"]["result_reference"] = write(Path(item["registration"]["result_reference"]["path"]), item["result"])
    with pytest.raises(cleanup.CleanupError, match="grade is incomplete"):
        invoke(case)
    assert simulated_removal[1] == []


def test_training_cleanup_retains_all_evidence_and_is_idempotent_without_workspace(factory, simulated_removal):
    value = factory()
    result = invoke(value)
    assert result["status"] == "COMPLETE"
    absent, calls = simulated_removal
    assert len(absent) == 1 and calls[-1] == ("images", {value["image"]: [value["tag"]]})
    item = value["cells"]["PDF_MEMORY"]
    receipt = cleanup.validate_completed_cleanup(item["path"], item["registration"]["result_reference"], item["registration"]["capture_reference"])
    assert receipt["status"] == "COMPLETE" and receipt["broker_status"]["status"] == "SUBMITTED"
    before = list(calls)
    assert invoke(value) == result and calls == before
    assert item["path"].is_file() and (item["path"].parent / "grader-private.json").is_file()


def test_evaluation_waits_for_both_completed_captures_then_releases_only_first_arm_owned_image(factory, simulated_removal):
    value = factory("EVALUATION")
    assert invoke(value, "BASELINE") == {"status": "WAITING_FOR_PAIRED_COMPLETION", "cleanup_reference": None}
    assert simulated_removal[1] == []
    result = invoke(value, "PDF_MEMORY")
    assert result["status"] == "COMPLETE"
    assert len(simulated_removal[0]) == 2
    assert simulated_removal[1][-1] == ("images", {value["image"]: [value["tag"]]})
    for item in value["cells"].values():
        assert cleanup.validate_completed_cleanup(item["path"], item["registration"]["result_reference"])["status"] == "COMPLETE"


def test_preexisting_images_are_never_selected(factory, simulated_removal):
    value = factory(own=False)
    invoke(value)
    assert simulated_removal[1][-1] == ("images", {})


def test_evaluation_capture_accepts_bound_native_grade_packet_and_opaque_quarantine_references(factory, simulated_removal):
    value = factory("EVALUATION")
    item = value["cells"]["PDF_MEMORY"]
    native = value["root"] / "native-control" / "EVALUATION" / value["target"]["instance_id"] / "PDF_MEMORY" / "worker-001"
    refs = item["capture"]["source_references"]
    for name in ("public-result.json", "execution-audit.json"):
        refs[name] = cleanup._reference(item["path"].parent / name)
    for name in ("completion.json", "events.jsonl"):
        refs["native/worker-1/" + name] = cleanup._reference(native / "output" / name)
    refs["native/worker-1/launch.json"] = write(native / "output" / "launch.json", {"synthetic": "launch"})
    refs["native/worker-1/packet.json"] = write(native / "packet.json", {"synthetic": "packet"})
    (native / "prompt.txt").write_text("Synthetic public prompt")
    refs["native/worker-1/prompt.txt"] = cleanup._reference(native / "prompt.txt")
    refs["broker/packets/0001.json"] = write(item["path"].parent / "broker" / "packets" / "0001.json", {"synthetic": "packet"})
    authority = value["root"] / "quarantine" / "authority.sqlite"
    authority.parent.mkdir()
    authority.write_bytes(b"Synthetic opaque SQLite bytes, deliberately not JSON")
    item["capture"].update(status="CAPTURED", quarantine_references=[cleanup._reference(authority)])
    item["registration"]["capture_reference"] = write(Path(item["registration"]["capture_reference"]["path"]), item["capture"])
    invoke(value, "BASELINE")
    assert invoke(value, "PDF_MEMORY")["status"] == "COMPLETE"
    assert authority.read_bytes() == b"Synthetic opaque SQLite bytes, deliberately not JSON"


@pytest.mark.parametrize("failure", ["no_capture", "failed_capture", "empty_unexecuted", "private_changed", "worker_changed", "pending"])
def test_incomplete_or_changed_prerequisites_prevent_every_removal(factory, simulated_removal, failure):
    value = factory()
    item = value["cells"]["PDF_MEMORY"]
    if failure == "no_capture":
        item["registration"]["capture_reference"] = None
    elif failure in {"failed_capture", "empty_unexecuted"}:
        capture = item["capture"]
        if failure == "failed_capture":
            capture.update(status="PARTIAL_CAPTURE_FAILURE", failures=[{"synthetic": "failed"}])
        else:
            capture.update(status="NO_PUBLIC_ATTEMPTS", captures=[], source_execution_observed=False)
        item["registration"]["capture_reference"] = write(Path(item["registration"]["capture_reference"]["path"]), capture)
    elif failure == "private_changed":
        (item["path"].parent / "grader-private.json").write_bytes(b"Changed synthetic private bytes")
    elif failure == "worker_changed":
        path = next((value["root"] / "native-control").rglob("completion.json"))
        path.write_bytes(b"{}")
    else:
        write(item["path"].parent / "broker" / "pending.json", {"phase": "FINISHED"})
    with pytest.raises(cleanup.CleanupError):
        invoke(value)
    assert simulated_removal[1] == []


@pytest.mark.parametrize("field,value", [("official", False), ("grader_status", "error"),
    ("patch_sha256", "f" * 64), ("container_digest", "foreign@sha256:" + "f" * 64)])
def test_invalid_official_result_blocks_cleanup(factory, simulated_removal, field, value):
    case = factory()
    item = case["cells"]["PDF_MEMORY"]
    item["result"][field] = value
    item["registration"]["result_reference"] = write(item["path"].parent / "public-result.json", item["result"])
    with pytest.raises(cleanup.CleanupError):
        invoke(case)
    assert simulated_removal[1] == []


def rewrite_cell(item):
    write(item["path"], item["cell"])
    item["path"].with_suffix(".sha256").write_text(cleanup._sha(cleanup._canonical(item["cell"])) + "\n")
    item["capture"]["source_references"]["cell.json"] = cleanup._reference(item["path"])
    item["registration"]["capture_reference"] = write(Path(item["registration"]["capture_reference"]["path"]), item["capture"])


def test_outside_checkout_even_with_updated_cell_checksum_is_rejected(factory, simulated_removal):
    value = factory()
    item = value["cells"]["PDF_MEMORY"]
    item["cell"]["workspace_configuration"]["checkout_root"] = str(value["root"])
    rewrite_cell(item)
    with pytest.raises(cleanup.CleanupError, match="exact generated"):
        invoke(value)
    assert simulated_removal[1] == []


@pytest.mark.parametrize("ownership", ["foreign_image", "foreign_tag"])
def test_unrelated_image_or_tag_ownership_is_rejected(factory, simulated_removal, ownership):
    value = factory()
    item = value["cells"]["PDF_MEMORY"]
    item["cell"]["owned_images"] = ({"foreign@sha256:" + "f" * 64: []} if ownership == "foreign_image"
        else {value["image"]: ["preexisting:unrelated"]})
    rewrite_cell(item)
    with pytest.raises(cleanup.CleanupError, match="ownership evidence"):
        invoke(value)
    assert simulated_removal[1] == []


def test_changed_patch_after_submission_blocks_cleanup(factory, simulated_removal, monkeypatch):
    value = factory()
    original = cleanup._workspace_snapshot
    monkeypatch.setattr(cleanup, "_workspace_snapshot", lambda *a: {**original(*a), "patch_sha256": "f" * 64})
    with pytest.raises(cleanup.CleanupError, match="changed after"):
        invoke(value)
    assert simulated_removal[1] == []


def test_incomplete_image_release_retains_intent_and_allows_explicit_retry(factory, simulated_removal, monkeypatch):
    value = factory()
    monkeypatch.setattr(cleanup, "_release_owned_images", lambda owned: [{"image": image, "removed": False} for image in owned])
    with pytest.raises(cleanup.CleanupError, match="image release is incomplete"):
        invoke(value)
    folder = value["root"] / "cleanup" / value["target"]["target_id"]
    assert (folder / "intent.json").is_file() and (folder / "attempt-0001.json").is_file()
    assert not (folder / "completion.json").exists()
    monkeypatch.setattr(cleanup, "_release_owned_images", lambda owned: [{"image": image, "removed": True} for image in owned])
    assert invoke(value)["status"] == "COMPLETE"


def test_completed_receipt_rejects_changed_retained_patch_without_opening_workspace(factory, simulated_removal, monkeypatch):
    value = factory()
    invoke(value)
    item = value["cells"]["PDF_MEMORY"]
    (item["path"].parent / "broker" / "submission.diff").write_bytes(b"changed retained patch")
    monkeypatch.setattr(cleanup, "_workspace_snapshot", lambda *a: pytest.fail("Receipt reopened deleted workspace"))
    with pytest.raises(cleanup.CleanupError, match="changed"):
        cleanup.validate_completed_cleanup(item["path"], item["registration"]["result_reference"])


def test_remove_checkout_rejects_replaced_inode_before_rmtree(tmp_path, monkeypatch):
    path = tmp_path / "checkout"
    path.mkdir()
    info = path.stat()
    called = []
    def remove(*args, **kwargs):
        called.append(args)
    remove.avoids_symlink_attacks = True
    monkeypatch.setattr(cleanup.shutil, "rmtree", remove)
    with pytest.raises(cleanup.CleanupError, match="identity changed"):
        cleanup._remove_checkout({"path": str(path), "device": info.st_dev, "inode": info.st_ino + 1})
    assert called == [] and path.is_dir()


def test_linked_target_and_linked_parent_are_rejected_without_removal(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "nested").mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    for path in (linked, linked / "nested"):
        with pytest.raises(cleanup.CleanupError):
            cleanup._remove_checkout({"path": str(path), "device": 0, "inode": 0})
    assert (real / "nested").is_dir()


def test_non_linux_cleanup_is_rejected_before_input_access(monkeypatch):
    monkeypatch.setattr(cleanup.sys, "platform", "win32")
    with pytest.raises(cleanup.CleanupError, match="Linux"):
        cleanup.cleanup_completed_cell("C:/untrusted/cell.json", {}, policy_reference={})


@pytest.mark.parametrize("arm", ["BASELINE", "PDF_MEMORY"])
def test_authorized_single_arm_development_cleanup_does_not_wait_for_another_arm(factory, simulated_removal, arm):
    value = factory("EVALUATION", scale_arms=(arm,))
    result = invoke(value, arm)
    assert result["status"] == "COMPLETE" and len(simulated_removal[0]) == 1
    item = value["cells"][arm]
    receipt = cleanup.validate_completed_cleanup(item["path"], item["registration"]["result_reference"], item["registration"]["capture_reference"])
    assert [entry["arm"] for entry in cleanup._checked(receipt["intent_reference"])["cells"]] == [arm]
    assert receipt["preserved_references"] and item["path"].is_file()
    other = "PDF_MEMORY" if arm == "BASELINE" else "BASELINE"
    assert not (item["path"].parent.parent / other).exists()


def test_cleanup_cannot_reduce_paired_final_arms_without_new_authority(factory):
    value = factory("EVALUATION")
    policy = cleanup._checked(value["policy"])
    policy["phase_arms"]["EVALUATION"] = ["BASELINE"]
    ref = write(Path(value["policy"]["path"]), policy)
    with pytest.raises(cleanup.CleanupError, match="arms or scale authority"):
        cleanup.plan_target_cleanup(ref, value["target"]["target_id"], registrations=value["registrations"])
