"""Actual Gate B and controller integration over clearly synthetic test evidence."""
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
import shutil
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
import trimem_skhynix_codex_learning as learning
import trimem_skhynix_codex_memory as bridge
import trimem_skhynix_codex_procedures as procedures
import trimem_skhynix_codex_skill_bank as skills
from enterprise_memory.trimem.agent_runtime import CodingTask
from enterprise_memory.trimem.ppr import DeterministicHashEmbedder
from enterprise_memory.trimem.skill_memory import EpisodeEvidence, SkillMemoryStore, canonical_hash
from test_trimem_skhynix_codex_learning import training_run, write
from test_trimem_skhynix_codex_procedures import named_result


@pytest.fixture(params=["1", "2", "3"])
def components(tmp_path, request):
    return make_components(tmp_path, request.param)


def make_components(tmp_path, version):
    procedure_ids = {"1": procedures.PROCEDURE_ID, "2": procedures.NAMED_PROCEDURE_ID,
                     "3": procedures.MULTI_SOURCE_PROCEDURE_ID}
    profile = procedures.procedure_profile(procedure_ids[version])
    template = profile["template"]
    task = CodingTask("swebench_verified--sympy__sympy-90001", "evaluation-org", "evaluation-user",
        "sympy/sympy", "a" * 40, template.subgoal_signature, {}, ())
    target = learning._task_descriptor(task.public_payload())
    base = tmp_path / "observations.json"
    sources = [training_run(tmp_path / f"training-{index}", index) for index in range(1, 5)]
    learning.freeze_learned_bank(base, sources, [target])
    declaration_path = tmp_path / "declaration.json"
    declaration = procedures.declare_procedure(declaration_path, "fixture-training", ["test-training-3", "test-training-4"], version)
    authority = tmp_path / "authority.sqlite3"
    with SkillMemoryStore(authority) as store:
        episodes = []
        for index in (3, 4):
            bindings = {"source_path": f"pkg/source_{index}.py", "test_path": f"pkg/tests/test_{index}.py",
                        "test_argv": learning.canonical([skills.PUBLIC_PYTHON, "bin/test", f"pkg/tests/test_{index}.py",
                                                         "--no-colors", "--no-subprocess"]).decode()}
            if version in ("2", "3"):
                bindings["test_name"] = "test_fresh_regression"
                bindings["test_argv"] = learning.canonical([skills.PUBLIC_PYTHON, "bin/test", bindings["test_path"],
                    "--no-colors", "--no-subprocess", "-k", bindings["test_name"]]).decode()
            if version == "3":
                source = bindings.pop("source_path")
                bindings["source_paths"] = learning.canonical(sorted([source, f"pkg/helper_{index}.py"])).decode()
            rendered = template.render(bindings)
            evidence = EpisodeEvidence(org_id="fixture-training", user_id=f"native-session-{index}",
                repository="sympy/sympy", task_id=f"test-training-{index}", revision=str(index) * 40,
                subgoal=template.subgoal_signature, summary="Synthetic verified workflow fixture",
                actions=rendered.steps, succeeded=True, verification_command=rendered.verification_command,
                verification_evidence_hash="sha256:" + str(index) * 64,
                created_at="2026-01-01T00:00:00Z", procedure_hash=template.content_hash,
                parameter_bindings=tuple(sorted(bindings.items())))
            episodes.append(store.record_episode(evidence))
        promoted = store.promote_skill(template, [row.episode_id for row in episodes], org_id="fixture-training")
    attestations = []
    for index in (3, 4):
        path = tmp_path / f"attestation-{index}-private.json"
        path.write_bytes(b"PRIVATE_CONTENT_MUST_NEVER_BE_DECODED")
        attestations.append({**skills._ref(path), "attestation_sha256": str(index) * 64})
    view = promoted.execution_view()
    export = {"schema": profile["export_schema"], "status": "ACTUALLY_PROMOTED_BY_GATE_B",
        "declaration_sha256": declaration["sha256"], "declaration": skills._ref(declaration_path),
        "procedure_id": profile["procedure_id"], "authority_org_id": promoted.org_id,
        "training_task_ids": ["test-training-3", "test-training-4"], "contributor_count": 2,
        "verified_skill_count": 1, "authority_db": skills._ref(authority), "attestations": attestations,
        "promoted_skill": asdict(promoted), "public_execution_view": view,
        "public_execution_view_sha256": learning.sha(view.encode()), "public_execution_view_bytes": len(view.encode()),
        "training_runner_sha256": ["b" * 64], "target_fix_validated": False,
        "source_revisions_rebound": False, "same_public_payload_required_for_memory_arms": True,
        "model_api_calls": 0}
    export_path = tmp_path / "promoted.json"
    write(export_path, export)
    result = {"stdout": "22 passed", "stderr": "", "exit_code": 0,
              "timed_out": False, "output_truncated": False}
    shared = {"target": target, "runner_sha256": "b" * 64, "python_executable": skills.PUBLIC_PYTHON,
        "python_version": "3.9.20", "clean_checkout_before_after": True, "solver_actions_used": 0,
        "source_image": "swebench/sweb.eval.x86_64.sympy_1776_sympy-90001@sha256:" + "c" * 64}
    raw = {**shared, "argv": skills.SMOKE_ARGV, "result": result,
        "python_version_argv": [skills.PUBLIC_PYTHON, "-c", "import platform; print(platform.python_version())"],
        "python_version_result": {"exit_code": 0, "stdout": "3.9.20\n", "stderr": ""}}
    evidence_path = tmp_path / "public-evidence.json"
    if version in ("2", "3"):
        raw["schema"] = (skills.MULTI_SOURCE_COMPATIBILITY_EVIDENCE_SCHEMA if version == "3"
                         else skills.NAMED_COMPATIBILITY_EVIDENCE_SCHEMA)
        raw["named_public_test"] = {"test_name": skills.NAMED_SMOKE_TEST, "argv": skills.NAMED_SMOKE_ARGV,
                                    "result": named_result(skills.NAMED_SMOKE_ARGV)}
        if version == "3":
            raw["procedure_id"] = procedures.MULTI_SOURCE_PROCEDURE_ID
    write(evidence_path, raw)
    certificate_path = tmp_path / "compatibility.json"
    certificate = {**shared, "public_test": {"argv": skills.SMOKE_ARGV, "exit_code": 0,
        "passed_count": 22, "observation_sha256": learning.sha(learning.canonical(result))},
        "evidence_ref": skills._ref(evidence_path)}
    if version in ("2", "3"):
        certificate["schema"] = (skills.MULTI_SOURCE_COMPATIBILITY_SCHEMA if version == "3"
                                 else skills.NAMED_COMPATIBILITY_SCHEMA)
        certificate["named_public_test"] = {"test_name": skills.NAMED_SMOKE_TEST, "argv": skills.NAMED_SMOKE_ARGV,
            "exit_code": 0, "passed_count": 1,
            "observation_sha256": learning.sha(learning.canonical(raw["named_public_test"]["result"]))}
        if version == "3":
            certificate["procedure_id"] = procedures.MULTI_SOURCE_PROCEDURE_ID
    write(certificate_path, certificate)
    return {"task": task, "base": base, "export": export_path, "certificate": certificate_path,
            "authority": authority, "evidence": evidence_path, "promoted": promoted,
            "output": tmp_path / "skill-bank.json", "template": template}


