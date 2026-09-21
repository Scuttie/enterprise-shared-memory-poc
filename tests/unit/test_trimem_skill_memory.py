"""Trust, promotion and restart invariants for the local PDF architecture."""
from dataclasses import FrozenInstanceError, asdict, replace
import json
import sqlite3

import pytest

from enterprise_memory.trimem.schema import canonical_hash
from enterprise_memory.trimem.skill_memory import (
    EpisodeEvidence,
    ProcedureTemplate,
    PromotionRejected,
    SkillMemoryError,
    SkillMemoryStore,
)


ORG = "organisation-one"
REPO = "private-team/first-repository"
REVISION = "revision-one"


def template(**overrides):
    values = dict(
        subgoal_signature="normalize case insensitive extension matching",
        parameters=("source_file", "test_file"),
        preconditions=("{source_file} validates file extensions",),
        steps=("Inspect {source_file}", "Normalize extension comparison in {source_file}"),
        verification_command="python -m pytest {test_file}",
        language="python",
    )
    values.update(overrides)
    return ProcedureTemplate(**values)


def evidence(index=1, procedure=None, **overrides):
    procedure = procedure or template()
    bindings = {"source_file": f"src/private_{index}.py", "test_file": f"tests/private_{index}.py"}
    rendered = procedure.render(bindings)
    values = dict(
        org_id=ORG, user_id=f"private-user-{index}", repository=REPO,
        task_id=f"source-task-{index}", revision=REVISION,
        subgoal="normalize case insensitive extension matching",
        summary=f"Private source: private-user-{index}@example.org",
        actions=rendered.steps, succeeded=True,
        verification_command=rendered.verification_command,
        verification_evidence_hash=canonical_hash({"verifier": index}),
        created_at=f"2026-09-10T10:00:0{index}Z",
        procedure_hash=procedure.content_hash,
        parameter_bindings=tuple(bindings.items()),
    )
    values.update(overrides)
    return EpisodeEvidence(**values)


def promoted(store, procedure=None):
    procedure = procedure or template()
    episodes = [store.record_episode(evidence(i, procedure)) for i in (1, 2)]
    skill = store.promote_skill(procedure, [row.episode_id for row in episodes], org_id=ORG)
    return skill, episodes


def snapshot(store, **overrides):
    values = dict(org_id=ORG, user_id="private-user-1", repository=REPO,
                  revision=REVISION, language="python")
    values.update(overrides)
    return store.snapshot(**values)


def test_gate_a_keeps_successes_and_failed_attempts_private(tmp_path):
    with SkillMemoryStore(tmp_path / "memory.db") as store:
        success = store.record_episode(evidence())
        failed = store.record_episode(evidence(2, user_id="private-user-1", succeeded=False,
                                               verification_evidence_hash="", procedure_hash=""))
        own = snapshot(store)
        assert {row.episode_id for row in own.episodes} == {success.episode_id, failed.episode_id}
        assert own.episodes[0].evidence.succeeded is False
        assert snapshot(store, user_id="different-user").episodes == ()
        assert snapshot(store, org_id="different-org").episodes == ()
        assert snapshot(store, repository="different/repository").episodes == ()
        assert store.get_episode(success.episode_id, org_id=ORG, user_id="different-user") is None
        assert store.get_episode(success.episode_id, org_id=ORG, user_id="private-user-1") == success


def test_gate_a_restart_is_idempotent_and_preserves_first_timestamp(tmp_path):
    path = tmp_path / "memory.db"
    with SkillMemoryStore(path) as store:
        first = store.record_episode(evidence())
        original_snapshot = snapshot(store)
    with SkillMemoryStore(path) as store:
        repeated = store.record_episode(replace(evidence(), created_at="2026-09-11T10:00:00Z"))
        assert repeated == first
        assert snapshot(store) == original_snapshot
        with pytest.raises(SkillMemoryError, match="immutable"):
            store.record_episode(replace(evidence(), summary="conflicting new summary"))
        assert len(snapshot(store).episodes) == 1


