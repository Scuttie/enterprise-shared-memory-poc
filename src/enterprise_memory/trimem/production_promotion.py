"""Reviewed production promotion into the organisation semantic graph."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from enterprise_memory.promotion import security_scan as promotion_security

from .accounting import canonical_bytes, sha256_bytes
from .postgres_store import CapacityLimits, LifecycleAppendBundle, PostgresTriMemStore, PromotionEvidence
from .schema import (
    AccessContext,
    EdgeType,
    GraphEdge,
    GraphKind,
    GraphNode,
    LifecycleState,
    NodeType,
    OrganisationSemanticGraph,
    ReviewAuthority,
    ReviewProvenance,
    SemanticStrength,
    SemanticStrengthRecord,
    SemanticSupport,
    TemporalMetadata,
    canonical_hash,
)


_ID_NAMESPACE = uuid.UUID("9091cf72-bca0-4fa9-8f52-5d670c3650bd")
_SEMANTIC_FIELDS = (
    "applicability_scope",
    "preconditions",
    "operation",
    "invariant",
    "non_applicability",
    "verification",
)


class PromotionError(RuntimeError):
    pass


def _digest(value: object) -> str:
    return "sha256:" + sha256_bytes(canonical_bytes(value))


def _sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        raise PromotionError("%s must be a canonical sha256 digest" % name)
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise PromotionError("%s must be a canonical sha256 digest" % name) from exc
    return value


def promotion_review_evidence_hash(evidence: Sequence[PromotionEvidence]) -> str:
    rows = [
        {
            "evidence_hash": item.evidence_hash,
            "contributor_hash": item.contributor_hash,
            "attestation_hash": item.attestation_hash,
        }
        for item in sorted(
            evidence,
            key=lambda item: (item.evidence_hash, item.contributor_hash, item.attestation_hash),
        )
    ]
    return canonical_hash({"schema": "trimem/promotion-review-evidence/1.0", "rows": rows})


class PostgresReviewedPromotionService:
    """Only explicit review authority can publish a shared semantic record.

    The service accepts no learned-policy argument.  It reloads the private
    source canonically, verifies only the org-visible content-free evidence
    ledger, and persists the reviewed shared graph before Qdrant projection.
    """

    def __init__(
        self,
        canonical_store: PostgresTriMemStore,
        persistence: object,
        *,
        namespace: str,
        organisation_capacity: int = 1000,
        clock: Optional[object] = None,
    ) -> None:
        if not isinstance(canonical_store, PostgresTriMemStore):
            raise TypeError("production promotion requires PostgresTriMemStore")
        if getattr(canonical_store, "namespace", None) != namespace:
            raise ValueError("promotion store namespace mismatch")
        if not callable(getattr(persistence, "persist_bundle", None)) or not callable(
            getattr(getattr(persistence, "bridge", None), "call", None)
        ):
            raise TypeError("promotion persistence requires the session async bridge")
        if type(organisation_capacity) is not int or organisation_capacity <= 0:
            raise ValueError("organisation_capacity must be positive")
        self.store = canonical_store
        self.persistence = persistence
        self.bridge = persistence.bridge
        self.namespace = namespace
        self.capacity = organisation_capacity
        self.clock = clock or (
            lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )

    def _uuid(self, label: str) -> str:
        return str(uuid.uuid5(_ID_NAMESPACE, self.namespace + "|" + label))

    def promote(
        self,
        ctx: AccessContext,
        *,
        source_semantic_node_id: str,
        review: ReviewProvenance,
        evidence_hashes: Sequence[str] = (),
        trusted_document_hash: Optional[str] = None,
    ) -> Mapping[str, Any]:
        if not isinstance(ctx, AccessContext) or not isinstance(review, ReviewProvenance):
            raise TypeError("promotion requires access context and ReviewProvenance")
        if not review.verify_hash():
            raise PromotionError("review provenance hash is invalid")
        source = self.bridge.call(self.store.get_node(ctx, source_semantic_node_id))
        if (
            source.namespace != self.namespace
            or source.org_id != ctx.org_id
            or source.owner_user_id != ctx.user_id
            or source.graph_kind != GraphKind.USER_SEMANTIC
            or source.node_type != NodeType.SEMANTIC_RULE
            or source.lifecycle_state != LifecycleState.ACTIVE
            or not source.verify_hash()
        ):
            raise PromotionError("source semantic record is unavailable")
        payload = source.canonical_payload
        if (
            payload.get("verified") is not True
            or payload.get("source_outcome") != "passed"
            or payload.get("servable") is not True
        ):
            raise PromotionError("source semantic record is not verified and servable")

        evidence: tuple[PromotionEvidence, ...] = ()
        if review.authority == ReviewAuthority.HUMAN_REVIEW:
            if trusted_document_hash is not None:
                raise PromotionError("human evidence and trusted document modes cannot be mixed")
            evidence = tuple(
                self.bridge.call(
                    self.store.verify_promotion_evidence(ctx, tuple(evidence_hashes))
                )
            )
            if (
                len({item.evidence_hash for item in evidence}) < 2
                or len({item.contributor_hash for item in evidence}) < 2
                or any(
                    not item.verified
                    or item.source_kind != "VERIFIED_EPISODE"
                    or item.source_outcome != "passed"
                    for item in evidence
                )
            ):
                raise PromotionError(
                    "human promotion requires two independently contributed verified episodes"
                )
            if review.evidence_hash != promotion_review_evidence_hash(evidence):
                raise PromotionError("review evidence hash does not bind canonical attestations")
        elif review.authority == ReviewAuthority.TRUSTED_DOCUMENT:
            if evidence_hashes:
                raise PromotionError("trusted-document promotion cannot accept episode evidence")
            trusted = _sha256(trusted_document_hash, "trusted_document_hash")
            if review.evidence_hash != trusted:
                raise PromotionError("review does not bind the trusted document hash")
        else:  # defensive against a future enum extension granting DQN authority
            raise PromotionError("unsupported organisation promotion authority")

        try:
            execution = json.loads(str(payload["execution_view"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PromotionError("source semantic execution view is invalid") from exc
        if not isinstance(execution, Mapping) or any(
            not isinstance(execution.get(name), str) or not execution[name].strip()
            for name in _SEMANTIC_FIELDS
        ):
            raise PromotionError("source semantic applicability schema is incomplete")
        shared_view = {"kind": "organisation_semantic"}
        shared_view.update({name: str(execution[name]) for name in _SEMANTIC_FIELDS})
        security_scan = promotion_security.scan(
            json.dumps(shared_view, ensure_ascii=False, sort_keys=True)
        )
        if security_scan["blocking"]:
            raise PromotionError(
                "source semantic record failed deterministic security scan: %s"
                % security_scan["result"]
            )

        now = self.clock()
        temporal = TemporalMetadata(
            ingested_at=now,
            event_time=now,
            source_available_at=now,
            last_verified_at=review.reviewed_at,
        )
        promotion_key = "%s|%s" % (source.content_hash, review.content_hash)
        graph = OrganisationSemanticGraph(
            graph_id=self._uuid("org-graph|" + promotion_key),
            org_id=ctx.org_id,
            namespace=self.namespace,
            repository_id=source.repository_id,
            temporal=temporal,
            review_provenance=review,
        )
        root = GraphNode(
            node_id=self._uuid("org-semantic|" + promotion_key),
            graph_id=graph.graph_id,
            org_id=ctx.org_id,
            namespace=self.namespace,
            graph_kind=graph.kind,
            owner_user_id=None,
            repository_id=source.repository_id,
            node_type=NodeType.SEMANTIC_RULE,
            canonical_payload={
                "retrieval_text": " ".join(shared_view[name] for name in _SEMANTIC_FIELDS),
                "execution_view": json.dumps(
                    shared_view, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
                "version": str(payload.get("version", "UNKNOWN")),
                "version_valid": bool(payload.get("version_valid")),
                "stale": False,
                "servable": True,
                "verified": True,
                "source_outcome": "passed",
                "quality": float(payload.get("quality", 1.0)),
                "completeness": float(payload.get("completeness", 1.0)),
                "coverage": list(payload.get("coverage", ())),
                "provenance": {
                    "source_user_semantic_hash": source.content_hash,
                    "review_hash": review.content_hash,
                    "evidence_attestation_hashes": sorted(
                        item.attestation_hash for item in evidence
                    ),
                    "trusted_document_hash": trusted_document_hash,
                },
            },
            temporal=temporal,
            review_provenance=review,
        )
        source_anchor = self._anchor(
            graph,
            NodeType.SEMANTIC_RULE,
            "source|" + source.content_hash,
            {"source_user_semantic_hash": source.content_hash},
            temporal,
            review,
        )
        nodes = [root, source_anchor]
        edges = [
            self._edge(graph, source_anchor, root, EdgeType.PROMOTED_TO, temporal, review),
            self._edge(graph, root, source_anchor, EdgeType.DERIVED_FROM, temporal, review),
        ]
        supports = []
        support_rows = [
            (item.evidence_hash, item.contributor_hash, item.attestation_hash)
            for item in evidence
        ]
        if trusted_document_hash is not None:
            support_rows.append((
                trusted_document_hash,
                _digest({"trusted_document": trusted_document_hash}),
                review.content_hash,
            ))
        for ordinal, (evidence_hash, contributor_hash, attestation_hash) in enumerate(
            sorted(support_rows)
        ):
            anchor = self._anchor(
                graph,
                NodeType.OUTCOME,
                "evidence|%s|%s" % (evidence_hash, contributor_hash),
                {
                    "evidence_hash": evidence_hash,
                    "contributor_hash": contributor_hash,
                    "attestation_hash": attestation_hash,
                    "verified": True,
                },
                temporal,
                review,
            )
            nodes.append(anchor)
            edges.append(
                self._edge(graph, root, anchor, EdgeType.SUPPORTED_BY, temporal, review)
            )
            supports.append(SemanticSupport(
                support_id=self._uuid("org-support|%s|%04d" % (promotion_key, ordinal)),
                semantic_graph_id=graph.graph_id,
                semantic_node_id=root.node_id,
                org_id=ctx.org_id,
                namespace=self.namespace,
                graph_kind=GraphKind.ORGANISATION_SEMANTIC,
                owner_user_id=None,
                source_episode_id=None,
                source_evidence_hash=evidence_hash,
                contributor_hash=contributor_hash,
                temporal=temporal,
                review_provenance=review,
            ))

        receipt = self.persistence.persist_bundle(
            ctx,
            LifecycleAppendBundle(
                graphs=(graph,),
                nodes=tuple(nodes),
                edges=tuple(edges),
                supports=tuple(supports),
                strengths=(SemanticStrengthRecord(
                    strength_id=self._uuid("org-strength|" + root.node_id),
                    graph_id=graph.graph_id,
                    semantic_node_id=root.node_id,
                    org_id=ctx.org_id,
                    namespace=self.namespace,
                    graph_kind=GraphKind.ORGANISATION_SEMANTIC,
                    owner_user_id=None,
                    strength=SemanticStrength(
                        support=float(len(support_rows)),
                        independent_user_evidence=float(
                            len({item.contributor_hash for item in evidence})
                        ),
                        recent_verification=1.0,
                    ),
                    updated_at=now,
                ),),
                index_node_ids=(root.node_id,),
                capacity_limits=CapacityLimits(
                    episodic_per_user=100,
                    user_semantic_per_user=100,
                    organisation_semantic=self.capacity,
                ),
                capacity_archived_at=now,
            ),
        )
        return {
            "graph_id": graph.graph_id,
            "node_id": root.node_id,
            "content_hash": root.content_hash,
            "review_hash": review.content_hash,
            "receipt_digest": receipt["receipt_digest"],
            "authority": review.authority.value,
            "dqn_authority": False,
        }

    def _anchor(self, graph, node_type, key, payload, temporal, review):
        return GraphNode(
            node_id=self._uuid("org-anchor|%s|%s" % (graph.graph_id, key)),
            graph_id=graph.graph_id,
            org_id=graph.org_id,
            namespace=self.namespace,
            graph_kind=graph.kind,
            owner_user_id=None,
            repository_id=graph.repository_id,
            node_type=node_type,
            canonical_payload=payload,
            temporal=temporal,
            review_provenance=review,
        )

    def _edge(self, graph, source, target, edge_type, temporal, review):
        return GraphEdge(
            edge_id=self._uuid(
                "org-edge|%s|%s|%s|%s"
                % (graph.graph_id, edge_type.value, source.node_id, target.node_id)
            ),
            graph_id=graph.graph_id,
            org_id=graph.org_id,
            namespace=self.namespace,
            graph_kind=graph.kind,
            owner_user_id=None,
            edge_type=edge_type,
            source_node_id=source.node_id,
            target_node_id=target.node_id,
            metadata={"weight": 1.0, "review_hash": review.content_hash},
            temporal=temporal,
            review_provenance=review,
        )


__all__ = [
    "PostgresReviewedPromotionService",
    "PromotionError",
    "promotion_review_evidence_hash",
]