def freeze(parts):
    return skills.freeze_skill_bank(parts["base"], parts["export"], [parts["certificate"]], parts["output"])


@pytest.fixture
def frozen(components):
    return {**components, "receipt": freeze(components)}


def load(parts):
    return learning.load_frozen_bank(parts["output"], learning.file_sha(parts["output"]), parts["task"])


def test_freeze_preserves_four_observations_and_actual_skill_without_private_content(frozen):
    bank = load(frozen)
    original = learning.read(frozen["base"])
    assert bank.manifest["schema"] == skills.SCHEMA
    assert bank.manifest["records"] == original["records"] and len(bank.records) == 4
    assert bank.manifest["gate_a"] == original["gate_a"]
    assert bank.manifest["gate_b"]["verified_skill_count"] == 1
    assert bank.promoted_skill == frozen["promoted"]
    assert bank.promoted_skill.org_id == "fixture-training" != frozen["task"].org_id
    assert "PRIVATE_CONTENT_MUST_NEVER_BE_DECODED" not in frozen["output"].read_text()
    assert bank.report["workflow_projection"]["target_fix_correctness_verified"] is False


def test_private_refs_are_only_hashed_never_json_decoded(frozen, monkeypatch):
    original = learning.read
    forbidden = {str(frozen["authority"]), *[row["path"] for row in original(frozen["export"])["attestations"]]}
    def public_only(path):
        assert str(path) not in forbidden
        return original(path)
    monkeypatch.setattr(learning, "read", public_only)
    assert load(frozen).promoted_skill.support_count == 2


