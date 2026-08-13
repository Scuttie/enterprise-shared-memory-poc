"""Deterministic memory-injection planner (P5.1 §2, §3).

The worker must NOT record a candidate as `injected` unless the exact compiled view is actually placed in the
backend payload. This module makes that guarantee auditable:

  validated hits (already gated + canonically reloaded by validated_search)
    -> deterministic safe view compilation (private via PrivateExecutionViewCompiler; shared via the codec's
       target-free retrieval projection)
    -> deterministic joint ranking across private + shared
    -> select at most `max_injected` TOTAL
    -> memory_views = the exact strings handed to the backend, in order
    -> injected=True ONLY for the selected candidates, with the injected-view hash + prompt position
    -> cross_user_private_injection_count = number of ACTUALLY-injected private candidates whose
       authoritative canonical owner != the authenticated user (must be 0)

`injected=True` therefore means "this exact view is byte-for-byte present in the backend payload". A candidate
not placed in the payload is `injected=False`. Ownership is always the authoritative PostgreSQL owner carried
on the validated hit — never the authenticated user, never inferred from the query context.
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field
from typing import List, Optional

from ..contracts import codec
from .private_view import compile_private_view, PrivateViewRefused

MAX_INJECTED = 2


def _sha(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


class CrossUserInjectionError(Exception):
    """Raised if a private candidate owned by another user would reach the backend payload (defence in depth
    behind validated_search's owner gate). The job must not enter SUCCEEDED."""


@dataclass
class PlannedCandidate:
    scope: str                              # 'private' | 'shared'
    canonical_id: Optional[str]
    canonical_version_id: Optional[str]
    content_hash: Optional[str]
    score: float
    index_owner_id: Optional[str]           # claimed owner in the index payload (private)
    canonical_owner_id: Optional[str]       # authoritative owner from PostgreSQL (private)
    accepted: bool                          # passed validated_search gates
    rejection_reason: Optional[str] = None
    view_text: Optional[str] = None         # compiled safe view (None if refused / rejected)
    view_refused_reason: Optional[str] = None
    injected: bool = False
    injected_position: Optional[int] = None
    injected_view_hash: Optional[str] = None


@dataclass
class InjectionPlan:
    memory_views: List[str] = field(default_factory=list)   # EXACT ordered strings sent to the backend
    candidates: List[PlannedCandidate] = field(default_factory=list)
    cross_user_private_injection_count: int = 0


def _compile_private(hit, requester_id: str, repo_id) -> str:
    """Compile a bounded, secret-scrubbed private execution view. Ownership/scope are re-checked here as a
    second boundary; the raw private trace text is never used verbatim."""
    canonical = hit.canonical if isinstance(hit.canonical, dict) else {}
    body = (canonical.get("private_note") or canonical.get("note") or canonical.get("body")
            or canonical.get("technique") or "")
    item = {"id": hit.canonical_version_id, "owner": hit.owner_user_id, "hash": hit.content_hash,
            "repo_id": None, "body": body}
    view, _meta = compile_private_view(item, requester_id=requester_id, repo_id=repo_id)
    return view


def _compile_shared(hit) -> str:
    view_text, _scope = codec.retrieval_text_and_path_scope(hit.canonical)
    return view_text


def _rank_key(c: PlannedCandidate):
    # deterministic joint ranking: higher score first; private before shared on ties; then a stable hash key.
    scope_rank = 0 if c.scope == "private" else 1
    return (-float(c.score or 0.0), scope_rank, str(c.content_hash or ""), str(c.canonical_version_id or ""))


def plan_injection(private_hits, shared_hits, *, requester_id: str, repo_id,
                   rejected_audit=None, max_injected: int = MAX_INJECTED) -> InjectionPlan:
    """Build the injection plan. `private_hits`/`shared_hits` are validated_search ValidatedHit objects
    (already owner/scope/permission/path/hash gated). `rejected_audit` is validated_search's per-candidate
    audit rows for REJECTED candidates (so they are persisted as accepted=False with real owner info)."""
    cands: List[PlannedCandidate] = []

    for h in private_hits:
        c = PlannedCandidate(scope="private", canonical_id=h.canonical_id,
                             canonical_version_id=h.canonical_version_id, content_hash=h.content_hash,
                             score=getattr(h, "score", 0.0), index_owner_id=h.owner_user_id,
                             canonical_owner_id=h.owner_user_id, accepted=True)
        try:
            c.view_text = _compile_private(h, requester_id, repo_id)
        except PrivateViewRefused as e:
            c.accepted = False
            c.rejection_reason = "private_view_refused:%s" % e.reason
            c.view_refused_reason = e.reason
        cands.append(c)

    for h in shared_hits:
        c = PlannedCandidate(scope="shared", canonical_id=h.canonical_id,
                             canonical_version_id=h.canonical_version_id, content_hash=h.content_hash,
                             score=getattr(h, "score", 0.0), index_owner_id=None,
                             canonical_owner_id=None, accepted=True)
        c.view_text = _compile_shared(h)
        cands.append(c)

    # rejected candidates (from validated_search audit) are recorded but never eligible for injection
    for a in (rejected_audit or []):
        cands.append(PlannedCandidate(
            scope=a.get("scope"), canonical_id=a.get("canonical_id"),
            canonical_version_id=a.get("canonical_version_id"), content_hash=a.get("content_hash"),
            score=a.get("score", 0.0), index_owner_id=a.get("index_owner"),
            canonical_owner_id=a.get("canonical_owner"), accepted=False,
            rejection_reason=a.get("rejection_reason")))

    # deterministic selection of at most `max_injected` eligible candidates (accepted + view compiled)
    eligible = [c for c in cands if c.accepted and c.view_text is not None]
    eligible.sort(key=_rank_key)
    selected = eligible[:max(0, max_injected)]

    plan = InjectionPlan()
    for pos, c in enumerate(selected):
        c.injected = True
        c.injected_position = pos
        c.injected_view_hash = _sha(c.view_text)
        plan.memory_views.append(c.view_text)

    # authoritative cross-user leakage: computed from the real canonical owner of ACTUALLY-injected private
    # candidates. Structurally 0 (validated_search gates PRIVATE to the owner), but enforced defensively.
    cross = 0
    for c in selected:
        if c.scope == "private" and str(c.canonical_owner_id) != str(requester_id):
            cross += 1
    if cross:
        raise CrossUserInjectionError(
            "cross-user private candidate reached backend payload: injected owners include a non-requester")
    plan.cross_user_private_injection_count = cross
    plan.candidates = cands
    return plan
