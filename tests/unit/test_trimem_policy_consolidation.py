import inspect
from types import SimpleNamespace

import pytest

from enterprise_memory.trimem.consolidation import (
    ConsolidationService,
    EpisodeRecord,
    PerUserEpisodicFIFO,
    PromotionError,
    PromotionReview,
    SemanticMetrics,
    SemanticRecord,
    SemanticStrengthBank,
    UnverifiedSemanticError,
    add_episode_support,
    candidate_from_episode,
    candidate_from_trusted_document,
    promote_to_organisation,
    semantic_strength,
)
from enterprise_memory.trimem.policy import (
    ACTION_ORDER,
    ActionMask,
    ActionMaskError,
    CheckpointError,
    DoubleDQNConfig,
    DoubleDQNMemoryPolicy,
    FeatureSchema,
    FrozenCheckpoint,
    FrozenPolicyError,
    MemoryAction,
    MemoryState,
    TrainingScopeError,
)
from enterprise_memory.trimem.grader import GradeResult
from enterprise_memory.trimem.lifecycle import DQNExperienceLifecycle, LifecycleError
from enterprise_memory.trimem.retrieval import InMemoryMemoryGraphStore


SCHEMA = FeatureSchema(2, 2, 2, 2)


def state(seed=0.0, **over):
    values = dict(
        candidate_embedding=(0.1 + seed, 0.2),
        task_embedding=(0.3, 0.4),
        subtask_embedding=(0.5, 0.6),
        verification_outcome=1.0,
        novelty=0.8,
        redundancy=0.1,
        recency=0.9,
        reuse_frequency=0.2,
        past_gain_loss=0.5,
        version_validity=1.0,
        memory_occupancy=0.25,
        graph_statistics=(0.2, 0.7),
        context_cost=0.1,
    )
    values.update(over)
    return MemoryState(**values)


def config(**over):
    values = dict(
        feature_schema=SCHEMA,
        hidden_dim=5,
        replay_capacity=8,
        batch_size=2,
        min_replay_size=2,
        target_sync_interval=1,
        epsilon_start=0.0,
        epsilon_end=0.0,
        epsilon_decay_steps=2,
        seed=17,
    )
    values.update(over)
    return DoubleDQNConfig(**values)


def episode(eid, user="alice", *, success=True):
    return EpisodeRecord(
        episode_id=eid,
        user_id=user,
        repository="acme/widgets",
        commit="abc123",
        subtask_id="propagate-new-argument",
        action="update all call sites",
        outcome="success" if success else "failed",
        verification_outcome="passed" if success else "failed",
        source_verifier_hash="sha256:grader" if success else "sha256:grader",
        event_time="2026-01-01T00:00:00Z",
        payload={"patch_ref": f"patch:{eid}", "result": "pass" if success else "fail"},
    )


def test_feature_vector_contains_every_frozen_feature():
    vector = state().vector(SCHEMA)
    assert len(vector) == SCHEMA.input_dim == 17
    assert vector[-1] == 0.1
    with pytest.raises(ValueError):
        state(candidate_embedding=(1.0,)).vector(SCHEMA)


def test_action_surface_and_mask_are_narrow_and_enforced():
    assert {a.value for a in ACTION_ORDER} == {
        "FORGET",
        "MOVE_TO_EPISODIC",
        "MOVE_TO_SEMANTIC_CANDIDATE",
    }
    assert not any("SHARED" in a.value or "ACL" in a.value or "TENANT" in a.value for a in ACTION_ORDER)
    policy = DoubleDQNMemoryPolicy(config())
    decision = policy.decide(state(), ActionMask.only(MemoryAction.MOVE_TO_EPISODIC))
    assert decision.action == MemoryAction.MOVE_TO_EPISODIC
    with pytest.raises(ActionMaskError):
        ActionMask(False, False, False).as_tuple()


def test_double_dqn_is_deterministic_and_syncs_target():
    left, right = DoubleDQNMemoryPolicy(config()), DoubleDQNMemoryPolicy(config())
    for policy in (left, right):
        policy.remember(
            state(), MemoryAction.MOVE_TO_EPISODIC, 0.5, state(0.1), done=False,
            split="development", train_updates=0,
        )
        losses = policy.remember(
            state(0.2), MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE, 1.0, state(0.3), done=True,
            split="development", train_updates=1,
        )
        assert len(losses) == 1 and losses[0] >= 0
    assert left.q_values(state()) == right.q_values(state())
    assert left._online.state() == left._target.state()  # sync interval is one


def test_delayed_reward_and_development_only_guard():
    policy = DoubleDQNMemoryPolicy(config())
    policy.queue_delayed_credit(
        "task-arm-1", state(), MemoryAction.MOVE_TO_EPISODIC,
        ActionMask.only(MemoryAction.MOVE_TO_EPISODIC), split="development",
    )
    assert policy.pending_credit_count == 1 and policy.replay_size == 0
    policy.credit_delayed_reward(
        "task-arm-1", 1.0, state(0.1), done=True, split="development", train_updates=0,
    )
    assert policy.pending_credit_count == 0 and policy.replay_size == 1
    with pytest.raises(TrainingScopeError):
        policy.remember(
            state(), MemoryAction.FORGET, 0.0, state(), done=True,
            split="heldout", train_updates=0,
        )