@pytest.mark.parametrize("field,value", [("runner_sha256", "e" * 64), ("python_version", "3.10.0"),
    ("python_executable", "/other/python"), ("clean_checkout_before_after", False),
    ("solver_actions_used", 1), ("source_image", "swebench/sweb.eval.x86_64.sympy_1776_sympy-90002@sha256:" + "c" * 64)])
def test_incompatible_public_scope_cannot_be_frozen(components, field, value):
    receipt = learning.read(components["certificate"])
    receipt[field] = value
    write(components["certificate"], receipt)
    with pytest.raises(skills.SkillBankError, match="compatibility"):
        freeze(components)
    assert not components["output"].exists()


@pytest.mark.parametrize("field,value", [("passed_count", 23), ("exit_code", 1),
    ("observation_sha256", "f" * 64), ("argv", ["echo", "22 passed"])])
def test_certificate_must_match_hashed_real_public_observation(components, field, value):
    receipt = learning.read(components["certificate"])
    receipt["public_test"][field] = value
    write(components["certificate"], receipt)
    with pytest.raises(skills.SkillBankError, match="compatibility"):
        freeze(components)


def test_pass_count_is_rederived_not_fixed_to_one_target_baseline(components):
    evidence = learning.read(components["evidence"])
    evidence["result"]["stdout"] = "24 passed"
    write(components["evidence"], evidence)
    receipt = learning.read(components["certificate"])
    receipt["public_test"].update(passed_count=24,
        observation_sha256=learning.sha(learning.canonical(evidence["result"])))
    receipt["evidence_ref"] = skills._ref(components["evidence"])
    write(components["certificate"], receipt)
    assert freeze(components)["verified_skills"] == 1


@pytest.mark.parametrize("changes", [{"commit": "f" * 40}, {"org_id": "different-org"},
    {"user_id": "different-user"}, {"repository": "other/repository"}])
def test_projection_snapshot_requires_exact_task_scope(frozen, changes):
    bank, task = load(frozen), frozen["task"]
    store, report = learning.build_learned_seeded_store(":memory:", task, bank)
    try:
        scope = dict(org_id=task.org_id, user_id=task.user_id, repository=task.repository,
                     revision=task.commit, language="python")
        for key, value in changes.items():
            scope["revision" if key == "commit" else key] = value
        with pytest.raises(skills.SkillBankError, match="query scope"):
            store.snapshot(**scope)
        assert report["seed_skill_count"] == 1
    finally:
        store.close()


def test_underlying_store_keeps_original_revision_filter_and_no_episodes_are_relabelled(frozen, tmp_path):
    skill = frozen["promoted"]
    before = learning.file_sha(frozen["authority"])
    # The production store constructor writes its schema metadata. Probe a
    # test-only copy; the frozen projection never opens the authority as SQLite.
    probe = tmp_path / "authority-filter-probe.sqlite3"
    shutil.copyfile(frozen["authority"], probe)
    with SkillMemoryStore(probe) as authority:
        old = authority.snapshot(org_id=skill.org_id, user_id="native-session-3", repository="sympy/sympy",
                                 revision=frozen["task"].commit, language="python")
        assert old.skills == ()
        assert old.episodes[0].evidence.revision == "3" * 40
    assert learning.file_sha(frozen["authority"]) == before
    bank, task = load(frozen), frozen["task"]
    store, _ = learning.build_learned_seeded_store(":memory:", task, bank)
    try:
        scope = dict(org_id=task.org_id, user_id=task.user_id, repository=task.repository,
                     revision=task.commit, language="python")
        assert store.base_store.snapshot(**scope).skills == ()
        projected = store.snapshot(**scope)
        assert projected.skills == (skill,) and projected.episodes == ()
        assert len(projected.repository_knowledge) == 4
    finally:
        store.close()


