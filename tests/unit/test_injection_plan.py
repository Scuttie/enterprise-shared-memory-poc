"""P5.1 §2/§3 unit tests for the injection planner — deterministic ranking, <=2 cap, injected-flag ==
view-actually-in-payload, injected-view hash + position, and real-owner cross-user leakage (incl. the
defence-in-depth hard failure). Pure logic; no DB/Qdrant/network."""
import hashlib
import pytest
from enterprise_memory.service.injection import plan_injection, CrossUserInjectionError


class FakeHit:
    def __init__(self, cid, vid, chash, score, owner=None, canonical=None):
        self.canonical_id = cid
        self.canonical_version_id = vid
        self.content_hash = chash
        self.score = score
        self.owner_user_id = owner
        self.canonical = canonical if canonical is not None else {}


def _shared(vid, score, text="rule"):
    # a legacy-style canonical (string) so the codec projects it verbatim as the shared view
    return FakeHit("c-%s" % vid, vid, "h-%s" % vid, score, canonical="shared note %s" % text)


def _private(vid, owner, score, note="use a retry multiplier of three under load"):
    return FakeHit("p-%s" % vid, vid, "ph-%s" % vid, score, owner=owner,
                   canonical={"private_note": note})


def test_shared_only_injected_with_hash_and_position():
    plan = plan_injection([], [_shared("s1", 0.9)], requester_id="alice", repo_id="r1")
    assert len(plan.memory_views) == 1
    inj = [c for c in plan.candidates if c.injected]
    assert len(inj) == 1
    c = inj[0]
    assert c.injected_position == 0
    assert c.injected_view_hash == hashlib.sha256(plan.memory_views[0].encode()).hexdigest()
    assert plan.cross_user_private_injection_count == 0


def test_at_most_two_injected_across_scopes():
    priv = [_private("p1", "alice", 0.95)]
    shared = [_shared("s1", 0.9), _shared("s2", 0.8), _shared("s3", 0.7)]
    plan = plan_injection(priv, shared, requester_id="alice", repo_id="r1")
    assert len(plan.memory_views) == 2                       # global cap enforced
    assert sum(1 for c in plan.candidates if c.injected) == 2
    # every non-injected accepted candidate is explicitly injected=False
    assert any((not c.injected) and c.accepted for c in plan.candidates)


def test_injected_flag_matches_payload_byte_for_byte():
    priv = [_private("p1", "alice", 0.99)]
    shared = [_shared("s1", 0.5)]
    plan = plan_injection(priv, shared, requester_id="alice", repo_id="r1")
    injected_views = [c.view_text for c in plan.candidates if c.injected]
    assert injected_views == plan.memory_views              # the flag is the payload, not a claim
    for c in plan.candidates:
        if not c.injected:
            assert c.view_text not in plan.memory_views or c.view_text is None or \
                   plan.memory_views.count(c.view_text) == injected_views.count(c.view_text)


def test_private_own_owner_is_zero_leakage():
    plan = plan_injection([_private("p1", "alice", 0.9)], [], requester_id="alice", repo_id="r1")
    assert plan.cross_user_private_injection_count == 0
    assert any(c.scope == "private" and c.injected for c in plan.candidates)


def test_cross_user_private_view_refused_at_compile():
    # primary guarantee: a private hit owned by bob is refused for alice at view compilation, so it is
    # accepted=False, never injected, and contributes zero to the leakage count.
    plan = plan_injection([_private("p1", "bob", 0.99)], [], requester_id="alice", repo_id="r1")
    c = [x for x in plan.candidates if x.scope == "private"][0]
    assert not c.injected and not c.accepted
    assert "private_view_refused:NOT_OWNER" in c.rejection_reason
    assert plan.cross_user_private_injection_count == 0
    assert plan.memory_views == []


def test_cross_user_guard_defence_in_depth(monkeypatch):
    # deeper guard: if the view compiler ever produced a view for a non-owner (a bug), the planner must still
    # refuse to enter a plan with a cross-user private view in the payload.
    import enterprise_memory.service.injection as inj
    monkeypatch.setattr(inj, "_compile_private", lambda hit, requester_id, repo_id: "LEAKED bob note")
    with pytest.raises(CrossUserInjectionError):
        inj.plan_injection([_private("p1", "bob", 0.99)], [], requester_id="alice", repo_id="r1")


def test_deterministic_order():
    priv = [_private("p1", "alice", 0.8)]
    shared = [_shared("s1", 0.8)]
    a = plan_injection(priv, shared, requester_id="alice", repo_id="r1")
    b = plan_injection(priv, shared, requester_id="alice", repo_id="r1")
    assert a.memory_views == b.memory_views


def test_refused_private_view_not_injected():
    empty = FakeHit("p-e", "pe", "he", 0.99, owner="alice", canonical={"private_note": ""})
    plan = plan_injection([empty], [_shared("s1", 0.1)], requester_id="alice", repo_id="r1")
    refused = [c for c in plan.candidates if c.scope == "private"][0]
    assert not refused.injected and not refused.accepted
    assert refused.rejection_reason and "private_view_refused" in refused.rejection_reason


def test_rejected_audit_recorded_never_injected():
    audit = [{"scope": "private", "canonical_id": "p-bob", "canonical_version_id": "vbob",
              "content_hash": "hbob", "score": 0.99, "index_owner": "bob", "canonical_owner": "bob",
              "rejection_reason": "not_owner"}]
    plan = plan_injection([], [_shared("s1", 0.5)], requester_id="alice", repo_id="r1",
                          rejected_audit=audit)
    rej = [c for c in plan.candidates if c.canonical_version_id == "vbob"][0]
    assert (not rej.injected) and (not rej.accepted)
    assert rej.rejection_reason == "not_owner" and rej.canonical_owner_id == "bob"
    assert plan.cross_user_private_injection_count == 0
