"""Production DQN lifecycle backed only by canonical PostgreSQL and Qdrant.

The learned policy chooses a private storage disposition.  This adapter builds
canonical UUID records, atomically commits the lifecycle bundle through
``CanonicalLifecyclePersistence``, and lets that persistence layer index only
the PostgreSQL-reloaded node.  It never grants shared publication authority.
"""
from __future__ import annotations

import json
import math
import uuid
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Protocol

from enterprise_memory.promotion import security_scan as promotion_security

from .accounting import canonical_bytes, sha256_bytes
from .lifecycle import LifecycleError
from .policy import (
    ActionMask,
    DoubleDQNConfig,
    DoubleDQNMemoryPolicy,
    FrozenCheckpoint,
    MemoryAction,
    MemoryState,
)
from .postgres_store import (
    CapacityLimits,
    LifecycleAppendBundle,
    SemanticStrengthIncrement,
)
from .schema import (
    AccessContext,
    EdgeType,
    GraphEdge,
    GraphKind,
    GraphNode,
    NodeType,
    PolicyAction,
    PolicyActor,
    PolicyTransition,
    SemanticStrength,
    SemanticStrengthRecord,
    SemanticSupport,
    ShortTermWorkingGraph as CanonicalWorkingGraph,
    TemporalMetadata,
    UserEpisodicGraph,
    UserSemanticGraph,
    canonical_hash,
)


_ID_NAMESPACE = uuid.UUID("b8d4b900-069f-45bc-a351-0da4674d4398")
_SCALAR_FEATURES = (
    "verification_outcome",
    "novelty",
    "redundancy",
    "recency",
    "reuse_frequency",
    "past_gain_loss",
    "version_validity",
    "memory_occupancy",
    "context_cost",
)
_DQN_CONFIG_FIELDS = (
    "hidden_dim",
    "replay_capacity",
    "batch_size",
    "min_replay_size",
    "gamma",
    "learning_rate",
    "target_sync_interval",
    "epsilon_start",
    "epsilon_end",
    "epsilon_decay_steps",
    "seed",
)


class ProductionIdentityResolver(Protocol):
    def __call__(self, task: object) -> Mapping[str, str]: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value: object) -> str:
    return "sha256:" + sha256_bytes(canonical_bytes(value))


def _canonical_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError("%s is required" % name)
    candidate = value if value.startswith("sha256:") else "sha256:" + value
    if len(candidate) != 71:
        raise LifecycleError("%s must be a canonical sha256 digest" % name)
    try:
        int(candidate[7:], 16)
    except ValueError as exc:
        raise LifecycleError("%s must be a canonical sha256 digest" % name) from exc
    return candidate


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LifecycleError("%s must be a mapping" % name)
    return dict(value)


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LifecycleError("%s must be numeric" % name)
    result = float(value)
    if not math.isfinite(result):
        raise LifecycleError("%s must be finite" % name)
    return result


def _parse_policy_manifest(
    value: Mapping[str, Any], expected_hash: str
) -> tuple[DoubleDQNConfig, dict[str, Any]]:
    """Validate every runtime-bearing part of the committed M2 contract."""

    manifest = _mapping(value, "policy_manifest")
    observed_hash = _digest(manifest)
    if observed_hash != _canonical_digest(expected_hash, "expected_policy_manifest_hash"):
        raise LifecycleError("M2 policy manifest hash mismatch")
    if manifest.get("schema") != "trimem/m2-policy/1.0":
        raise LifecycleError("unsupported M2 policy manifest schema")

    dqn = _mapping(manifest.get("double_dqn"), "double_dqn")
    if tuple(dqn.get("action_order", ())) != tuple(action.value for action in MemoryAction):
        raise LifecycleError("M2 action order drift")
    if dqn.get("network") != "pure-python one-hidden-layer ReLU online and target networks":
        raise LifecycleError("M2 network implementation drift")
    feature = _mapping(dqn.get("feature_schema"), "double_dqn.feature_schema")
    if tuple(feature.pop("scalar_features", ())) != _SCALAR_FEATURES:
        raise LifecycleError("M2 scalar feature order drift")
    config_value = {name: dqn.get(name) for name in _DQN_CONFIG_FIELDS}
    config_value["feature_schema"] = feature
    try:
        config = DoubleDQNConfig.from_dict(config_value)
    except (KeyError, TypeError, ValueError) as exc:
        raise LifecycleError("invalid M2 DoubleDQN config") from exc

    encoder = _mapping(dqn.get("feature_encoder"), "double_dqn.feature_encoder")
    if encoder.get("projection") != "NONE":
        raise LifecycleError("M2 feature projection drift")
    dimensions = {
        config.feature_schema.candidate_embedding_dim,
        config.feature_schema.task_embedding_dim,
        config.feature_schema.subtask_embedding_dim,
    }
    if len(dimensions) != 1:
        raise LifecycleError("projection NONE requires equal encoder feature dimensions")
    encoder["dimensions"] = dimensions.pop()

    reward = _mapping(manifest.get("reward"), "reward")
    expected_reward_fields = {
        "successful_outcome",
        "failure_outcome",
        "successful_reuse",
        "negative_transfer",
        "context_cost_coefficient",
        "subtask_completion_coefficient",
        "token_cost_coefficient",
        "latency_cost_coefficient",
        "storage_cost_coefficient",
        "stale_conflict_coefficient",
        "token_normalization",
        "latency_normalization_ms",
        "storage_normalization_bytes",
    }
    if set(reward) != expected_reward_fields:
        raise LifecycleError("M2 reward field drift")
    reward = {name: _number(raw, "reward.%s" % name) for name, raw in reward.items()}
    for name in (
        "context_cost_coefficient",
        "token_cost_coefficient",
        "latency_cost_coefficient",
        "storage_cost_coefficient",
        "stale_conflict_coefficient",
    ):
        if reward[name] > 0.0:
            raise LifecycleError("M2 cost coefficients cannot reward cost")
    if reward["subtask_completion_coefficient"] < 0.0:
        raise LifecycleError("M2 subtask completion coefficient cannot be negative")
    for name in (
        "token_normalization", "latency_normalization_ms", "storage_normalization_bytes"
    ):
        if reward[name] <= 0.0:
            raise LifecycleError("M2 reward normalizers must be positive")

    topology = _mapping(manifest.get("graph_topology"), "graph_topology")
    if set(topology) != {"compiler", "dependency_orientation", "edge_weights"}:
        raise LifecycleError("M2 graph topology field drift")
    if topology.get("compiler") != "trimem-canonical-topology-v1" or topology.get(
        "dependency_orientation"
    ) != "subtask_to_prerequisite":
        raise LifecycleError("M2 graph topology compiler drift")
    edge_weights = _mapping(topology.get("edge_weights"), "graph_topology.edge_weights")
    required_edges = {
        "DERIVED_FROM", "VALID_FOR", "PRODUCED", "OBSERVED", "DECOMPOSES_TO",
        "APPLIED", "TOUCHES", "CALLS", "VERIFIED_BY", "DEPENDS_ON",
    }
    if set(edge_weights) != required_edges:
        raise LifecycleError("M2 graph topology edge-weight drift")
    topology["edge_weights"] = {
        name: _number(raw, "graph_topology.edge_weights.%s" % name)
        for name, raw in edge_weights.items()
    }
    if any(value <= 0.0 for value in topology["edge_weights"].values()):
        raise LifecycleError("M2 graph topology weights must be positive")

    state_features = _mapping(manifest.get("state_features"), "state_features")
    if set(state_features) != {
        "algorithm", "max_history_records", "recency_half_life_seconds",
        "reuse_frequency_scale", "version_scope",
    }:
        raise LifecycleError("M2 state feature contract drift")
    if state_features.get("algorithm") != "trimem-canonical-state-features-v1" or state_features.get(
        "version_scope"
    ) != "repository-exact-or-generalized-null":
        raise LifecycleError("M2 state feature algorithm drift")
    for name in ("max_history_records", "recency_half_life_seconds", "reuse_frequency_scale"):
        if type(state_features.get(name)) is not int or state_features[name] <= 0:
            raise LifecycleError("M2 state feature limits must be positive integers")

    retrieval = _mapping(manifest.get("retrieval"), "retrieval")
    expected_retrieval = {
        "context_budget_bytes",
        "embedding_dimensions",
        "embedding_weight",
        "episode_complete_threshold",
        "lexical_weight",
        "max_episodic_per_active_node",
        "max_semantic_per_active_node",
        "max_task_injections",
        "min_confidence",
        "min_margin",
        "ppr_damping",
        "ppr_iterations",
        "retrieval_point",
        "self_memory_exclusion",
    }
    if set(retrieval) != expected_retrieval:
        raise LifecycleError("M2 retrieval contract drift")
    if retrieval["embedding_dimensions"] != encoder["dimensions"]:
        raise LifecycleError("M2 retrieval/encoder dimension mismatch")
    if retrieval["retrieval_point"] != "exactly when a semantic subtask becomes active":
        raise LifecycleError("M2 retrieval point drift")
    if retrieval["self_memory_exclusion"] != (
        "source_task_id equal to current target task_id is excluded before ranking"
    ):
        raise LifecycleError("M2 self-memory exclusion drift")

    consolidation = _mapping(manifest.get("consolidation"), "consolidation")
    capacities = _mapping(consolidation.get("capacities"), "consolidation.capacities")
    if set(capacities) != {
        "episodic_per_user", "user_semantic_per_user", "organisation_semantic"
    } or any(type(item) is not int or item <= 0 for item in capacities.values()):
        raise LifecycleError("M2 consolidation capacity drift")

    freeze = _mapping(manifest.get("development_freeze_rule"), "development_freeze_rule")
    required = _mapping(freeze.get("required_before_export"), "required_before_export")
    cursor = required.get("development_resume_cursor")
    if type(cursor) is not int or cursor <= 0 or required.get("pending_credit_count") != 0:
        raise LifecycleError("M2 development freeze boundary drift")
    if required.get("policy_frozen") is not True:
        raise LifecycleError("M2 development checkpoint must be frozen")

    return config, {
        "manifest_hash": observed_hash,
        "encoder": encoder,
        "reward": reward,
        "graph_topology": topology,
        "state_features": state_features,
        "retrieval": retrieval,
        "capacities": capacities,
        "development_resume_cursor": cursor,
    }