def test_mutable_policy_runtime_checkpoint_restores_rng_replay_pending_and_networks():
    policy = DoubleDQNMemoryPolicy(config(epsilon_start=1.0, epsilon_end=1.0))
    policy.remember(
        state(), MemoryAction.MOVE_TO_EPISODIC, 0.5, state(0.1), done=True,
        split="development", train_updates=0,
    )
    policy.queue_delayed_credit(
        "pending", state(0.2), MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE,
        split="development",
    )
    checkpoint = policy.runtime_state()
    expected = policy.decide(state(0.3), evaluation=False)
    policy.credit_delayed_reward(
        "pending", 1.0, state(0.4), done=True, split="development", train_updates=1,
    )
    policy.restore_runtime_state(checkpoint)
    assert policy.pending_credit_count == 1
    assert policy.replay_size == 1
    assert policy.training_steps == 0
    assert policy.decide(state(0.3), evaluation=False) == expected
    tampered = {"payload": dict(checkpoint["payload"]), "digest": checkpoint["digest"]}
    tampered["payload"]["selection_steps"] = 999
    with pytest.raises(CheckpointError, match="digest mismatch"):
        policy.restore_runtime_state(tampered)


def test_freeze_digest_restore_and_evaluation_are_immutable():
    policy = DoubleDQNMemoryPolicy(config(epsilon_start=1.0, epsilon_end=1.0))
    frozen = policy.freeze_checkpoint()
    assert frozen.digest.startswith("sha256:")
    before = frozen.payload
    first = policy.decide(state(), evaluation=True)
    second = policy.decide(state(), evaluation=True)
    after = policy._frozen_payload()
    assert first == second and first.epsilon == 0.0 and before == after
    q_before = policy.q_values(state())
    frozen.payload["online_network"]["b2"][0] += 100  # checkpoint value cannot alias the live network
    assert policy.q_values(state()) == q_before
    with pytest.raises(FrozenPolicyError):
        policy.train(1, split="development")
    clean = policy._frozen_payload()
    restored = DoubleDQNMemoryPolicy.from_frozen_checkpoint(
        policy.freeze_checkpoint()
    )
    assert restored.decide(state(), evaluation=True) == first
    assert clean == policy._frozen_payload()
    bad = FrozenCheckpoint(frozen.payload, "sha256:" + "0" * 64)
    with pytest.raises(CheckpointError):
        DoubleDQNMemoryPolicy.from_frozen_checkpoint(bad)


def test_freeze_rejects_uncredited_delayed_reward():
    policy = DoubleDQNMemoryPolicy(config())
    policy.queue_delayed_credit("pending", state(), MemoryAction.FORGET, split="development")
    with pytest.raises(CheckpointError):
        policy.freeze_checkpoint()


def test_heldout_reuse_credit_is_observed_without_policy_or_replay_mutation():
    policy = DoubleDQNMemoryPolicy(config())
    policy.freeze_checkpoint()
    lifecycle = DQNExperienceLifecycle(
        policy,
        ConsolidationService(2, 2, 2),
        InMemoryMemoryGraphStore(),
        split="heldout",
        evaluation=True,
    )
    lifecycle.pending_by_memory_id["sem-source"] = {
        "credit_id": None,
        "state": state(),
        "action": MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE.value,
        "source_task_id": "source",
        "context_cost": 0.1,
    }
    before = policy._frozen_payload()
    grade = GradeResult(
        task_id="target", resolved=False, exit_code=1, stdout="", stderr="failed",
        report={"task_id": "target", "resolved": False}, grader_id="replay",
        container_digest="replay@sha256:" + "a" * 64, official=False, wall_time_ms=1,
    )
    result = lifecycle.credit_outcome(
        SimpleNamespace(task_id="target"), grade, ({"memory_id": "sem-source"},)
    )
    assert result["credited"] == 1
    assert result["transitions"][0]["negative_transfer"] is True
    assert result["transitions"][0]["losses"] == []
    assert result["evaluation_mutation"] is False
    assert policy._frozen_payload() == before
    assert policy.replay_size == 0 and policy.training_steps == 0
    assert lifecycle.pending_by_memory_id == {}


def test_terminal_transition_allows_an_empty_next_action_mask():
    policy = DoubleDQNMemoryPolicy(config())
    policy.remember(
        state(), MemoryAction.FORGET, 0.0, state(), done=True,
        next_action_mask=ActionMask(False, False, False), split="development", train_updates=0,
    )
    assert policy.replay_size == 1