def test_revocation_invalidates_loaded_bank_and_live_projection(frozen):
    bank, task = load(frozen), frozen["task"]
    store, _ = learning.build_learned_seeded_store(":memory:", task, bank)
    try:
        with SkillMemoryStore(frozen["authority"]) as authority:
            assert authority.invalidate_skill(org_id=frozen["promoted"].org_id,
                skill_id=frozen["promoted"].skill_id, reason="unit test revocation")
        with pytest.raises(skills.SkillBankError, match="hash differs"):
            load(frozen)
        with pytest.raises(skills.SkillBankError, match="hash differs"):
            store.snapshot(org_id=task.org_id, user_id=task.user_id, repository=task.repository,
                           revision=task.commit, language="python")
    finally:
        store.close()


@pytest.mark.parametrize("arm", bridge.ARMS)
def test_actual_controllers_and_resume_preserve_exact_skill_view_and_arm_counts(frozen, tmp_path, monkeypatch, arm):
    monkeypatch.setattr(bridge, "_m2_embedder", lambda: DeterministicHashEmbedder(384))
    task = frozen["task"]
    kwargs = {"frozen_bank_path": frozen["output"], "frozen_bank_sha256": frozen["receipt"]["sha256"]}
    cell = tmp_path / arm
    manifest = bridge.initialize_memory(cell, task, arm, ROOT, **kwargs)
    assert manifest["seed_skill_count"] == (1 if arm == "SKHYNIX" else 0)
    assert manifest["verified_skill_payload_count"] == (0 if arm == "NO_MEMORY" else 1)
    assert manifest["seed_episode_count"] == 0
    query = {"node_id": "public-regression", "objective": frozen["template"].subgoal_signature,
             "operation": "reproduce assertion failure repair implementation verify focused public tests"}
    response = bridge.recall_memory(cell, task, arm, query, ROOT, **kwargs)
    if arm == "NO_MEMORY":
        assert not response["injections"]
    else:
        matching = [row for row in response["injections"] if row["memory_id"] == frozen["promoted"].skill_id]
        assert len(matching) == 1, response
        assert matching[0]["exact_text"] == frozen["promoted"].execution_view()
        assert matching[0]["kind"] == ("SKILL" if arm == "SKHYNIX" else "ORG_SEMANTIC")
    again = bridge.recall_memory(cell, task, arm, query, ROOT, **kwargs)
    assert again["repeat"] and again["injections"] == response["injections"]
    assert again["new_injection_count"] == 0
    resumed = bridge.initialize_memory(cell, task, arm, ROOT, **kwargs)
    assert resumed["budget"] == response["budget"]
    assert resumed["binding_sha256"] == manifest["binding_sha256"]
    assert response["budget"]["max_task_injections"] == 3 and response["budget"]["context_budget_bytes"] == 12_000


@pytest.mark.parametrize("arm", ["EXISTING_M2", "SKHYNIX"])
def test_retained_controller_cannot_resume_after_authority_revocation(frozen, tmp_path, monkeypatch, arm):
    monkeypatch.setattr(bridge, "_m2_embedder", lambda: DeterministicHashEmbedder(384))
    kwargs = {"frozen_bank_path": frozen["output"], "frozen_bank_sha256": frozen["receipt"]["sha256"]}
    cell, task = tmp_path / arm, frozen["task"]
    bridge.initialize_memory(cell, task, arm, ROOT, **kwargs)
    query = {"node_id": "workflow", "objective": task.instruction, "operation": "public regression verification"}
    bridge.recall_memory(cell, task, arm, query, ROOT, **kwargs)
    with SkillMemoryStore(frozen["authority"]) as authority:
        authority.invalidate_skill(org_id=frozen["promoted"].org_id, skill_id=frozen["promoted"].skill_id, reason="revoked")
    with pytest.raises(skills.SkillBankError, match="hash differs"):
        bridge.recall_memory(cell, task, arm, query, ROOT, **kwargs)


@pytest.mark.parametrize("target", ["export", "certificate", "evidence", "base"])
def test_changed_frozen_dependency_fails_closed(frozen, target):
    with frozen[target].open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(skills.SkillBankError, match="hash differs"):
        load(frozen)


