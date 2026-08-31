"""Deterministic TRIMEM consolidation and forgetting.

This module intentionally has no dependency on the learned memory policy.  A
DQN may propose ``MOVE_TO_SEMANTIC_CANDIDATE``; verification, retention,
tenant isolation and organisation publication are deterministic operations
implemented here or by the surrounding store/ACL layer.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional


class ConsolidationError(RuntimeError):
    pass


class UnverifiedSemanticError(ConsolidationError):
    pass


class PromotionError(ConsolidationError):
    pass


def _canonical_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("payload must be JSON-canonicalizable") from exc


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EpisodeRecord:
    episode_id: str
    user_id: str
    repository: str
    commit: str
    subtask_id: str
    action: str
    outcome: str
    verification_outcome: str
    source_verifier_hash: str
    event_time: str
    payload: Mapping[str, Any]
    provenance_hash: str = ""

    def __post_init__(self) -> None:
        for name in ("episode_id", "user_id", "repository", "subtask_id", "event_time"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        canonical = _canonical_payload(self.payload)
        object.__setattr__(self, "payload", canonical)
        calculated = _hash(
            {
                "episode_id": self.episode_id,
                "user_id": self.user_id,
                "repository": self.repository,
                "commit": self.commit,
                "subtask_id": self.subtask_id,
                "action": self.action,
                "outcome": self.outcome,
                "verification_outcome": self.verification_outcome,
                "source_verifier_hash": self.source_verifier_hash,
                "event_time": self.event_time,
                "payload": canonical,
            }
        )
        if self.provenance_hash and self.provenance_hash != calculated:
            raise ValueError("episode provenance hash mismatch")
        object.__setattr__(self, "provenance_hash", calculated)

    @property
    def verified_success(self) -> bool:
        return (
            self.outcome.lower() in {"success", "resolved", "passed"}
            and self.verification_outcome.lower() in {"passed", "resolved", "success"}
            and bool(self.source_verifier_hash.strip())
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EpisodeRecord":
        """Duck-typed adapter for the eventual canonical graph/store schema."""

        return cls(**{name: value.get(name, "") for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class ArchivedEpisode:
    episode_id: str
    user_id: str
    repository: str
    event_time: str
    provenance_hash: str
    archive_sequence: int
    reason: str = "episodic_fifo_capacity"


class PerUserEpisodicFIFO:
    """Independent FIFO per user; archived entries retain provenance, not payload."""

    def __init__(self, capacity_per_user: int):
        if capacity_per_user <= 0:
            raise ValueError("capacity_per_user must be positive")
        self.capacity_per_user = capacity_per_user
        self._active: dict[str, list[EpisodeRecord]] = {}
        self._archived: dict[str, list[ArchivedEpisode]] = {}
        self._ids: set[str] = set()
        self._archive_sequence = 0

    def add(self, episode: EpisodeRecord | Mapping[str, Any]) -> Optional[ArchivedEpisode]:
        record = episode if isinstance(episode, EpisodeRecord) else EpisodeRecord.from_mapping(episode)
        if record.episode_id in self._ids:
            raise ConsolidationError(f"duplicate episode_id: {record.episode_id}")
        self._ids.add(record.episode_id)
        queue = self._active.setdefault(record.user_id, [])
        queue.append(record)
        if len(queue) <= self.capacity_per_user:
            return None
        evicted = queue.pop(0)
        self._archive_sequence += 1
        archived = ArchivedEpisode(
            episode_id=evicted.episode_id,
            user_id=evicted.user_id,
            repository=evicted.repository,
            event_time=evicted.event_time,
            provenance_hash=evicted.provenance_hash,
            archive_sequence=self._archive_sequence,
        )
        self._archived.setdefault(record.user_id, []).append(archived)
        return archived

    def active(self, user_id: str) -> tuple[EpisodeRecord, ...]:
        return tuple(self._active.get(user_id, ()))

    def archived(self, user_id: str) -> tuple[ArchivedEpisode, ...]:
        return tuple(self._archived.get(user_id, ()))


@dataclass(frozen=True)
class SemanticMetrics:
    support: float = 0.0
    successful_reuse: float = 0.0
    independent_user_evidence: float = 0.0
    recent_verification: float = 0.0
    negative_transfer: float = 0.0
    contradiction: float = 0.0
    version_staleness: float = 0.0

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")


def semantic_strength(metrics: SemanticMetrics) -> float:
    """The preregistered, coefficient-free semantic strength formula."""

    return (
        metrics.support
        + metrics.successful_reuse
        + metrics.independent_user_evidence
        + metrics.recent_verification
        - metrics.negative_transfer
        - metrics.contradiction
        - metrics.version_staleness
    )


@dataclass(frozen=True)
class SemanticRecord:
    semantic_id: str
    owner_user_id: Optional[str]
    scope: str
    payload: Mapping[str, Any]
    supporting_episode_ids: tuple[str, ...] = ()
    verified_episode_ids: tuple[str, ...] = ()
    supporting_user_ids: tuple[str, ...] = ()
    trusted_document_hash: Optional[str] = None
    verified: bool = False
    verification_basis: str = "unverified"
    metrics: SemanticMetrics = field(default_factory=SemanticMetrics)
    provenance_hash: str = ""
    reviewer_id: Optional[str] = None
    review_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.semantic_id:
            raise ValueError("semantic_id is required")
        if self.scope not in {"user", "organisation"}:
            raise ValueError("scope must be user or organisation")
        if self.scope == "user" and not self.owner_user_id:
            raise ValueError("user semantic record requires owner_user_id")
        if self.scope == "organisation" and self.owner_user_id is not None:
            raise ValueError("organisation semantic record cannot have owner_user_id")
        canonical = _canonical_payload(self.payload)
        object.__setattr__(self, "payload", canonical)
        for name in ("supporting_episode_ids", "verified_episode_ids", "supporting_user_ids"):
            object.__setattr__(self, name, tuple(sorted(set(getattr(self, name)))))
        if not set(self.verified_episode_ids) <= set(self.supporting_episode_ids):
            raise ValueError("verified episodes must also be supporting episodes")
        episode_basis = self.verification_basis == "verified_episode" and bool(self.verified_episode_ids)
        document_basis = self.verification_basis == "trusted_document" and bool(self.trusted_document_hash)
        if self.verified != bool(episode_basis or document_basis):
            raise ValueError("verified semantic requires verified-episode or trusted-document evidence")
        calculated = _semantic_provenance(self, canonical)
        if self.provenance_hash and self.provenance_hash != calculated:
            raise ValueError("semantic provenance hash mismatch")
        object.__setattr__(self, "provenance_hash", calculated)

    @property
    def strength(self) -> float:
        return semantic_strength(self.metrics)


def _semantic_provenance(record: SemanticRecord, payload: Mapping[str, Any]) -> str:
    return _hash(
        {
            "semantic_id": record.semantic_id,
            "owner_user_id": record.owner_user_id,
            "scope": record.scope,
            "payload": payload,
            "supporting_episode_ids": sorted(set(record.supporting_episode_ids)),
            "verified_episode_ids": sorted(set(record.verified_episode_ids)),
            "supporting_user_ids": sorted(set(record.supporting_user_ids)),
            "trusted_document_hash": record.trusted_document_hash,
            "verified": record.verified,
            "verification_basis": record.verification_basis,
            "metrics": record.metrics.__dict__,
            "reviewer_id": record.reviewer_id,
            "review_reason": record.review_reason,
        }
    )


def candidate_from_episode(
    episode: EpisodeRecord,
    semantic_id: str,
    payload: Mapping[str, Any],
) -> SemanticRecord:
    """One episode may create a candidate; failure never becomes verified semantic."""

    verified_ids = (episode.episode_id,) if episode.verified_success else ()
    metrics = SemanticMetrics(
        support=float(len(verified_ids)),
        independent_user_evidence=0.0,
        recent_verification=1.0 if verified_ids else 0.0,
    )
    return SemanticRecord(
        semantic_id=semantic_id,
        owner_user_id=episode.user_id,
        scope="user",
        payload=payload,
        supporting_episode_ids=(episode.episode_id,),
        verified_episode_ids=verified_ids,
        supporting_user_ids=(episode.user_id,) if verified_ids else (),
        verified=bool(verified_ids),
        verification_basis="verified_episode" if verified_ids else "unverified",
        metrics=metrics,
    )


def candidate_from_trusted_document(
    *,
    semantic_id: str,
    owner_user_id: str,
    payload: Mapping[str, Any],
    trusted_document_hash: str,
) -> SemanticRecord:
    digest = trusted_document_hash.removeprefix("sha256:")
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
        raise ValueError("trusted_document_hash must be a sha256 digest")
    return SemanticRecord(
        semantic_id=semantic_id,
        owner_user_id=owner_user_id,
        scope="user",
        payload=payload,
        trusted_document_hash=trusted_document_hash,
        verified=True,
        verification_basis="trusted_document",
        metrics=SemanticMetrics(support=1.0, recent_verification=1.0),
    )


def add_episode_support(record: SemanticRecord, episode: EpisodeRecord) -> SemanticRecord:
    all_ids = set(record.supporting_episode_ids)
    all_ids.add(episode.episode_id)
    verified_ids = set(record.verified_episode_ids)
    if episode.verified_success:
        verified_ids.add(episode.episode_id)
    users = set(record.supporting_user_ids)
    if episode.verified_success:
        users.add(episode.user_id)
    verified = bool(verified_ids) or record.verification_basis == "trusted_document"
    metrics = replace(
        record.metrics,
        support=float(len(verified_ids)) + (1.0 if record.trusted_document_hash else 0.0),
        independent_user_evidence=float(max(0, len(users) - 1)),
        recent_verification=max(record.metrics.recent_verification, 1.0 if episode.verified_success else 0.0),
    )
    return replace(
        record,
        supporting_episode_ids=tuple(all_ids),
        verified_episode_ids=tuple(verified_ids),
        supporting_user_ids=tuple(users),
        verified=verified,
        verification_basis=(record.verification_basis if record.trusted_document_hash else
                            "verified_episode" if verified_ids else "unverified"),
        metrics=metrics,
        provenance_hash="",
    )


@dataclass(frozen=True)
class ArchivedSemantic:
    semantic_id: str
    scope: str
    owner_user_id: Optional[str]
    provenance_hash: str
    strength: float
    archive_sequence: int
    reason: str = "lowest_semantic_strength"


class SemanticStrengthBank:
    """Capacity-bounded semantic bank with deterministic lowest-strength archive."""

    def __init__(self, capacity: int, *, scope: str, owner_user_id: Optional[str] = None):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if scope not in {"user", "organisation"}:
            raise ValueError("invalid bank scope")
        if scope == "user" and not owner_user_id:
            raise ValueError("user bank requires owner_user_id")
        if scope == "organisation" and owner_user_id is not None:
            raise ValueError("organisation bank cannot have an owner")
        self.capacity = capacity
        self.scope = scope
        self.owner_user_id = owner_user_id
        self._records: dict[str, SemanticRecord] = {}
        self._archived: list[ArchivedSemantic] = []
        self._archive_sequence = 0

    def add(self, record: SemanticRecord) -> Optional[ArchivedSemantic]:
        if not record.verified:
            raise UnverifiedSemanticError("unverified/source-failure candidate cannot enter semantic bank")
        if record.scope != self.scope or record.owner_user_id != self.owner_user_id:
            raise ConsolidationError("semantic record does not match bank scope/owner")
        if record.semantic_id in self._records:
            raise ConsolidationError(f"duplicate semantic_id: {record.semantic_id}")
        self._records[record.semantic_id] = record
        if len(self._records) <= self.capacity:
            return None
        lowest = min(self._records.values(), key=lambda r: (r.strength, r.semantic_id))
        del self._records[lowest.semantic_id]
        self._archive_sequence += 1
        archived = ArchivedSemantic(
            semantic_id=lowest.semantic_id,
            scope=lowest.scope,
            owner_user_id=lowest.owner_user_id,
            provenance_hash=lowest.provenance_hash,
            strength=lowest.strength,
            archive_sequence=self._archive_sequence,
        )
        self._archived.append(archived)
        return archived

    def update(self, record: SemanticRecord) -> None:
        if record.semantic_id not in self._records:
            raise ConsolidationError("cannot update absent semantic record")
        if not record.verified or record.scope != self.scope or record.owner_user_id != self.owner_user_id:
            raise ConsolidationError("updated record violates bank invariants")
        self._records[record.semantic_id] = record

    def records(self) -> tuple[SemanticRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def archived(self) -> tuple[ArchivedSemantic, ...]:
        return tuple(self._archived)


@dataclass(frozen=True)
class PromotionReview:
    reviewer_id: str
    approved: bool
    reason: str
    trusted_document_approved: bool = False

    def __post_init__(self) -> None:
        if not self.reviewer_id or not self.reason:
            raise ValueError("reviewer_id and reason are required")


def promote_to_organisation(record: SemanticRecord, review: PromotionReview) -> SemanticRecord:
    """Deterministic shared-publication gate; never delegated to a learned policy."""

    if record.scope != "user":
        raise PromotionError("only a user semantic record can be promoted")
    if not record.verified:
        raise PromotionError("unverified semantic candidate cannot be promoted")
    if not review.approved:
        raise PromotionError("organisation promotion requires explicit review approval")
    multiple_verified_episodes = len(set(record.verified_episode_ids)) >= 2
    trusted = bool(record.trusted_document_hash) and review.trusted_document_approved
    if not (multiple_verified_episodes or trusted):
        raise PromotionError("promotion requires multiple verified episodes or reviewed trusted-document evidence")
    return SemanticRecord(
        semantic_id=record.semantic_id,
        owner_user_id=None,
        scope="organisation",
        payload=record.payload,
        supporting_episode_ids=record.supporting_episode_ids,
        verified_episode_ids=record.verified_episode_ids,
        supporting_user_ids=record.supporting_user_ids,
        trusted_document_hash=record.trusted_document_hash,
        verified=True,
        verification_basis=record.verification_basis,
        metrics=record.metrics,
        reviewer_id=review.reviewer_id,
        review_reason=review.reason,
    )


class ConsolidationService:
    """In-memory orchestration surface; persistent stores can duck-type these operations."""

    def __init__(self, episodic_capacity: int, user_semantic_capacity: int, organisation_capacity: int):
        self.episodes = PerUserEpisodicFIFO(episodic_capacity)
        self.user_semantic_capacity = user_semantic_capacity
        self.user_semantic: dict[str, SemanticStrengthBank] = {}
        self.organisation_semantic = SemanticStrengthBank(organisation_capacity, scope="organisation")

    def ingest_episode(self, episode: EpisodeRecord | Mapping[str, Any]) -> Optional[ArchivedEpisode]:
        return self.episodes.add(episode)

    def retain_user_semantic(self, record: SemanticRecord) -> Optional[ArchivedSemantic]:
        if record.scope != "user" or not record.owner_user_id:
            raise ConsolidationError("expected a user semantic record")
        bank = self.user_semantic.setdefault(
            record.owner_user_id,
            SemanticStrengthBank(self.user_semantic_capacity, scope="user", owner_user_id=record.owner_user_id),
        )
        return bank.add(record)

    def promote_shared(self, record: SemanticRecord, review: PromotionReview) -> Optional[ArchivedSemantic]:
        promoted = promote_to_organisation(record, review)
        return self.organisation_semantic.add(promoted)