def test_private_artifact_links_survive_restart_and_are_absent_from_skill_view(tmp_path):
    path = tmp_path / "memory.db"
    artifacts = (("patch", canonical_hash("exact patch bytes")),
                 ("public_evidence", canonical_hash("exact public test output")))
    with SkillMemoryStore(path) as store:
        first = store.record_episode(evidence(artifact_hashes=artifacts))
        second = store.record_episode(evidence(2))
        skill = store.promote_skill(template(), [first.episode_id, second.episode_id], org_id=ORG)
        public = skill.execution_view()
        assert "artifact_hashes" not in public
        assert all(digest not in public for _, digest in artifacts)
    with SkillMemoryStore(path) as store:
        restored = store.get_episode(first.episode_id, org_id=ORG, user_id="private-user-1")
        assert restored == first
        assert restored.evidence.artifact_hashes == artifacts
        assert store.get_episode(first.episode_id, org_id=ORG, user_id="other-user") is None


@pytest.mark.parametrize("artifacts", [
    (("patch", "sha256:invalid"),),
    (("", canonical_hash("patch")),),
    (("patch", canonical_hash("first")), ("patch", canonical_hash("second"))),
    (("patch",),),
])
def test_private_artifact_links_require_unique_labels_and_canonical_hashes(artifacts):
    with pytest.raises(SkillMemoryError):
        evidence(artifact_hashes=artifacts)


def test_gate_b_promotes_exact_parameterised_pattern_without_private_evidence(tmp_path):
    with SkillMemoryStore(tmp_path / "memory.db") as store:
        skill, episodes = promoted(store)
        assert skill.support_count == 2 and skill.contributor_count == 2
        text = skill.execution_view()
        assert "{source_file}" in text and "verification_command" in text
        for row in episodes:
            for private in (row.episode_id, row.evidence.user_id, row.evidence.task_id,
                            row.evidence.repository, row.evidence.summary,
                            row.evidence.verification_evidence_hash):
                assert private not in text
        assert snapshot(store, user_id="third-user").skills == (skill,)
        assert snapshot(store, user_id="third-user").episodes == ()
        assert snapshot(store, org_id="other-organisation").skills == ()
        assert store.promote_skill(template(), [row.episode_id for row in episodes], org_id=ORG) == skill
        with pytest.raises(FrozenInstanceError):
            skill.support_count = 900


@pytest.mark.parametrize("change", [
    {"user_id": "private-user-1"},
    {"task_id": "source-task-1"},
    {"verification_evidence_hash": canonical_hash({"verifier": 1})},
    {"succeeded": False},
    {"verification_evidence_hash": ""},
    {"procedure_hash": ""},
    {"procedure_hash": canonical_hash("unrelated procedure")},
    {"actions": ("An unrelated fix happened to pass",)},
    {"verification_command": "echo pretend-success"},
    {"parameter_bindings": (("source_file", "src/only.py"),)},
])
def test_gate_b_rejects_non_independent_or_unbound_support(tmp_path, change):
    with SkillMemoryStore(tmp_path / "memory.db") as store:
        first = store.record_episode(evidence())
        second = store.record_episode(evidence(2, **change))
        with pytest.raises(PromotionRejected):
            store.promote_skill(template(), [first.episode_id, second.episode_id], org_id=ORG)
        assert snapshot(store).skills == ()


def test_repeating_one_episode_cannot_inflate_support(tmp_path):
    with SkillMemoryStore(tmp_path / "memory.db") as store:
        row = store.record_episode(evidence())
        with pytest.raises(PromotionRejected, match="two independent"):
            store.promote_skill(template(), [row.episode_id] * 20, org_id=ORG)


def test_gate_b_cannot_read_evidence_across_organisations(tmp_path):
    with SkillMemoryStore(tmp_path / "memory.db") as store:
        first = store.record_episode(evidence())
        second = store.record_episode(evidence(2, org_id="other-org"))
        with pytest.raises(PromotionRejected, match="unavailable"):
            store.promote_skill(template(), [first.episode_id, second.episode_id], org_id=ORG)