def test_recomputed_outer_hash_cannot_change_source_skill_content_or_projection_policy(frozen):
    value = learning.read(frozen["output"])
    value["skill_projection"]["source_episode_revisions_rebound"] = True
    write(frozen["output"], value)
    with pytest.raises(skills.SkillBankError, match="projection policy"):
        load(frozen)


def test_promoted_public_view_is_verified_against_actual_skill(components):
    value = learning.read(components["export"])
    value["public_execution_view"] += "altered"
    value["public_execution_view_sha256"] = learning.sha(value["public_execution_view"].encode())
    value["public_execution_view_bytes"] = len(value["public_execution_view"].encode())
    write(components["export"], value)
    with pytest.raises(skills.SkillBankError, match="public skill"):
        freeze(components)


def test_hash_consistent_forged_export_must_join_actual_shared_authority_row(components):
    value = learning.read(components["export"])
    value["promoted_skill"]["promoted_at"] = "2025-01-01T00:00:00Z"
    payload = deepcopy(value["promoted_skill"])
    payload.pop("content_hash")
    value["promoted_skill"]["content_hash"] = canonical_hash(payload)
    write(components["export"], value)
    with pytest.raises(skills.SkillBankError, match="shared authority row"):
        freeze(components)


def test_hash_consistent_wrong_authority_cannot_authorize_public_skill(components, tmp_path):
    other = tmp_path / "unrelated-authority.sqlite3"
    with SkillMemoryStore(other):
        pass
    value = learning.read(components["export"])
    value["authority_db"] = skills._ref(other)
    write(components["export"], value)
    before = learning.file_sha(other)
    with pytest.raises(skills.SkillBankError, match="shared authority row"):
        freeze(components)
    assert learning.file_sha(other) == before


@pytest.mark.parametrize("mutation", ["shared_revoked", "support_missing", "support_revoked", "support_owner",
                                      "support_org", "support_revision", "support_hash", "support_task"])
def test_rehashed_authority_with_invalid_support_cannot_be_admitted(components, mutation):
    with sqlite3.connect(components["authority"]) as connection:
        if mutation == "shared_revoked":
            connection.execute("UPDATE memory_records SET revoked=1 WHERE kind='skill'")
        elif mutation == "support_missing":
            connection.execute("DELETE FROM skill_support WHERE episode_id=(SELECT min(episode_id) FROM skill_support)")
        else:
            clause = {
                "support_revoked": "revoked=1", "support_owner": "owner_user_id='unobserved-owner'",
                "support_org": "org_id='other-org'", "support_revision": "revision='outdated-revision'",
                "support_hash": "content_hash='sha256:" + "9" * 64 + "'",
                "support_task": "payload=json_set(payload,'$.evidence.task_id','undeclared-task')",
            }[mutation]
            connection.execute("UPDATE memory_records SET " + clause + " WHERE kind='episode'")
    value = learning.read(components["export"])
    value["authority_db"] = skills._ref(components["authority"])
    write(components["export"], value)
    with pytest.raises(skills.SkillBankError, match="authority"):
        freeze(components)


def test_authority_join_is_read_only_and_preserves_exact_bytes(frozen, monkeypatch):
    before = learning.file_sha(frozen["authority"])
    original, calls = sqlite3.connect, []
    def read_only_connect(path, *args, **kwargs):
        calls.append((path, kwargs))
        assert str(path).endswith("?mode=ro") and kwargs.get("uri") is True
        return original(path, *args, **kwargs)
    monkeypatch.setattr(skills.sqlite3, "connect", read_only_connect)
    bank = load(frozen)
    assert bank.promoted_skill == frozen["promoted"]
    assert calls and learning.file_sha(frozen["authority"]) == before
    certificate = skills.runtime_certificate_for_bank(bank)
    assert certificate["target"] == bank.target and certificate["python_executable"] == skills.PUBLIC_PYTHON
    certificate["target"]["commit"] = "changed"
    assert skills.runtime_certificate_for_bank(bank)["target"] == bank.target


@pytest.fixture(params=["2", "3"])
def named_components(tmp_path, request):
    return make_components(tmp_path, request.param)