def test_episodic_fifo_is_per_user_and_archive_keeps_only_provenance():
    fifo = PerUserEpisodicFIFO(2)
    one, two, three = episode("e1"), episode("e2"), episode("e3")
    fifo.add(one)
    fifo.add(episode("b1", "bob"))
    fifo.add(two)
    archived = fifo.add(three)
    assert [e.episode_id for e in fifo.active("alice")] == ["e2", "e3"]
    assert [e.episode_id for e in fifo.active("bob")] == ["b1"]
    assert archived.episode_id == "e1" and archived.provenance_hash == one.provenance_hash
    assert not hasattr(archived, "payload")


def test_source_failure_can_be_candidate_but_not_verified_semantic():
    failed = candidate_from_episode(episode("bad", success=False), "rule-bad", {"operation": "x"})
    assert not failed.verified and failed.verified_episode_ids == () and failed.supporting_user_ids == ()
    bank = SemanticStrengthBank(2, scope="user", owner_user_id="alice")
    with pytest.raises(UnverifiedSemanticError):
        bank.add(failed)
    good = candidate_from_episode(episode("good"), "rule-good", {"operation": "safe"})
    assert good.verified and good.verification_basis == "verified_episode"
    assert bank.add(good) is None


def test_verified_flag_cannot_be_forged_and_failed_support_adds_no_strength():
    with pytest.raises(ValueError):
        SemanticRecord("forged", "alice", "user", {"rule": "x"}, verified=True)
    base = candidate_from_episode(episode("good-base"), "base", {"rule": "x"})
    updated = add_episode_support(base, episode("failed-bob", user="bob", success=False))
    assert updated.metrics.support == base.metrics.support
    assert updated.metrics.independent_user_evidence == 0
    assert updated.verified_episode_ids == base.verified_episode_ids


def test_semantic_strength_and_lowest_eviction_are_deterministic():
    assert semantic_strength(SemanticMetrics(3, 2, 1, 1, 0.5, 0.25, 0.25)) == 6.0
    bank = SemanticStrengthBank(2, scope="user", owner_user_id="alice")

    def record(sid, support):
        return SemanticRecord(
            sid, "alice", "user", {"rule": sid}, supporting_episode_ids=(sid,),
            verified_episode_ids=(sid,), supporting_user_ids=("alice",), verified=True,
            verification_basis="verified_episode", metrics=SemanticMetrics(support=support),
        )

    bank.add(record("strong", 3))
    bank.add(record("weak", 1))
    archived = bank.add(record("middle", 2))
    assert archived.semantic_id == "weak" and archived.strength == 1
    assert [r.semantic_id for r in bank.records()] == ["middle", "strong"]


def test_shared_promotion_is_reviewed_and_evidence_gated_without_dqn():
    one = candidate_from_episode(episode("e1"), "rule", {"operation": "update-callers"})
    review = PromotionReview("reviewer", True, "evidence checked")
    with pytest.raises(PromotionError):
        promote_to_organisation(one, review)
    two = add_episode_support(one, episode("e2", user="bob"))
    shared = promote_to_organisation(two, review)
    assert shared.scope == "organisation" and shared.owner_user_id is None
    assert shared.reviewer_id == "reviewer" and len(shared.verified_episode_ids) == 2
    assert "policy" not in inspect.signature(promote_to_organisation).parameters


def test_in_memory_reviewed_publication_rechecks_product_security_scanner():
    policy = DoubleDQNMemoryPolicy(config())
    lifecycle = DQNExperienceLifecycle(
        policy,
        ConsolidationService(2, 2, 2),
        InMemoryMemoryGraphStore(),
        split="credential_free_replay",
        evaluation=False,
    )
    blocked = candidate_from_episode(
        episode("security-source"),
        "security-rule",
        {"operation": "e" + "yJabcdefghijk.abcdefghijk.abcdefghijk"},
    )
    lifecycle.semantic_candidates[blocked.semantic_id] = blocked
    with pytest.raises(LifecycleError, match="publication security scan"):
        lifecycle.add_support_and_review(
            blocked.semantic_id,
            episode("security-support", user="bob"),
            PromotionReview("reviewer", True, "reviewed"),
            task=SimpleNamespace(
                org_id="org-a", user_id="alice", repository="acme/widgets", commit="abc123"
            ),
        )
    assert lifecycle.consolidation.organisation_semantic.records() == ()


def test_trusted_document_and_consolidation_service_paths():
    trusted = candidate_from_trusted_document(
        semantic_id="trusted-rule", owner_user_id="alice", payload={"invariant": "keep ABI"},
        trusted_document_hash="sha256:" + "a" * 64,
    )
    with pytest.raises(PromotionError):
        promote_to_organisation(trusted, PromotionReview("r", True, "read", False))
    review = PromotionReview("r", True, "trusted document reviewed", True)
    shared = promote_to_organisation(trusted, review)
    assert shared.scope == "organisation"

    service = ConsolidationService(episodic_capacity=1, user_semantic_capacity=2, organisation_capacity=2)
    service.ingest_episode(episode("s1"))
    service.retain_user_semantic(trusted)
    assert service.promote_shared(trusted, review) is None