@pytest.mark.parametrize("signature", [
    "normalize private-user-1@example.org extension matching",
    "normalize private-team/first-repository extension matching",
    "normalize src/private_1.py extension matching",
])
def test_gate_b_rejects_unparameterised_private_instances(tmp_path, signature):
    procedure = template(subgoal_signature=signature)
    with SkillMemoryStore(tmp_path / "memory.db") as store:
        with pytest.raises(PromotionRejected):
            promoted(store, procedure)
        assert snapshot(store).skills == ()


@pytest.mark.parametrize("changes", [
    {"parameters": ()},
    {"parameters": ("source_file", "test_file", "unused")},
    {"parameters": ("source_file", "source_file")},
    {"steps": ()},
    {"preconditions": ()},
    {"verification_command": ""},
    {"steps": ("Inspect {source_file.__class__}",)},
    {"steps": ("Inspect {source_file!r}",)},
    {"steps": ("Inspect {source_file:>10}",)},
    {"steps": ("Inspect {undeclared}",)},
])
def test_procedure_requires_structured_fully_declared_parameters(changes):
    with pytest.raises(SkillMemoryError):
        template(**changes)


def test_render_is_data_only_and_requires_exact_bindings(tmp_path):
    with SkillMemoryStore(tmp_path / "memory.db") as store:
        skill, _ = promoted(store)
        for bindings in ({}, {"source_file": "src/a.py"},
                         {"source_file": "src/a.py", "test_file": "tests/a.py", "extra": "bad"}):
            with pytest.raises(SkillMemoryError):
                skill.execution_view(bindings)
        rendered = json.loads(skill.execution_view({"source_file": "src/a.py", "test_file": "tests/a.py"}))
        assert rendered["steps"][0] == "Inspect src/a.py"
        assert rendered["verification_command"] == "python -m pytest tests/a.py"
        assert not (tmp_path / "src" / "a.py").exists()


def test_repo_knowledge_and_edges_are_team_shared_revision_bound(tmp_path):
    with SkillMemoryStore(tmp_path / "memory.db") as store:
        args = dict(org_id=ORG, repository=REPO, revision=REVISION, language="python")
        first = store.put_repository_knowledge(title="Loader convention", content="Normalize suffixes", **args)
        second = store.put_repository_knowledge(title="Test ownership", content="Parser tests live in tests", **args)
        store.link_repository_knowledge(first.knowledge_id, second.knowledge_id, "VERIFIED_BY", org_id=ORG, repository=REPO)
        shared = snapshot(store, user_id="team-colleague")
        assert set(shared.repository_knowledge) == {first, second}
        assert shared.knowledge_edges == ((first.knowledge_id, second.knowledge_id, 1.0),)
        for scope in ({"revision": ""}, {"revision": "new-revision"},
                      {"repository": "another/repository"}, {"org_id": "other-org"},
                      {"language": "rust"}, {"language": ""}):
            observed = snapshot(store, **scope)
            assert observed.repository_knowledge == () and observed.knowledge_edges == ()
        foreign = store.put_repository_knowledge(title="Unrelated", content="Foreign data", **{**args, "repository": "foreign/repo"})
        with pytest.raises(SkillMemoryError, match="crosses"):
            store.link_repository_knowledge(first.knowledge_id, foreign.knowledge_id, "CALLS", org_id=ORG, repository=REPO)


def test_skill_language_and_current_repository_revision_filter(tmp_path):
    with SkillMemoryStore(tmp_path / "memory.db") as store:
        skill, _ = promoted(store)
        assert snapshot(store).skills == (skill,)
        assert snapshot(store, language="rust").skills == ()
        assert snapshot(store, language="").skills == ()
        assert snapshot(store, revision="refactored-revision").skills == ()
        # The generic procedure is usable in a different repository after binding.
        assert snapshot(store, repository="new-team/new-repo", revision="different-revision").skills == (skill,)