@pytest.mark.parametrize("mutation", ["missing", "name", "argv", "count", "digest"])
def test_named_promotion_requires_its_additional_exact_probe_certificate(named_components, mutation):
    certificate = learning.read(named_components["certificate"])
    if mutation == "missing":
        certificate.pop("named_public_test")
    else:
        key, value = {"name": ("test_name", "test_other"), "argv": ("argv", skills.SMOKE_ARGV),
            "count": ("passed_count", 2), "digest": ("observation_sha256", "0" * 64)}[mutation]
        certificate["named_public_test"][key] = value
    write(named_components["certificate"], certificate)
    with pytest.raises(skills.SkillBankError, match="named public compatibility"):
        freeze(named_components)


@pytest.mark.parametrize("mutation", ["missing", "name", "argv", "result_argv", "cwd", "loose_pass",
    "two_tests", "truncated", "timeout", "missing_flag", "skip"])
def test_rehashed_named_probe_evidence_cannot_invent_one_executed_test(named_components, mutation):
    raw = learning.read(named_components["evidence"])
    named = raw["named_public_test"]
    response = named["result"]
    if mutation == "missing":
        raw.pop("named_public_test")
    elif mutation == "name":
        named["test_name"] = "test_other"
    elif mutation == "argv":
        named["argv"] = skills.SMOKE_ARGV
    elif mutation == "result_argv":
        response["argv"] = ["echo", "1 passed"]
    elif mutation == "cwd":
        response["cwd"] = "/elsewhere"
    elif mutation == "loose_pass":
        response["stdout"] = "1 passed"
    elif mutation == "two_tests":
        response["stdout"] = response["stdout"].replace("[1] .", "[2] ..").replace("1 passed", "2 passed")
    elif mutation == "truncated":
        response["output_truncated"] = True
    elif mutation == "timeout":
        response["timed_out"] = True
    elif mutation == "missing_flag":
        response.pop("timed_out")
    elif mutation == "skip":
        response["stdout"] = response["stdout"].replace("1 passed", "1 skipped")
    write(named_components["evidence"], raw)
    certificate = learning.read(named_components["certificate"])
    certificate["evidence_ref"] = skills._ref(named_components["evidence"])
    certificate["named_public_test"]["observation_sha256"] = learning.sha(learning.canonical(response))
    write(named_components["certificate"], certificate)
    with pytest.raises(skills.SkillBankError, match="named public compatibility"):
        freeze(named_components)


@pytest.mark.parametrize("field,value", [("schema", procedures.EXPORT_SCHEMA),
    ("procedure_id", procedures.PROCEDURE_ID), ("procedure_id", "unrecognized-version")])
def test_named_skill_export_cannot_fall_back_to_a_v1_or_unknown_contract(named_components, field, value):
    export = learning.read(named_components["export"])
    export[field] = value
    write(named_components["export"], export)
    with pytest.raises(skills.SkillBankError, match="public skill"):
        freeze(named_components)


@pytest.mark.parametrize("document", ["certificate", "evidence"])
@pytest.mark.parametrize("field,value", [
    ("schema", None), ("schema", "skhynix/public-workflow-compatibility/2.0"),
    ("schema", "skhynix/public-workflow-compatibility-evidence/2.0"),
    ("procedure_id", None), ("procedure_id", procedures.PROCEDURE_ID),
    ("procedure_id", procedures.NAMED_PROCEDURE_ID), ("procedure_id", "unrecognized-version"),
])
def test_multisource_runtime_requires_both_exact_versioned_evidence_identities(tmp_path, document, field, value):
    parts = make_components(tmp_path, "3")
    changed = learning.read(parts[document])
    if value is None:
        changed.pop(field)
    else:
        changed[field] = value
    write(parts[document], changed)
    if document == "evidence":
        certificate = learning.read(parts["certificate"])
        certificate["evidence_ref"] = skills._ref(parts["evidence"])
        write(parts["certificate"], certificate)
    with pytest.raises(skills.SkillBankError, match="named public compatibility"):
        freeze(parts)
    assert not parts["output"].exists()


@pytest.mark.parametrize("field,value", [("schema", procedures.NAMED_EXPORT_SCHEMA),
    ("procedure_id", procedures.NAMED_PROCEDURE_ID)])
def test_multisource_export_cannot_substitute_a_single_source_named_contract(tmp_path, field, value):
    parts = make_components(tmp_path, "3")
    export = learning.read(parts["export"])
    export[field] = value
    write(parts["export"], export)
    with pytest.raises(skills.SkillBankError, match="public skill"):
        freeze(parts)
