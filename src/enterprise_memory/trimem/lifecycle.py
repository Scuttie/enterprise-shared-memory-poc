"""Source extraction -> DQN storage -> graph recall -> delayed outcome credit."""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from typing import Any, Callable, Mapping, Optional

from enterprise_memory.promotion import security_scan as promotion_security

from .accounting import canonical_bytes, sha256_bytes
from .agent_runtime import CodingTask, ExperienceExtraction
from .consolidation import (
    ConsolidationService,
    EpisodeRecord,
    PromotionReview,
    SemanticRecord,
    add_episode_support,
    candidate_from_episode,
    promote_to_organisation,
)
from .grader import GradeResult
from .policy import (
    ActionMask,
    DoubleDQNMemoryPolicy,
    MemoryAction,
    MemoryState,
)
from .ppr import DeterministicHashEmbedder, GraphNode
from .retrieval import (
    InMemoryMemoryGraphStore,
    MemoryGraphSnapshot,
    MemoryKind,
    MemoryRecord,
)
from .working_graph import ShortTermWorkingGraph


class LifecycleError(RuntimeError):
    pass


class DQNExperienceLifecycle:
    """A development/evaluation lifecycle with explicit learned-policy boundaries.

    The learned policy chooses only storage disposition.  Secret filtering,
    ownership, verification, and shared publication are deterministic gates.
    """

    def __init__(
        self,
        policy: DoubleDQNMemoryPolicy,
        consolidation: ConsolidationService,
        memory_index: InMemoryMemoryGraphStore,
        *,
        split: str,
        evaluation: bool,
        clock: Callable[[], str] = lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    ):
        if split not in {"development", "heldout", "credential_free_replay"}:
            raise ValueError("unknown data split")
        if evaluation and not policy.frozen:
            raise LifecycleError("evaluation requires a frozen DQN checkpoint")
        if not evaluation and split == "heldout":
            raise LifecycleError("held-out policy must be frozen evaluation")
        self.policy = policy
        self.consolidation = consolidation
        self.memory_index = memory_index
        self.split = split
        self.evaluation = evaluation
        self.clock = clock
        self.pending_by_memory_id: dict[str, dict[str, Any]] = {}
        self.semantic_candidates: dict[str, SemanticRecord] = {}
        self.credit_ledger: list[dict[str, Any]] = []

    def store_experience(self, task, graph, extraction, grade, injections):
        source_text = json.dumps(
            {"episode": extraction.episode, "semantic": extraction.semantic_candidate},
            ensure_ascii=False,
            sort_keys=True,
        )
        security_scan = promotion_security.scan(source_text)
        secret_free = not bool(security_scan["blocking"])
        state = self._state(task, graph, extraction, grade)
        if not secret_free:
            action_mask = ActionMask.only(MemoryAction.FORGET)
            deterministic_gate = "SECRET_FILTER"
        elif not grade.resolved or extraction.semantic_candidate is None:
            action_mask = ActionMask(
                forget=True,
                move_to_episodic=True,
                move_to_semantic_candidate=False,
            )
            deterministic_gate = "SEMANTIC_REQUIRES_VERIFIED_SUCCESS"
        else:
            action_mask = ActionMask()
            deterministic_gate = "ELIGIBLE"
        decision = self.policy.decide(state, action_mask, evaluation=self.evaluation)

        episode_id = "ep_" + sha256_bytes(
            canonical_bytes(
                {
                    "org": task.org_id,
                    "user": task.user_id,
                    "task": task.task_id,
                    "commit": task.commit,
                    "extract": extraction.response_hash,
                }
            )
        )[:24]
        verifier_hash = "sha256:" + sha256_bytes(canonical_bytes(grade.report))
        first_node = next(iter(graph.nodes.values()))
        episode = EpisodeRecord(
            episode_id=episode_id,
            user_id=task.user_id,
            repository=task.repository,
            commit=task.commit,
            subtask_id=first_node.node_id,
            action=str(extraction.episode["action"]),
            outcome="passed" if grade.resolved else "failed",
            verification_outcome="passed" if grade.resolved else "failed",
            source_verifier_hash=verifier_hash,
            event_time=self.clock(),
            payload={
                "summary": extraction.episode["summary"],
                "semantic_subtasks": [
                    {"id": node.node_id, "objective": node.objective, "operation": node.operation}
                    for node in graph.nodes.values()
                ],
                "patch_hash": extraction.patch_hash,
                "public_evidence_hash": extraction.public_evidence_hash,
                "extraction_response_hash": extraction.response_hash,
            },
        )
        archived_episode = None
        archived_semantic = None
        memory_id: Optional[str] = None
        if decision.action == MemoryAction.MOVE_TO_EPISODIC:
            archived_episode = self.consolidation.ingest_episode(episode)
            memory_id = episode.episode_id
            self._index_episode(task, episode, extraction)
        elif decision.action == MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE:
            if not grade.resolved or extraction.semantic_candidate is None:
                raise LifecycleError("action mask failed to stop unverified semantic storage")
            # Preserve the source episode as provenance even though only the
            # generalized candidate is exposed through the user semantic bank.
            archived_episode = self.consolidation.ingest_episode(episode)
            semantic_id = "sem_" + sha256_bytes(
                canonical_bytes(
                    {
                        "user": task.user_id,
                        "repository": task.repository,
                        "payload": extraction.semantic_candidate,
                    }
                )
            )[:24]
            semantic = candidate_from_episode(episode, semantic_id, extraction.semantic_candidate)
            archived_semantic = self.consolidation.retain_user_semantic(semantic)
            self.semantic_candidates[semantic_id] = semantic
            memory_id = semantic_id
            self._index_semantic(task, semantic, MemoryKind.USER_SEMANTIC)

        credit_id = None
        if not self.evaluation:
            credit_id = f"credit:{episode_id}"
            # credential-free replay is a development-mode implementation check;
            # it does not authorize paid calls or contaminate a held-out checkpoint.
            training_split = "development"
            self.policy.queue_delayed_credit(
                credit_id,
                state,
                decision.action,
                action_mask,
                split=training_split,
            )
            pending_key = memory_id or f"forgotten:{episode_id}"
            self.pending_by_memory_id[pending_key] = {
                "credit_id": credit_id,
                "state": state,
                "action": decision.action.value,
                "source_task_id": task.task_id,
                "context_cost": state.context_cost,
            }
        elif memory_id is not None:
            # Held-out evaluation keeps the policy/network/replay immutable, but
            # online streaming reuse still needs auditable success/negative-
            # transfer credit. This observation is consumed without training.
            self.pending_by_memory_id[memory_id] = {
                "credit_id": None,
                "state": state,
                "action": decision.action.value,
                "source_task_id": task.task_id,
                "context_cost": state.context_cost,
            }
        retained_records = (
            2
            if decision.action == MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE
            else int(decision.action == MemoryAction.MOVE_TO_EPISODIC)
        )
        archived_records = int(archived_episode is not None) + int(
            archived_semantic is not None
        )
        return {
            "storage_action": decision.action.value,
            "action_mask": list(decision.allowed),
            "q_values": list(decision.q_values),
            "epsilon": decision.epsilon,
            "evaluation": decision.evaluation,
            "deterministic_gate": deterministic_gate,
            "secret_free": secret_free,
            "security_scan_result": security_scan["result"],
            "episode_id": episode_id if decision.action != MemoryAction.FORGET else None,
            "memory_id": memory_id,
            "semantic_verified": bool(
                decision.action == MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE and grade.resolved
            ),
            "archived_episode_provenance": (
                archived_episode.provenance_hash if archived_episode is not None else None
            ),
            "archived_semantic_provenance": (
                archived_semantic.provenance_hash if archived_semantic is not None else None
            ),
            "delayed_credit_id": credit_id,
            "retained_records": retained_records,
            "archived_records": archived_records,
            "net_memory_growth": retained_records - archived_records,
        }

    def credit_outcome(self, task, grade, injections, *, outcome_metrics=None):
        injected_ids = {str(row["memory_id"]) for row in injections}
        credited = []
        for memory_id in sorted(injected_ids & set(self.pending_by_memory_id)):
            pending = self.pending_by_memory_id[memory_id]
            context_cost = float(pending["context_cost"])
            reward = (
                (1.0 if grade.resolved else -1.0)
                + (0.25 if grade.resolved else -0.5)
                - 0.05 * context_cost
            )
            losses: list[float] = []
            if not self.evaluation:
                prior: MemoryState = pending["state"]
                next_state = replace(
                    prior,
                    reuse_frequency=prior.reuse_frequency + 1.0,
                    past_gain_loss=prior.past_gain_loss + reward,
                )
                losses = self.policy.credit_delayed_reward(
                    pending["credit_id"],
                    reward,
                    next_state,
                    done=True,
                    split="development",
                    train_updates=1,
                )
            row = {
                "memory_id": memory_id,
                "source_task_id": pending["source_task_id"],
                "target_task_id": task.task_id,
                "target_resolved": grade.resolved,
                "reward": reward,
                "negative_transfer": not grade.resolved,
                "losses": losses,
            }
            self.credit_ledger.append(row)
            credited.append(row)
            del self.pending_by_memory_id[memory_id]
        return {
            "credited": len(credited),
            "transitions": credited,
            "pending_credit_count": self.policy.pending_credit_count if not self.evaluation else 0,
            "replay_size": self.policy.replay_size,
            "training_steps": self.policy.training_steps,
            "evaluation_mutation": False if self.evaluation else None,
        }

    def resolve_unreused(self, *, next_task_succeeded: bool) -> list[dict[str, Any]]:
        """Close pending FORGET/non-retrieved actions before checkpoint freeze."""
        out = []
        for memory_id in sorted(list(self.pending_by_memory_id)):
            pending = self.pending_by_memory_id.pop(memory_id)
            prior: MemoryState = pending["state"]
            # A small retention cost and no reuse gain.  This closes delayed
            # transitions without pretending they caused the downstream result.
            reward = -0.05 * float(pending["context_cost"])
            losses = [] if self.evaluation else self.policy.credit_delayed_reward(
                pending["credit_id"], reward, prior, done=True,
                split="development", train_updates=1,
            )
            row = {
                "memory_id": memory_id,
                "source_task_id": pending["source_task_id"],
                "reward": reward,
                "losses": losses,
                "useful_reuse": False,
                "evaluation_mutation": False if self.evaluation else None,
            }
            self.credit_ledger.append(row)
            out.append(row)
        return out

    def add_support_and_review(
        self,
        semantic_id: str,
        supporting_episode: EpisodeRecord,
        review: PromotionReview,
        *,
        task: CodingTask,
    ) -> SemanticRecord:
        """Explicit deterministic cross-user publication path, outside the DQN."""
        current = self.semantic_candidates[semantic_id]
        strengthened = add_episode_support(current, supporting_episode)
        security_scan = promotion_security.scan(
            json.dumps(strengthened.payload, ensure_ascii=False, sort_keys=True)
        )
        if security_scan["blocking"]:
            raise LifecycleError(
                "semantic candidate failed deterministic publication security scan: %s"
                % security_scan["result"]
            )
        promoted = promote_to_organisation(strengthened, review)
        self.consolidation.organisation_semantic.add(promoted)
        self._index_semantic(task, promoted, MemoryKind.ORG_SEMANTIC)
        self.semantic_candidates[semantic_id] = strengthened
        return promoted

    def _state(self, task, graph, extraction, grade):
        schema = self.policy.config.feature_schema
        candidate_text = json.dumps(
            {"episode": extraction.episode, "semantic": extraction.semantic_candidate},
            ensure_ascii=False,
            sort_keys=True,
        )
        subtasks = " ".join(node.objective + " " + node.operation for node in graph.nodes.values())
        total_records = sum(len(snapshot.records) for snapshot in self.memory_index._snapshots.values())
        graph_stats = [
            min(1.0, len(graph.nodes) / 10.0),
            min(1.0, total_records / 100.0),
            1.0 if graph.complete else 0.0,
        ]
        while len(graph_stats) < schema.graph_statistics_dim:
            graph_stats.append(0.0)
        return MemoryState(
            candidate_embedding=_embed(candidate_text, schema.candidate_embedding_dim),
            task_embedding=_embed(task.instruction, schema.task_embedding_dim),
            subtask_embedding=_embed(subtasks, schema.subtask_embedding_dim),
            verification_outcome=1.0 if grade.resolved else -1.0,
            novelty=1.0,
            redundancy=0.0,
            recency=1.0,
            reuse_frequency=0.0,
            past_gain_loss=0.0,
            version_validity=1.0,
            memory_occupancy=min(1.0, total_records / 100.0),
            graph_statistics=tuple(graph_stats[: schema.graph_statistics_dim]),
            context_cost=min(1.0, len(candidate_text.encode("utf-8")) / 12_000.0),
        )

    def _index_episode(self, task, episode, extraction):
        text = " ".join(
            [str(extraction.episode["summary"]), str(extraction.episode["action"]), task.repository]
        )
        view = json.dumps(
            {
                "kind": "episodic",
                "source_repository": task.repository,
                "source_commit": task.commit,
                "summary": extraction.episode["summary"],
                "action": extraction.episode["action"],
                "outcome": extraction.episode["outcome"],
                "evidence_hash": episode.provenance_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        record = MemoryRecord(
            memory_id=episode.episode_id,
            kind=MemoryKind.EPISODIC,
            retrieval_text=text,
            execution_view=view,
            org_id=task.org_id,
            owner_user_id=task.user_id,
            repository=task.repository,
            version=task.commit,
            source_outcome="passed" if episode.verified_success else "failed",
            verified=episode.verified_success,
            reviewed=False,
            completeness=0.65,
            coverage=("operation", "verification"),
            metadata={"provenance_hash": episode.provenance_hash, "event_time": episode.event_time},
        )
        self._upsert_index(record)

    def _index_semantic(self, task, semantic, kind):
        payload = dict(semantic.payload)
        text = " ".join(str(payload.get(key, "")) for key in (
            "preconditions", "operation", "invariant", "non_applicability", "verification"
        ))
        provenance_view = (
            {
                "supporting_evidence_count": len(semantic.supporting_episode_ids),
                "independent_user_count": len(semantic.supporting_user_ids),
                "reviewer_id": semantic.reviewer_id,
            }
            if kind == MemoryKind.ORG_SEMANTIC
            else {"supporting_episode_ids": list(semantic.supporting_episode_ids)}
        )
        view = json.dumps(
            {
                "kind": "organisation_semantic" if kind == MemoryKind.ORG_SEMANTIC else "user_semantic",
                **payload,
                **provenance_view,
                "provenance_hash": semantic.provenance_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        record = MemoryRecord(
            memory_id=semantic.semantic_id,
            kind=kind,
            retrieval_text=text,
            execution_view=view,
            org_id=task.org_id,
            owner_user_id=semantic.owner_user_id,
            repository=task.repository,
            version=task.commit,
            verified=semantic.verified,
            reviewed=kind != MemoryKind.ORG_SEMANTIC or bool(semantic.reviewer_id),
            source_outcome="passed",
            completeness=1.0,
            coverage=("operation", "precondition", "invariant", "non_applicability", "verification"),
            metadata={"provenance_hash": semantic.provenance_hash, "strength": semantic.strength},
        )
        self._upsert_index(record)

    def _upsert_index(self, record: MemoryRecord) -> None:
        try:
            existing = self.memory_index.snapshot(
                record.kind,
                user_id=record.owner_user_id or "org-reader",
                org_id=record.org_id,
                repository=record.repository or "",
            )
        except Exception:
            existing = MemoryGraphSnapshot(record.kind, {})
        records = dict(existing.records)
        records[record.memory_id] = record
        nodes = dict(existing.nodes)
        nodes[record.memory_id] = GraphNode(record.memory_id, record.retrieval_text, record.metadata)
        adjacency = {key: dict(value) if isinstance(value, Mapping) else tuple(value)
                     for key, value in existing.adjacency.items()}
        # Related records in one bank receive deterministic undirected repository
        # edges.  PPR can still abstain through the seed and confidence gates.
        for other_id in sorted(records):
            if other_id == record.memory_id:
                continue
            adjacency.setdefault(record.memory_id, {})
            if not isinstance(adjacency[record.memory_id], dict):
                adjacency[record.memory_id] = {x: 1.0 for x in adjacency[record.memory_id]}
            adjacency[record.memory_id][other_id] = 1.0
            adjacency.setdefault(other_id, {})
            if not isinstance(adjacency[other_id], dict):
                adjacency[other_id] = {x: 1.0 for x in adjacency[other_id]}
            adjacency[other_id][record.memory_id] = 1.0
        graph_hash = sha256_bytes(
            canonical_bytes(
                {
                    "kind": record.kind.value,
                    "records": {key: records[key].metadata for key in sorted(records)},
                    "adjacency": adjacency,
                }
            )
        )
        self.memory_index.put(
            MemoryGraphSnapshot(record.kind, records, nodes=nodes, adjacency=adjacency, graph_hash=graph_hash)
        )


def _embed(text: str, dimensions: int) -> tuple[float, ...]:
    return DeterministicHashEmbedder(dimensions).embed(text)