def test_hard_invalidation_persists_and_stale_evidence_cannot_repromote(tmp_path):
    path = tmp_path / "memory.db"
    with SkillMemoryStore(path) as store:
        skill, episodes = promoted(store)
        store.put_repository_knowledge(org_id=ORG, repository=REPO, title="Old ownership",
                                       content="The parser owns this file", revision=REVISION)
        before = snapshot(store)
        assert store.invalidate_repository(org_id=ORG, repository=REPO, current_revision="revision-two") == 2
        assert store.invalidate_repository(org_id=ORG, repository=REPO, current_revision="revision-two") == 0
        after = snapshot(store)
        assert not after.skills and not after.repository_knowledge
        assert after.episodes == before.episodes
        assert before.content_hash != after.content_hash
        with pytest.raises(PromotionRejected, match="invalidated"):
            store.promote_skill(template(), [row.episode_id for row in episodes], org_id=ORG, skill_id="new-skill-id")
    with SkillMemoryStore(path) as store:
        assert snapshot(store).content_hash == after.content_hash
        assert not snapshot(store, repository="other/repo").skills


def test_explicit_revocation_is_scoped_permanent_and_changes_snapshot(tmp_path):
    with SkillMemoryStore(tmp_path / "memory.db") as store:
        skill, episodes = promoted(store)
        before = snapshot(store)
        assert not store.invalidate_skill(org_id="other-org", skill_id=skill.skill_id, reason="wrong tenant")
        assert store.invalidate_skill(org_id=ORG, skill_id=skill.skill_id, reason="CI regression")
        assert not store.invalidate_skill(org_id=ORG, skill_id=skill.skill_id, reason="already revoked")
        assert snapshot(store).content_hash != before.content_hash
        with pytest.raises(SkillMemoryError, match="revoked"):
            store.promote_skill(template(), [row.episode_id for row in episodes], org_id=ORG)


def test_canonical_corruption_and_partition_index_tampering_fail_closed(tmp_path):
    path = tmp_path / "memory.db"
    with SkillMemoryStore(path) as store:
        row = store.record_episode(evidence())
        connection = sqlite3.connect(path)
        with connection:
            connection.execute("UPDATE memory_records SET owner_user_id='attacker' WHERE record_id=?", (row.episode_id,))
        connection.close()
        with pytest.raises(SkillMemoryError, match="owner mismatch"):
            snapshot(store, user_id="attacker")


def test_private_support_join_is_bound_to_skill_hash(tmp_path):
    path = tmp_path / "memory.db"
    with SkillMemoryStore(path) as store:
        skill, _ = promoted(store)
        unrelated = store.record_episode(evidence(3))
        connection = sqlite3.connect(path)
        with connection:
            connection.execute("INSERT INTO skill_support VALUES(?,?)", (skill.skill_id, unrelated.episode_id))
        connection.close()
        with pytest.raises(SkillMemoryError, match="provenance mismatch"):
            snapshot(store)


def test_public_identifier_and_raw_source_are_also_scanned(tmp_path):
    with SkillMemoryStore(tmp_path / "memory.db") as store:
        rows = [store.record_episode(evidence(i)) for i in (1, 2)]
        with pytest.raises(PromotionRejected, match="private instance"):
            store.promote_skill(template(), [row.episode_id for row in rows], org_id=ORG, skill_id="private-user-1")
        source = template(steps=tuple(f"def source_excerpt_{i}(): pass" for i in range(10)))
        with pytest.raises(PromotionRejected, match="privacy/security"):
            store.promote_skill(source, [row.episode_id for row in rows], org_id=ORG)


@pytest.mark.parametrize("changes", [
    {"succeeded": 1}, {"actions": "not a sequence"},
    {"created_at": "2026-09-10T10:00:00"},
    {"verification_evidence_hash": "sha256:pretend"},
    {"parameter_bindings": (("x", "a"), ("x", "b"))},
])
def test_malformed_gate_a_evidence_cannot_enter_authority(changes):
    with pytest.raises(SkillMemoryError):
        evidence(**changes)


def test_unknown_schema_version_cannot_be_opened(tmp_path):
    path = tmp_path / "memory.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version=999")
    connection.close()
    with pytest.raises(SkillMemoryError, match="schema version"):
        SkillMemoryStore(path)