class PostgresDQNExperienceLifecycle:
    """Durable ExperienceLifecycle for the M2 production arm."""

    def __init__(
        self,
        policy: DoubleDQNMemoryPolicy,
        persistence: object,
        *,
        namespace: str,
        split: str,
        evaluation: bool,
        identity_resolver: ProductionIdentityResolver,
        feature_encoder: object,
        policy_manifest_hash: str,
        encoder_lock: Mapping[str, Any],
        reward_config: Mapping[str, float],
        graph_topology_config: Mapping[str, Any],
        state_feature_config: Mapping[str, Any],
        retrieval_config: Mapping[str, Any],
        capacity_config: Mapping[str, int],
        development_resume_cursor: int,
        clock: Callable[[], str] = _now,
    ) -> None:
        if split not in {"development", "heldout", "credential_free_replay"}:
            raise ValueError("unknown data split")
        if evaluation and not policy.frozen:
            raise LifecycleError("evaluation requires a frozen DQN checkpoint")
        if split == "heldout" and not evaluation:
            raise LifecycleError("heldout policy must be frozen evaluation")
        if not namespace or namespace == "unit-test":
            raise LifecycleError("production lifecycle requires an exact namespace")
        if not callable(identity_resolver):
            raise TypeError("identity_resolver is required")
        if not callable(getattr(feature_encoder, "embed", None)) or not callable(
            getattr(feature_encoder, "provenance", None)
        ):
            raise TypeError("feature_encoder must expose embed/provenance")
        persist = getattr(persistence, "persist_bundle", None)
        if not callable(persist):
            raise TypeError("persistence must expose persist_bundle")
        if not callable(getattr(persistence, "load_policy_feature_rows", None)):
            raise TypeError("persistence must expose canonical policy feature rows")
        if not callable(getattr(persistence, "checkpoint_state", None)) or not callable(
            getattr(persistence, "restore_state", None)
        ):
            raise TypeError("persistence must expose checkpoint_state/restore_state")
        self.policy = policy
        self.persistence = persistence
        self.namespace = namespace
        self.split = split
        self.evaluation = bool(evaluation)
        self.identity_resolver = identity_resolver
        self.feature_encoder = feature_encoder
        self.feature_encoder_provenance = dict(feature_encoder.provenance())
        encoder_dim = self.feature_encoder_provenance.get(
            "dimensions", self.feature_encoder_provenance.get("dimension")
        )
        if type(encoder_dim) is not int or encoder_dim <= 0:
            raise LifecycleError("feature encoder provenance has no dimension")
        required_dim = max(
            policy.config.feature_schema.candidate_embedding_dim,
            policy.config.feature_schema.task_embedding_dim,
            policy.config.feature_schema.subtask_embedding_dim,
        )
        if encoder_dim != required_dim:
            raise LifecycleError("feature encoder dimension does not match DQN feature lock")
        lock = dict(encoder_lock)
        if {
            "model_id": self.feature_encoder_provenance.get("model_id"),
            "revision": self.feature_encoder_provenance.get("revision"),
            "dimensions": encoder_dim,
        } != {
            "model_id": lock.get("model_id"),
            "revision": lock.get("revision"),
            "dimensions": lock.get("dimensions"),
        }:
            raise LifecycleError("feature encoder provenance does not match M2 policy manifest")
        if lock.get("projection") != "NONE" or self.feature_encoder_provenance.get(
            "normalized"
        ) is not True:
            raise LifecycleError("M2 requires normalized embeddings with projection NONE")
        production_encoder = self.feature_encoder_provenance.get("production") is True
        credential_free_fixture = (
            split == "credential_free_replay"
            and self.feature_encoder_provenance.get("production") is False
            and self.feature_encoder_provenance.get("credential_free_fixture") is True
        )
        if not production_encoder and not credential_free_fixture:
            raise LifecycleError(
                "M2 lifecycle requires the frozen production feature encoder; "
                "only credential_free_replay may use an explicit fixture encoder"
            )
        self.feature_projection = "NONE"
        self.policy_manifest_hash = _canonical_digest(
            policy_manifest_hash, "policy_manifest_hash"
        )
        self.configuration_hash = self.policy_manifest_hash
        self.policy_config_hash = _digest(policy.config.as_dict())
        self.reward_config = {str(key): float(item) for key, item in reward_config.items()}
        self.graph_topology_config = dict(graph_topology_config)
        self.graph_topology_config["edge_weights"] = dict(
            graph_topology_config["edge_weights"]
        )
        self.state_feature_config = dict(state_feature_config)
        self.retrieval_config = dict(retrieval_config)
        self.capacity_config = {str(key): int(item) for key, item in capacity_config.items()}
        self.development_resume_cursor = int(development_resume_cursor)
        self.clock = clock
        self.pending_by_memory_id: dict[str, dict[str, Any]] = {}
        self.credit_ledger: list[dict[str, Any]] = []
        self.persisted_memory_count = 0
        self.prepared_task_times: dict[str, dict[str, Any]] = {}

    def before_task(self, *, task: object, sequence_index: int) -> None:
        if type(sequence_index) is not int or sequence_index < 0:
            raise LifecycleError("sequence_index must be non-negative")
        task_id = str(getattr(task, "task_id", ""))
        if not task_id:
            raise LifecycleError("task_id is required")
        existing = self.prepared_task_times.get(task_id)
        if existing is not None:
            if existing.get("sequence_index") != sequence_index:
                raise LifecycleError("task event-time sequence mismatch")
            return
        history = self.persistence.load_policy_feature_rows(
            AccessContext(str(task.org_id), str(task.user_id)),
            limit=int(self.state_feature_config["max_history_records"]),
        )
        self.prepared_task_times[task_id] = {
            "sequence_index": sequence_index,
            "event_time": self.clock(),
            "feature_history": dict(history),
        }

    def after_task(self, *, task: object, result: object) -> None:
        # AgentRuntime invokes store_experience/credit_outcome before returning
        # its result.  This hook intentionally performs no second write.
        return None

    def _task_event_time(self, task: object) -> str:
        task_id = str(getattr(task, "task_id", ""))
        prepared = self.prepared_task_times.get(task_id)
        if prepared is not None:
            return str(prepared["event_time"])
        # Direct unit/service callers remain supported, but benchmark sessions
        # always prepare and checkpoint this timestamp before canonical writes.
        observed = self.clock()
        self.prepared_task_times[task_id] = {
            "sequence_index": None,
            "event_time": observed,
        }
        return observed

    def prepared_event_time(self, task: object) -> str:
        task_id = str(getattr(task, "task_id", ""))
        prepared = self.prepared_task_times.get(task_id)
        if prepared is None or not isinstance(prepared.get("event_time"), str):
            raise LifecycleError("task event time was not prepared")
        return str(prepared["event_time"])

    def _ids(self, task: object) -> tuple[str, str]:
        raw = dict(self.identity_resolver(task))
        repository_id = str(raw.get("repository_id", ""))
        solve_job_id = str(raw.get("solve_job_id", ""))
        for name, value in (("repository_id", repository_id), ("solve_job_id", solve_job_id)):
            try:
                uuid.UUID(value)
            except (ValueError, AttributeError) as exc:
                raise LifecycleError("%s must resolve to a UUID" % name) from exc
        return repository_id, solve_job_id

    def _uuid(self, label: str) -> str:
        return str(uuid.uuid5(_ID_NAMESPACE, self.namespace + "|" + label))

    def _semantic_repository_scope(
        self, task: object, graph: object, payload: Mapping[str, Any]
    ) -> tuple[Optional[str], str, Mapping[str, Any]]:
        """Return NULL only for an explicit, identifier-free general rule."""

        repository_id, _ = self._ids(task)
        requested = payload.get("applicability_scope")
        if payload.get("applicability_scope") != "CROSS_REPOSITORY":
            return repository_id, "EXPLICIT_EXACT_REPOSITORY", {
                "requested_scope": requested,
                "required_facets_complete": True,
                "checked_source_literal_hashes": [],
                "matched_source_literal_hashes": [],
            }
        required = (
            "preconditions", "operation", "invariant", "non_applicability", "verification"
        )
        if any(not isinstance(payload.get(name), str) or not payload[name].strip() for name in required):
            return repository_id, "INCOMPLETE_GENERALIZATION_FACETS", {
                "requested_scope": requested,
                "required_facets_complete": False,
                "checked_source_literal_hashes": [],
                "matched_source_literal_hashes": [],
            }
        source_literals = {str(task.repository).casefold()}
        for node in graph.nodes.values():
            source_literals.update(
                str(value).casefold()
                for field in ("files", "symbols", "apis")
                for value in getattr(node, field, ())
                if len(str(value).strip()) >= 3
            )
        candidate_text = canonical_hash(payload) + " " + json.dumps(
            payload, ensure_ascii=False, sort_keys=True
        ).casefold()
        checked = sorted(_digest(literal) for literal in source_literals if literal)
        matched_literals = sorted(
            literal for literal in source_literals if literal and literal in candidate_text
        )
        evidence = {
            "requested_scope": requested,
            "required_facets_complete": True,
            "checked_source_literal_hashes": checked,
            "matched_source_literal_hashes": [
                _digest(literal) for literal in matched_literals
            ],
        }
        if matched_literals:
            return repository_id, "SOURCE_IDENTIFIER_PRESENT", evidence
        return None, "EXPLICIT_CROSS_REPOSITORY_IDENTIFIER_FREE", evidence

    def _graph_topology(
        self,
        *,
        graph_id: str,
        graph_kind: GraphKind,
        owner_user_id: str,
        repository_id: Optional[str],
        root_node: GraphNode,
        task: object,
        graph: object,
        grade: object,
        temporal: TemporalMetadata,
    ) -> tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...]]:
        """Compile task/DAG/evidence into deterministic canonical graph anchors."""

        nodes: dict[str, GraphNode] = {root_node.node_id: root_node}
        edges: dict[str, GraphEdge] = {}

        def anchor(node_type: NodeType, key: str, payload: Mapping[str, Any]) -> GraphNode:
            node_id = self._uuid(
                "anchor|%s|%s|%s" % (graph_id, node_type.value, _digest({"key": key, **payload}))
            )
            existing = nodes.get(node_id)
            if existing is not None:
                return existing
            item = GraphNode(
                node_id=node_id,
                graph_id=graph_id,
                org_id=str(task.org_id),
                namespace=self.namespace,
                graph_kind=graph_kind,
                owner_user_id=owner_user_id,
                repository_id=repository_id,
                node_type=node_type,
                canonical_payload=dict(payload),
                temporal=temporal,
            )
            nodes[node_id] = item
            return item

        def connect(edge_type: EdgeType, source: GraphNode, target: GraphNode) -> None:
            try:
                weight = float(
                    self.graph_topology_config["edge_weights"][edge_type.value]
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise LifecycleError(
                    "canonical topology edge is absent from the frozen manifest"
                ) from exc
            edge_id = self._uuid(
                "edge|%s|%s|%s|%s"
                % (graph_id, edge_type.value, source.node_id, target.node_id)
            )
            edges[edge_id] = GraphEdge(
                edge_id=edge_id,
                graph_id=graph_id,
                org_id=str(task.org_id),
                namespace=self.namespace,
                graph_kind=graph_kind,
                owner_user_id=owner_user_id,
                edge_type=edge_type,
                source_node_id=source.node_id,
                target_node_id=target.node_id,
                metadata={
                    "weight": weight,
                    "compiler": self.graph_topology_config["compiler"],
                },
                temporal=temporal,
            )

        task_node = anchor(NodeType.TASK, str(task.task_id), {
            "task_id": str(task.task_id), "objective": str(task.instruction)
        })
        repository = anchor(NodeType.REPOSITORY, str(task.repository), {
            "repository": str(task.repository), "source_repository_id": self._ids(task)[0]
        })
        version = anchor(NodeType.VERSION, str(task.commit), {"version": str(task.commit)})
        user = anchor(NodeType.USER, str(task.user_id), {"user": str(task.user_id)})
        outcome = anchor(NodeType.OUTCOME, "passed" if grade.resolved else "failed", {
            "outcome": "passed" if grade.resolved else "failed",
            "grader_report_hash": _digest(grade.report),
        })
        connect(EdgeType.DERIVED_FROM, root_node, task_node)
        connect(EdgeType.VALID_FOR, root_node, repository)
        connect(EdgeType.VALID_FOR, root_node, version)
        connect(EdgeType.PRODUCED, root_node, outcome)
        connect(EdgeType.OBSERVED, task_node, user)

        subtask_nodes: dict[str, GraphNode] = {}
        ordered = sorted(
            graph.nodes.values(), key=lambda item: (item.created_order, item.node_id)
        )
        for source in ordered:
            subtask = anchor(NodeType.SUBTASK, source.node_id, {
                "subtask_id": source.node_id,
                "objective": source.objective,
                "operation": source.operation,
                "preconditions": list(source.preconditions),
                "invariants": list(source.invariants),
            })
            subtask_nodes[source.node_id] = subtask
            connect(EdgeType.DECOMPOSES_TO, task_node, subtask)
            operation = anchor(NodeType.OPERATION, source.operation, {
                "operation": source.operation
            })
            connect(EdgeType.APPLIED, subtask, operation)
            for value in source.files:
                connect(EdgeType.TOUCHES, subtask, anchor(NodeType.FILE, value, {"path": value}))
            for value in source.symbols:
                connect(EdgeType.TOUCHES, subtask, anchor(NodeType.SYMBOL, value, {"symbol": value}))
            for value in source.apis:
                connect(EdgeType.CALLS, subtask, anchor(NodeType.API, value, {"api": value}))
            for value in source.errors:
                connect(EdgeType.OBSERVED, subtask, anchor(NodeType.ERROR, value, {"error": value}))
            for value in source.tests:
                connect(
                    EdgeType.VERIFIED_BY,
                    subtask,
                    anchor(NodeType.TEST, value, {"test": value}),
                )
        for source in ordered:
            for dependency_id in source.dependencies:
                dependency = subtask_nodes.get(dependency_id)
                if dependency is not None:
                    connect(
                        EdgeType.DEPENDS_ON,
                        subtask_nodes[source.node_id],
                        dependency,
                    )
        return (
            tuple(nodes[key] for key in sorted(nodes) if key != root_node.node_id),
            tuple(edges[key] for key in sorted(edges)),
        )

    def _state(self, task, graph, extraction, grade, *, observed_at: str):
        schema = self.policy.config.feature_schema
        candidate = json.dumps(
            {"episode": extraction.episode, "semantic": extraction.semantic_candidate},
            ensure_ascii=False,
            sort_keys=True,
        )
        candidate_embedding = self._project_feature(
            candidate, schema.candidate_embedding_dim
        )
        prepared = self.prepared_task_times.get(str(task.task_id))
        history = prepared.get("feature_history") if prepared is not None else None
        if history is None:
            history = self.persistence.load_policy_feature_rows(
                AccessContext(str(task.org_id), str(task.user_id)),
                limit=int(self.state_feature_config["max_history_records"]),
            )
            if prepared is not None:
                prepared["feature_history"] = dict(history)
        if not isinstance(history, Mapping):
            raise LifecycleError("prepared policy feature history is malformed")
        digest = history.get("digest")
        body = {key: value for key, value in history.items() if key != "digest"}
        if (
            body.get("schema") != "trimem/canonical-policy-feature-rows/1.0"
            or body.get("namespace") != self.namespace
            or body.get("history_limit")
            != self.state_feature_config["max_history_records"]
            or not isinstance(body.get("rows"), list)
            or canonical_hash(body) != digest
        ):
            raise LifecycleError("canonical policy feature history failed its seal")
        rows = list(body["rows"])
        best_row: Optional[Mapping[str, Any]] = None
        best_similarity = 0.0
        for row in rows:
            if not isinstance(row, Mapping):
                raise LifecycleError("canonical policy feature row is malformed")
            text = row.get("retrieval_text")
            if not isinstance(text, str) or not text.strip():
                raise LifecycleError("canonical policy feature row has no retrieval text")
            memory_embedding = self._project_feature(text, schema.candidate_embedding_dim)
            similarity = max(
                0.0,
                min(1.0, sum(a * b for a, b in zip(candidate_embedding, memory_embedding))),
            )
            if best_row is None or (similarity, str(row.get("node_id", ""))) > (
                best_similarity,
                str(best_row.get("node_id", "")),
            ):
                best_row = row
                best_similarity = similarity

        recency = 0.0
        reuse_frequency = 0.0
        past_gain_loss = 0.0
        if best_row is not None:
            try:
                now = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
                last = datetime.fromisoformat(
                    str(best_row["last_activity_at"]).replace("Z", "+00:00")
                )
            except (KeyError, ValueError) as exc:
                raise LifecycleError("canonical feature recency timestamp is invalid") from exc
            if now.tzinfo is None or last.tzinfo is None:
                raise LifecycleError("canonical feature recency timestamp lacks timezone")
            age_seconds = max(0.0, (now - last).total_seconds())
            recency = 0.5 ** (
                age_seconds
                / float(self.state_feature_config["recency_half_life_seconds"])
            )
            raw_strength = best_row.get("strength")
            strength = dict(raw_strength) if isinstance(raw_strength, Mapping) else {}
            reuse_count = max(
                float(best_row.get("reuse_count", 0)),
                float(strength.get("successful_reuse", 0.0)),
            )
            reuse_frequency = min(
                1.0,
                reuse_count / float(self.state_feature_config["reuse_frequency_scale"]),
            )
            gain = float(strength.get("successful_reuse", 0.0))
            loss = sum(
                float(strength.get(name, 0.0))
                for name in ("negative_transfer", "contradiction", "version_staleness")
            )
            evidence = sum(
                float(strength.get(name, 0.0))
                for name in (
                    "support", "successful_reuse", "independent_user_evidence",
                    "recent_verification", "negative_transfer", "contradiction",
                    "version_staleness",
                )
            )
            past_gain_loss = max(-1.0, min(1.0, (gain - loss) / max(1.0, evidence)))

        scope = (
            extraction.semantic_candidate.get("applicability_scope")
            if isinstance(extraction.semantic_candidate, Mapping)
            else "EXACT_REPOSITORY"
        )
        version_validity = float(
            str(task.commit).strip().upper() != "UNKNOWN"
            and scope in {"EXACT_REPOSITORY", "CROSS_REPOSITORY"}
        )
        subtasks = " ".join(
            node.objective + " " + node.operation for node in graph.nodes.values()
        )
        occupancy = min(
            1.0,
            len(rows) / float(self.state_feature_config["max_history_records"]),
        )
        stats = [
            min(1.0, len(graph.nodes) / 10.0),
            occupancy,
            1.0 if graph.complete else 0.0,
        ]
        while len(stats) < schema.graph_statistics_dim:
            stats.append(0.0)
        state = MemoryState(
            candidate_embedding=candidate_embedding,
            task_embedding=self._project_feature(task.instruction, schema.task_embedding_dim),
            subtask_embedding=self._project_feature(subtasks, schema.subtask_embedding_dim),
            verification_outcome=1.0 if grade.resolved else -1.0,
            novelty=1.0 - best_similarity,
            redundancy=best_similarity,
            recency=recency,
            reuse_frequency=reuse_frequency,
            past_gain_loss=past_gain_loss,
            version_validity=version_validity,
            memory_occupancy=occupancy,
            graph_statistics=tuple(stats[: schema.graph_statistics_dim]),
            context_cost=min(1.0, len(candidate.encode("utf-8")) / 12_000.0),
        )
        provenance = {
            "algorithm": self.state_feature_config["algorithm"],
            "canonical_history_digest": digest,
            "canonical_history_count": len(rows),
            "history_status": "MATCHED" if best_row is not None else "EMPTY",
            "nearest_node_id": str(best_row["node_id"]) if best_row is not None else None,
            "nearest_node_content_hash": (
                str(best_row["node_content_hash"]) if best_row is not None else None
            ),
            "max_cosine_similarity": best_similarity,
            "observed_at": observed_at,
        }
        return state, provenance

    def _project_feature(self, text: str, dimensions: int) -> tuple[float, ...]:
        raw = tuple(float(value) for value in self.feature_encoder.embed(text))
        if len(raw) != dimensions or not all(math.isfinite(value) for value in raw):
            raise LifecycleError("feature encoder output violates the frozen dimension")
        norm = sum(value * value for value in raw) ** 0.5
        if not math.isclose(norm, 1.0, rel_tol=1e-5, abs_tol=1e-5):
            raise LifecycleError("feature encoder output is not normalized")
        return raw

    def store_experience(self, task, graph, extraction, grade, injections):
        repository_id, solve_job_id = self._ids(task)
        source = json.dumps(
            {"episode": extraction.episode, "semantic": extraction.semantic_candidate},
            ensure_ascii=False,
            sort_keys=True,
        )
        security_scan = promotion_security.scan(source)
        secret_free = not bool(security_scan["blocking"])
        now = self._task_event_time(task)
        state, state_feature_provenance = self._state(
            task, graph, extraction, grade, observed_at=now
        )
        if not secret_free:
            action_mask = ActionMask.only(MemoryAction.FORGET)
            gate = "SECRET_FILTER"
        elif not grade.resolved or extraction.semantic_candidate is None:
            action_mask = ActionMask(True, True, False)
            gate = "SEMANTIC_REQUIRES_VERIFIED_SUCCESS"
        else:
            action_mask = ActionMask()
            gate = "ELIGIBLE"

        policy_before = self.policy.runtime_state()
        decision = self.policy.decide(state, action_mask, evaluation=self.evaluation)
        temporal = TemporalMetadata(
            ingested_at=now,
            event_time=now,
            source_available_at=now,
            last_verified_at=now,
        )
        task_key = "%s|%s" % (task.task_id, extraction.response_hash)
        work_graph_id = self._uuid("working-graph|" + task.task_id)
        candidate_id = self._uuid("working-candidate|" + task_key)
        work_graph = CanonicalWorkingGraph(
            graph_id=work_graph_id,
            org_id=str(task.org_id),
            namespace=self.namespace,
            owner_user_id=str(task.user_id),
            repository_id=repository_id,
            solve_job_id=solve_job_id,
            temporal=temporal,
        )
        candidate = GraphNode(
            node_id=candidate_id,
            graph_id=work_graph_id,
            org_id=str(task.org_id),
            namespace=self.namespace,
            graph_kind=GraphKind.SHORT_TERM_WORKING,
            owner_user_id=str(task.user_id),
            repository_id=repository_id,
            node_type=NodeType.SUBTASK,
            canonical_payload={
                "source_task_id": task.task_id,
                "extraction_hash": _canonical_digest(extraction.response_hash, "response_hash"),
                "storage_candidate_hash": _digest({
                    "episode": extraction.episode,
                    "semantic": extraction.semantic_candidate,
                }),
            },
            temporal=temporal,
        )

        schema_action = {
            MemoryAction.FORGET: PolicyAction.FORGET,
            MemoryAction.MOVE_TO_EPISODIC: PolicyAction.MOVE_TO_EPISODIC,
            MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE: PolicyAction.MOVE_TO_SEMANTIC_CANDIDATE,
        }[decision.action]
        target_kind = {
            MemoryAction.FORGET: None,
            MemoryAction.MOVE_TO_EPISODIC: GraphKind.USER_EPISODIC,
            MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE: GraphKind.USER_SEMANTIC,
        }[decision.action]
        transition = PolicyTransition(
            transition_id=self._uuid("policy-transition|" + task_key),
            graph_id=work_graph_id,
            candidate_node_id=candidate_id,
            org_id=str(task.org_id),
            namespace=self.namespace,
            owner_user_id=str(task.user_id),
            action=schema_action,
            actor=PolicyActor.DOUBLE_DQN,
            target_graph_kind=target_kind,
            state_features_hash=canonical_hash(asdict(state)),
            event_time=now,
        )

        graphs = [work_graph]
        nodes = [candidate]
        topology_nodes, topology_edges = self._graph_topology(
            graph_id=work_graph.graph_id,
            graph_kind=work_graph.kind,
            owner_user_id=str(task.user_id),
            repository_id=repository_id,
            root_node=candidate,
            task=task,
            graph=graph,
            grade=grade,
            temporal=temporal,
        )
        nodes.extend(topology_nodes)
        edges = list(topology_edges)
        supports = []
        strengths = []
        index_ids = []
        memory_id: Optional[str] = None
        memory_graph_id: Optional[str] = None
        memory_kind: Optional[str] = None
        episode_node = None
        semantic_strength_record: Optional[SemanticStrengthRecord] = None
        patch_hash = _canonical_digest(getattr(extraction, "patch_hash", ""), "patch_hash")
        public_evidence_hash = _canonical_digest(
            getattr(extraction, "public_evidence_hash", ""), "public_evidence_hash"
        )
        verifier_hash = _digest(grade.report)

        if decision.action != MemoryAction.FORGET:
            episode_graph = UserEpisodicGraph(
                graph_id=self._uuid("episode-graph|" + task_key),
                org_id=str(task.org_id),
                namespace=self.namespace,
                owner_user_id=str(task.user_id),
                repository_id=repository_id,
                temporal=temporal,
            )
            episode_node = GraphNode(
                node_id=self._uuid("episode-node|" + task_key),
                graph_id=episode_graph.graph_id,
                org_id=str(task.org_id),
                namespace=self.namespace,
                graph_kind=GraphKind.USER_EPISODIC,
                owner_user_id=str(task.user_id),
                repository_id=repository_id,
                node_type=NodeType.EPISODE,
                canonical_payload=self._episode_payload(
                    task, extraction, grade, patch_hash, public_evidence_hash, verifier_hash
                ),
                temporal=temporal,
            )
            graphs.append(episode_graph)
            nodes.append(episode_node)
            topology_nodes, topology_edges = self._graph_topology(
                graph_id=episode_graph.graph_id,
                graph_kind=episode_graph.kind,
                owner_user_id=str(task.user_id),
                repository_id=repository_id,
                root_node=episode_node,
                task=task,
                graph=graph,
                grade=grade,
                temporal=temporal,
            )
            nodes.extend(topology_nodes)
            edges.extend(topology_edges)
            if decision.action == MemoryAction.MOVE_TO_EPISODIC:
                memory_id = episode_node.node_id
                memory_graph_id = episode_graph.graph_id
                memory_kind = "EPISODIC"
                index_ids.append(episode_node.node_id)

        if decision.action == MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE:
            if not grade.resolved or extraction.semantic_candidate is None or episode_node is None:
                self.policy.restore_runtime_state(policy_before)
                raise LifecycleError("unverified semantic candidate escaped its action mask")
            (
                semantic_repository_id,
                applicability_reason,
                applicability_evidence,
            ) = self._semantic_repository_scope(
                task, graph, extraction.semantic_candidate
            )
            semantic_graph = UserSemanticGraph(
                graph_id=self._uuid("semantic-graph|" + task_key),
                org_id=str(task.org_id),
                namespace=self.namespace,
                owner_user_id=str(task.user_id),
                repository_id=semantic_repository_id,
                temporal=temporal,
            )
            semantic_node = GraphNode(
                node_id=self._uuid("semantic-node|" + task_key),
                graph_id=semantic_graph.graph_id,
                org_id=str(task.org_id),
                namespace=self.namespace,
                graph_kind=GraphKind.USER_SEMANTIC,
                owner_user_id=str(task.user_id),
                repository_id=semantic_repository_id,
                node_type=NodeType.SEMANTIC_RULE,
                canonical_payload=self._semantic_payload(
                    task,
                    extraction,
                    episode_node,
                    source_repository_id=repository_id,
                    generalized=semantic_repository_id is None,
                    applicability_reason=applicability_reason,
                    applicability_evidence=applicability_evidence,
                ),
                temporal=temporal,
            )
            support = SemanticSupport(
                support_id=self._uuid("semantic-support|" + task_key),
                semantic_graph_id=semantic_graph.graph_id,
                semantic_node_id=semantic_node.node_id,
                org_id=str(task.org_id),
                namespace=self.namespace,
                graph_kind=GraphKind.USER_SEMANTIC,
                owner_user_id=str(task.user_id),
                source_episode_id=episode_node.node_id,
                source_evidence_hash=episode_node.payload_hash,
                contributor_hash=_digest({"user_id": task.user_id}),
                temporal=temporal,
            )
            graphs.append(semantic_graph)
            nodes.append(semantic_node)
            topology_nodes, topology_edges = self._graph_topology(
                graph_id=semantic_graph.graph_id,
                graph_kind=semantic_graph.kind,
                owner_user_id=str(task.user_id),
                repository_id=semantic_repository_id,
                root_node=semantic_node,
                task=task,
                graph=graph,
                grade=grade,
                temporal=temporal,
            )
            nodes.extend(topology_nodes)
            edges.extend(topology_edges)
            supports.append(support)
            semantic_strength_record = SemanticStrengthRecord(
                strength_id=self._uuid("semantic-strength|" + semantic_node.node_id),
                graph_id=semantic_graph.graph_id,
                semantic_node_id=semantic_node.node_id,
                org_id=str(task.org_id),
                namespace=self.namespace,
                graph_kind=GraphKind.USER_SEMANTIC,
                owner_user_id=str(task.user_id),
                strength=SemanticStrength(support=1.0, recent_verification=1.0),
                updated_at=now,
            )
            strengths.append(semantic_strength_record)
            memory_id = semantic_node.node_id
            memory_graph_id = semantic_graph.graph_id
            memory_kind = "USER_SEMANTIC"
            index_ids.append(semantic_node.node_id)

        credit_id = "credit:" + candidate_id
        if not self.evaluation:
            self.policy.queue_delayed_credit(
                credit_id,
                state,
                decision.action,
                action_mask,
                split="development",
            )
        pending_key = memory_id or "forgotten:" + candidate_id
        pending = {
            "credit_id": None if self.evaluation else credit_id,
            "state": asdict(state),
            "action": decision.action.value,
            "source_task_id": task.task_id,
            "source_event_time": now,
            "context_cost": state.context_cost,
            "source_storage_bytes": len(source.encode("utf-8")),
            "state_feature_provenance": state_feature_provenance,
            "work_graph_id": work_graph_id,
            "candidate_node_id": candidate_id,
            "org_id": str(task.org_id),
            "owner_user_id": str(task.user_id),
            "semantic_strength_id": (
                semantic_strength_record.strength_id
                if semantic_strength_record is not None else None
            ),
            "semantic_graph_id": (
                semantic_strength_record.graph_id
                if semantic_strength_record is not None else None
            ),
            "semantic_node_id": (
                semantic_strength_record.semantic_node_id
                if semantic_strength_record is not None else None
            ),
        }
        try:
            receipt = self.persistence.persist_bundle(
                AccessContext(str(task.org_id), str(task.user_id)),
                LifecycleAppendBundle(
                    operation_id=self._uuid("lifecycle-operation|store|" + task_key),
                    operation_scope={
                        "kind": "LIFECYCLE_STORE",
                        "task_id": str(task.task_id),
                        "active_node_ids": [],
                    },
                    graphs=tuple(graphs),
                    nodes=tuple(nodes),
                    edges=tuple(edges),
                    supports=tuple(supports),
                    transitions=(transition,),
                    strengths=tuple(strengths),
                    index_node_ids=tuple(index_ids),
                    capacity_limits=CapacityLimits(**self.capacity_config),
                    capacity_archived_at=now,
                ),
            )
        except BaseException:
            self.policy.restore_runtime_state(policy_before)
            raise
        self.pending_by_memory_id[pending_key] = pending
        self.persisted_memory_count += len(index_ids)
        retained_records = int(episode_node is not None) + int(
            semantic_strength_record is not None
        )
        archived_records = len(tuple(receipt.get("deleted", ())))
        return {
            "storage_action": decision.action.value,
            "action_mask": list(decision.allowed),
            "q_values": list(decision.q_values),
            "epsilon": decision.epsilon,
            "evaluation": decision.evaluation,
            "deterministic_gate": gate,
            "secret_free": secret_free,
            "security_scan_result": security_scan["result"],
            "memory_id": memory_id,
            "memory_kind": memory_kind,
            "canonical_graph_id": memory_graph_id,
            "namespace": self.namespace,
            "canonical_candidate_node_id": candidate_id,
            "state_feature_provenance": state_feature_provenance,
            "receipt_digest": receipt["receipt_digest"],
            "delayed_credit_id": None if self.evaluation else credit_id,
            "paid_model_calls": 0,
            "retained_records": retained_records,
            "archived_records": archived_records,
            "net_memory_growth": retained_records - archived_records,
        }

    @staticmethod
    def _episode_payload(task, extraction, grade, patch_hash, public_evidence_hash, verifier_hash):
        summary = str(extraction.episode["summary"])
        action = str(extraction.episode["action"])
        return {
            "retrieval_text": " ".join((summary, action, str(task.repository))),
            "execution_view": json.dumps({
                "kind": "episodic",
                "source_repository": task.repository,
                "source_commit": task.commit,
                "summary": summary,
                "action": action,
                "outcome": "passed" if grade.resolved else "failed",
                "patch_hash": patch_hash,
                "public_evidence_hash": public_evidence_hash,
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "version": task.commit,
            "version_valid": True,
            "stale": False,
            "servable": True,
            "verified": True,
            "source_outcome": "passed" if grade.resolved else "failed",
            "quality": 1.0 if grade.resolved else 0.7,
            "completeness": 0.65,
            "coverage": ["operation", "verification"],
            "provenance": {
                "source_task_id": task.task_id,
                "patch_hash": patch_hash,
                "public_evidence_hash": public_evidence_hash,
                "verifier_hash": verifier_hash,
                "extraction_hash": _canonical_digest(extraction.response_hash, "response_hash"),
                "contributor_hash": canonical_hash({
                    "schema": "trimem/promotion-contributor/1.0",
                    "org_id": str(task.org_id),
                    "user_id": str(task.user_id),
                }),
            },
        }

    @staticmethod
    def _semantic_payload(
        task,
        extraction,
        episode_node,
        *,
        source_repository_id,
        generalized,
        applicability_reason,
        applicability_evidence,
    ):
        payload = dict(extraction.semantic_candidate)
        retrieval_text = " ".join(str(payload.get(key, "")) for key in (
            "preconditions", "operation", "invariant", "non_applicability", "verification"
        ))
        return {
            "retrieval_text": retrieval_text,
            "execution_view": json.dumps(
                {"kind": "user_semantic", **payload},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "version": task.commit,
            "version_valid": True,
            "stale": False,
            "servable": True,
            "verified": True,
            "source_outcome": "passed",
            "quality": 1.0,
            "completeness": 1.0,
            "coverage": [
                "operation", "precondition", "invariant", "non_applicability", "verification"
            ],
            "provenance": {
                "source_task_id": task.task_id,
                "source_episode_hash": episode_node.payload_hash,
                "source_repository_id": source_repository_id,
                "applicability_scope": extraction.semantic_candidate["applicability_scope"],
                "generalized_repository": bool(generalized),
                "applicability_decision_reason": applicability_reason,
                "applicability_literal_check": dict(applicability_evidence),
            },
        }

    def credit_outcome(self, task, grade, injections, *, outcome_metrics):
        if not isinstance(outcome_metrics, Mapping):
            raise LifecycleError("production DQN credit requires outcome metrics")
        expected_metric_fields = {
            "schema",
            "subtask_completion",
            "actual_total_tokens",
            "actual_reasoning_tokens",
            "actual_wall_time_ms",
            "injected_context_bytes",
            "stale_conflict_reuse_count",
            "stale_conflict_memory_ids",
        }
        if set(outcome_metrics) != expected_metric_fields or outcome_metrics.get(
            "schema"
        ) != "trimem/outcome-metrics/1.0":
            raise LifecycleError("outcome metric schema drift")
        numeric_metric_fields = expected_metric_fields - {
            "schema", "stale_conflict_memory_ids"
        }
        metrics = {
            name: _number(outcome_metrics[name], "outcome_metrics.%s" % name)
            for name in numeric_metric_fields
        }
        conflict_ids = outcome_metrics["stale_conflict_memory_ids"]
        if (
            not isinstance(conflict_ids, (list, tuple))
            or any(not isinstance(value, str) or not value for value in conflict_ids)
            or tuple(conflict_ids) != tuple(sorted(set(conflict_ids)))
            or len(conflict_ids) != int(metrics["stale_conflict_reuse_count"])
        ):
            raise LifecycleError("stale/conflict memory evidence is invalid")
        if not 0.0 <= metrics["subtask_completion"] <= 1.0 or any(
            metrics[name] < 0.0
            for name in (
                "actual_total_tokens", "actual_reasoning_tokens", "actual_wall_time_ms",
                "injected_context_bytes", "stale_conflict_reuse_count",
            )
        ):
            raise LifecycleError("outcome metrics are outside their valid range")
        injected_rows: dict[str, Mapping[str, Any]] = {}
        for raw in injections:
            if not isinstance(raw, Mapping) or not isinstance(raw.get("memory_id"), str):
                raise LifecycleError("injection ledger entry is invalid")
            memory_id = str(raw["memory_id"])
            if memory_id in injected_rows and dict(injected_rows[memory_id]) != dict(raw):
                raise LifecycleError("conflicting duplicate injection ledger entry")
            injected_rows[memory_id] = raw
        injected = set(injected_rows)
        if not set(conflict_ids) <= injected:
            raise LifecycleError("stale/conflict evidence references uninjected memory")
        credit_time = self._task_event_time(task)
        strength_increments: dict[str, SemanticStrengthIncrement] = {}
        semantic_kinds = {
            "USER_SEMANTIC": GraphKind.USER_SEMANTIC,
            "ORG_SEMANTIC": GraphKind.ORGANISATION_SEMANTIC,
            "ORGANISATION_SEMANTIC": GraphKind.ORGANISATION_SEMANTIC,
        }
        for memory_id, row in injected_rows.items():
            graph_kind = semantic_kinds.get(str(row.get("kind", "")))
            if graph_kind is None:
                continue
            graph_id = row.get("canonical_graph_id")
            namespace = row.get("namespace")
            if not isinstance(graph_id, str) or not graph_id or namespace != self.namespace:
                raise LifecycleError("semantic reuse lacks canonical graph/namespace provenance")
            strength_increments[memory_id] = SemanticStrengthIncrement(
                graph_id=graph_id,
                semantic_node_id=memory_id,
                org_id=str(task.org_id),
                namespace=self.namespace,
                graph_kind=graph_kind,
                owner_user_id=(
                    str(task.user_id) if graph_kind == GraphKind.USER_SEMANTIC else None
                ),
                successful_reuse=1.0 if grade.resolved else 0.0,
                recent_verification=1.0 if grade.resolved else 0.0,
                negative_transfer=0.0 if grade.resolved else 1.0,
                contradiction=(1.0 if memory_id in conflict_ids else 0.0),
                updated_at=credit_time,
            )
        credited = []
        strength_updates = []
        for memory_id in sorted(injected & set(self.pending_by_memory_id)):
            pending = self.pending_by_memory_id[memory_id]
            state = MemoryState(**pending["state"])
            normalized = {
                "subtask_completion": metrics["subtask_completion"],
                "context_cost": min(
                    1.0,
                    metrics["injected_context_bytes"]
                    / float(self.retrieval_config["context_budget_bytes"]),
                ),
                "token_cost": min(
                    1.0,
                    metrics["actual_total_tokens"]
                    / self.reward_config["token_normalization"],
                ),
                "latency_cost": min(
                    1.0,
                    metrics["actual_wall_time_ms"]
                    / self.reward_config["latency_normalization_ms"],
                ),
                "storage_cost": min(
                    1.0,
                    float(pending["source_storage_bytes"])
                    / self.reward_config["storage_normalization_bytes"],
                ),
                "stale_conflict": min(
                    1.0, metrics["stale_conflict_reuse_count"]
                ),
            }
            reward_components = {
                "outcome": self.reward_config[
                    "successful_outcome" if grade.resolved else "failure_outcome"
                ],
                "reuse": self.reward_config[
                    "successful_reuse" if grade.resolved else "negative_transfer"
                ],
                "subtask_completion": self.reward_config[
                    "subtask_completion_coefficient"
                ] * normalized["subtask_completion"],
                "context_cost": self.reward_config["context_cost_coefficient"]
                * normalized["context_cost"],
                "token_cost": self.reward_config["token_cost_coefficient"]
                * normalized["token_cost"],
                "latency_cost": self.reward_config["latency_cost_coefficient"]
                * normalized["latency_cost"],
                "storage_cost": self.reward_config["storage_cost_coefficient"]
                * normalized["storage_cost"],
                "stale_conflict": self.reward_config["stale_conflict_coefficient"]
                * normalized["stale_conflict"],
            }
            reward = sum(reward_components.values())
            policy_before = self.policy.runtime_state()
            losses = []
            if not self.evaluation:
                losses = self.policy.credit_delayed_reward(
                    pending["credit_id"],
                    reward,
                    replace(
                        state,
                        reuse_frequency=state.reuse_frequency + 1.0,
                        past_gain_loss=state.past_gain_loss + reward,
                    ),
                    done=True,
                    split="development",
                    train_updates=1,
                )
            action = MemoryAction(pending["action"])
            transition = PolicyTransition(
                transition_id=self._uuid(
                    "credit-transition|%s|%s" % (memory_id, task.task_id)
                ),
                graph_id=pending["work_graph_id"],
                candidate_node_id=pending["candidate_node_id"],
                org_id=pending["org_id"],
                namespace=self.namespace,
                owner_user_id=pending["owner_user_id"],
                action={
                    MemoryAction.FORGET: PolicyAction.FORGET,
                    MemoryAction.MOVE_TO_EPISODIC: PolicyAction.MOVE_TO_EPISODIC,
                    MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE:
                        PolicyAction.MOVE_TO_SEMANTIC_CANDIDATE,
                }[action],
                actor=PolicyActor.DOUBLE_DQN,
                target_graph_kind={
                    MemoryAction.FORGET: None,
                    MemoryAction.MOVE_TO_EPISODIC: GraphKind.USER_EPISODIC,
                    MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE: GraphKind.USER_SEMANTIC,
                }[action],
                state_features_hash=canonical_hash(asdict(state)),
                reward=reward,
                delayed_credit_ref=(
                    "observation:%s" % memory_id
                    if self.evaluation else str(pending["credit_id"])
                ),
                event_time=credit_time,
            )
            increment = strength_increments.pop(memory_id, None)
            try:
                receipt = self.persistence.persist_bundle(
                    AccessContext(pending["org_id"], pending["owner_user_id"]),
                    LifecycleAppendBundle(
                        operation_id=self._uuid(
                            "lifecycle-operation|credit|%s|%s"
                            % (memory_id, task.task_id)
                        ),
                        operation_scope={
                            "kind": "CREDIT",
                            "task_id": str(task.task_id),
                            "active_node_ids": sorted({
                                str(row.get("active_node_id"))
                                for row in injected_rows.values()
                                if isinstance(row.get("active_node_id"), str)
                                and row.get("active_node_id")
                            }),
                        },
                        transitions=(transition,),
                        strength_increments=((increment,) if increment is not None else ()),
                    ),
                )
            except BaseException:
                if not self.evaluation:
                    self.policy.restore_runtime_state(policy_before)
                raise
            if increment is not None:
                strength_updates.append({
                    "memory_id": memory_id,
                    "receipt_digest": receipt["receipt_digest"],
                    "successful_reuse_delta": increment.successful_reuse,
                    "negative_transfer_delta": increment.negative_transfer,
                    "contradiction_delta": increment.contradiction,
                })
            row = {
                "memory_id": memory_id,
                "source_task_id": pending["source_task_id"],
                "target_task_id": task.task_id,
                "target_resolved": grade.resolved,
                "reward": reward,
                "reward_components": reward_components,
                "normalized_outcome_metrics": normalized,
                "outcome_metrics": dict(outcome_metrics),
                "negative_transfer": not grade.resolved,
                "losses": losses,
                "evaluation_mutation": False if self.evaluation else None,
            }
            credited.append(row)
            self.credit_ledger.append(row)
            del self.pending_by_memory_id[memory_id]
        for memory_id in sorted(strength_increments):
            increment = strength_increments[memory_id]
            receipt = self.persistence.persist_bundle(
                AccessContext(str(task.org_id), str(task.user_id)),
                LifecycleAppendBundle(
                    operation_id=self._uuid(
                        "lifecycle-operation|strength|%s|%s"
                        % (memory_id, task.task_id)
                    ),
                    operation_scope={
                        "kind": "CREDIT",
                        "task_id": str(task.task_id),
                        "active_node_ids": sorted({
                            str(row.get("active_node_id"))
                            for row in injected_rows.values()
                            if isinstance(row.get("active_node_id"), str)
                            and row.get("active_node_id")
                        }),
                    },
                    strength_increments=(increment,),
                ),
            )
            strength_updates.append({
                "memory_id": memory_id,
                "receipt_digest": receipt["receipt_digest"],
                "successful_reuse_delta": increment.successful_reuse,
                "negative_transfer_delta": increment.negative_transfer,
                "contradiction_delta": increment.contradiction,
            })
        return {
            "credited": len(credited),
            "transitions": credited,
            "strength_updates": tuple(strength_updates),
            "pending_credit_count": 0 if self.evaluation else self.policy.pending_credit_count,
            "replay_size": self.policy.replay_size,
            "training_steps": self.policy.training_steps,
            "evaluation_mutation": False if self.evaluation else None,
        }

    def checkpoint_state(self) -> Mapping[str, Any]:
        payload = {
            "schema": "trimem/postgres-dqn-lifecycle/1.0",
            "namespace": self.namespace,
            "split": self.split,
            "evaluation": self.evaluation,
            "persisted_memory_count": self.persisted_memory_count,
            "pending_by_memory_id": self.pending_by_memory_id,
            "credit_ledger": self.credit_ledger,
            "policy": self.policy.runtime_state(),
            "policy_config_hash": self.policy_config_hash,
            "policy_manifest_hash": self.policy_manifest_hash,
            "feature_encoder_provenance": self.feature_encoder_provenance,
            "feature_projection": self.feature_projection,
            "reward_config": self.reward_config,
            "graph_topology_config": self.graph_topology_config,
            "state_feature_config": self.state_feature_config,
            "retrieval_config": self.retrieval_config,
            "capacity_config": self.capacity_config,
            "development_resume_cursor": self.development_resume_cursor,
            "prepared_task_times": self.prepared_task_times,
            "persistence_state": self.persistence.checkpoint_state(),
        }
        frozen = deepcopy(payload)
        return {"payload": frozen, "digest": _digest(frozen)}

    def restore(self, value: Mapping[str, Any]) -> None:
        payload = value.get("payload")
        if not isinstance(payload, Mapping) or _digest(payload) != value.get("digest"):
            raise LifecycleError("lifecycle checkpoint digest mismatch")
        if (
            payload.get("schema") != "trimem/postgres-dqn-lifecycle/1.0"
            or payload.get("namespace") != self.namespace
            or payload.get("split") != self.split
            or bool(payload.get("evaluation")) != self.evaluation
            or payload.get("policy_config_hash") != self.policy_config_hash
            or payload.get("policy_manifest_hash") != self.policy_manifest_hash
            or payload.get("feature_encoder_provenance") != self.feature_encoder_provenance
            or payload.get("feature_projection") != self.feature_projection
            or payload.get("reward_config") != self.reward_config
            or payload.get("graph_topology_config") != self.graph_topology_config
            or payload.get("state_feature_config") != self.state_feature_config
            or payload.get("retrieval_config") != self.retrieval_config
            or payload.get("capacity_config") != self.capacity_config
            or payload.get("development_resume_cursor") != self.development_resume_cursor
        ):
            raise LifecycleError("lifecycle checkpoint identity mismatch")
        persistence_state = payload.get("persistence_state")
        if not isinstance(persistence_state, Mapping):
            raise LifecycleError("lifecycle persistence checkpoint is missing")
        self.persistence.restore_state(persistence_state)
        self.policy.restore_runtime_state(payload["policy"])
        self.pending_by_memory_id = {
            str(key): dict(item)
            for key, item in payload.get("pending_by_memory_id", {}).items()
        }
        self.credit_ledger = [dict(item) for item in payload.get("credit_ledger", ())]
        prepared = payload.get("prepared_task_times", {})
        if not isinstance(prepared, Mapping) or any(
            not isinstance(key, str)
            or not isinstance(item, Mapping)
            or not isinstance(item.get("event_time"), str)
            or item.get("sequence_index") is not None
            and (type(item.get("sequence_index")) is not int or item["sequence_index"] < 0)
            for key, item in prepared.items()
        ):
            raise LifecycleError("prepared task event-time ledger is invalid")
        self.prepared_task_times = {
            str(key): dict(item) for key, item in prepared.items()
        }
        self.persisted_memory_count = int(payload.get("persisted_memory_count", 0))
        if self.persisted_memory_count < 0:
            raise LifecycleError("persisted memory count cannot be negative")

    # BenchmarkArmSession deliberately uses one restore method name for every
    # lifecycle adapter.  Keep ``restore`` as a compatibility alias for direct
    # callers, but make the session-facing method explicit.
    def restore_state(self, value: Mapping[str, Any]) -> None:
        self.restore(value)

    def finalize_development_and_freeze(
        self, *, completed_cursor: int, expected_cursor: Optional[int] = None
    ) -> Mapping[str, Any]:
        """Close every no-reuse credit and export the sole final DEV policy.

        Each transition is committed before its pending entry is removed.  A
        crash can therefore resume from the lifecycle checkpoint without
        inventing credit or mutating an already-frozen evaluation policy.
        """

        required_cursor = (
            self.development_resume_cursor
            if expected_cursor is None else int(expected_cursor)
        )
        if required_cursor != self.development_resume_cursor:
            raise LifecycleError("development finalization cursor differs from manifest")
        if completed_cursor != required_cursor:
            raise LifecycleError("development stream is not complete")
        if self.evaluation or self.split != "development" or self.policy.frozen:
            raise LifecycleError("only a mutable development lifecycle can be finalized")

        for pending_key in sorted(tuple(self.pending_by_memory_id)):
            pending = self.pending_by_memory_id[pending_key]
            state = MemoryState(**pending["state"])
            reward = self.reward_config["context_cost_coefficient"] * float(
                pending["context_cost"]
            )
            policy_before = self.policy.runtime_state()
            losses = self.policy.credit_delayed_reward(
                str(pending["credit_id"]),
                reward,
                state,
                done=True,
                split="development",
                train_updates=1,
            )
            action = MemoryAction(pending["action"])
            transition = PolicyTransition(
                transition_id=self._uuid("stream-final-credit|" + pending_key),
                graph_id=pending["work_graph_id"],
                candidate_node_id=pending["candidate_node_id"],
                org_id=pending["org_id"],
                namespace=self.namespace,
                owner_user_id=pending["owner_user_id"],
                action={
                    MemoryAction.FORGET: PolicyAction.FORGET,
                    MemoryAction.MOVE_TO_EPISODIC: PolicyAction.MOVE_TO_EPISODIC,
                    MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE:
                        PolicyAction.MOVE_TO_SEMANTIC_CANDIDATE,
                }[action],
                actor=PolicyActor.DOUBLE_DQN,
                target_graph_kind={
                    MemoryAction.FORGET: None,
                    MemoryAction.MOVE_TO_EPISODIC: GraphKind.USER_EPISODIC,
                    MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE: GraphKind.USER_SEMANTIC,
                }[action],
                state_features_hash=canonical_hash(asdict(state)),
                reward=reward,
                delayed_credit_ref=str(pending["credit_id"]),
                event_time=str(pending.get("source_event_time") or self.clock()),
            )
            try:
                self.persistence.persist_bundle(
                    AccessContext(pending["org_id"], pending["owner_user_id"]),
                    LifecycleAppendBundle(
                        operation_id=self._uuid(
                            "lifecycle-operation|finalize|" + pending_key
                        ),
                        operation_scope={
                            "kind": "FINALIZE",
                            "task_id": str(pending["source_task_id"]),
                            "active_node_ids": [],
                        },
                        transitions=(transition,),
                    ),
                )
            except BaseException:
                self.policy.restore_runtime_state(policy_before)
                raise
            self.credit_ledger.append({
                "memory_id": pending_key,
                "source_task_id": pending["source_task_id"],
                "target_task_id": None,
                "target_resolved": None,
                "reward": reward,
                "negative_transfer": False,
                "no_reuse_finalization": True,
                "losses": losses,
            })
            del self.pending_by_memory_id[pending_key]

        if self.pending_by_memory_id or self.policy.pending_credit_count:
            raise LifecycleError("development pending credit did not reach zero")
        checkpoint = self.policy.freeze_checkpoint()
        return {"payload": dict(checkpoint.payload), "digest": checkpoint.digest}

    def freeze_development_checkpoint(self) -> FrozenCheckpoint:
        if self.evaluation or self.split == "heldout":
            raise LifecycleError("only a development lifecycle can be frozen")
        if self.pending_by_memory_id or self.policy.pending_credit_count:
            raise LifecycleError("cannot freeze with unresolved delayed credit")
        return self.policy.freeze_checkpoint()


def production_dqn_lifecycle_factory(
    identity_resolver: ProductionIdentityResolver,
    *,
    policy_manifest: Mapping[str, Any],
    expected_policy_manifest_hash: str,
) -> Callable[..., PostgresDQNExperienceLifecycle]:
    """Bind the complete committed M2 contract to ``open_benchmark_arm``."""

    config, contract = _parse_policy_manifest(
        policy_manifest, expected_policy_manifest_hash
    )

    def factory(*, policy, persistence, namespace, split, evaluation, embedder, **_):
        selected = policy
        if split in {"development", "credential_free_replay"} and not evaluation:
            if selected is not None:
                raise LifecycleError("development cannot start from a frozen selected checkpoint")
            selected = DoubleDQNMemoryPolicy(config)
        elif split == "heldout" and evaluation:
            if selected is None or not selected.frozen:
                raise LifecycleError("heldout requires the exact frozen selected checkpoint")
            if selected.config != config:
                raise LifecycleError("heldout checkpoint config differs from M2 policy manifest")
        else:
            raise LifecycleError("unsupported M2 policy/split/evaluation boundary")
        return PostgresDQNExperienceLifecycle(
            selected,
            persistence,
            namespace=namespace,
            split=split,
            evaluation=evaluation,
            identity_resolver=identity_resolver,
            feature_encoder=embedder,
            policy_manifest_hash=contract["manifest_hash"],
            encoder_lock=contract["encoder"],
            reward_config=contract["reward"],
            graph_topology_config=contract["graph_topology"],
            state_feature_config=contract["state_features"],
            retrieval_config=contract["retrieval"],
            capacity_config=contract["capacities"],
            development_resume_cursor=contract["development_resume_cursor"],
        )

    factory.configuration_hash = contract["manifest_hash"]  # type: ignore[attr-defined]
    factory.policy_manifest_hash = contract["manifest_hash"]  # type: ignore[attr-defined]
    return factory


__all__ = [
    "PostgresDQNExperienceLifecycle",
    "ProductionIdentityResolver",
    "production_dqn_lifecycle_factory",
]
