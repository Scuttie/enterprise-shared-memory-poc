"""Deterministic, dependency-free Double-DQN memory storage policy.

The policy has a deliberately narrow authority boundary.  Its complete action
space is ``FORGET``, ``MOVE_TO_EPISODIC`` and
``MOVE_TO_SEMANTIC_CANDIDATE``.  It cannot grant access, choose a tenant,
publish a candidate to a shared bank, or bypass a secret filter.  Those remain
deterministic service/consolidation decisions outside this module.

Training is accepted only for the development split.  Evaluation is greedy,
requires a frozen checkpoint, and performs no mutation (including RNG or
counter mutation).
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Protocol, Sequence, runtime_checkable


class MemoryAction(str, Enum):
    FORGET = "FORGET"
    MOVE_TO_EPISODIC = "MOVE_TO_EPISODIC"
    MOVE_TO_SEMANTIC_CANDIDATE = "MOVE_TO_SEMANTIC_CANDIDATE"


ACTION_ORDER = (
    MemoryAction.FORGET,
    MemoryAction.MOVE_TO_EPISODIC,
    MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE,
)


class PolicyError(RuntimeError):
    pass


class TrainingScopeError(PolicyError):
    pass


class FrozenPolicyError(PolicyError):
    pass


class ActionMaskError(PolicyError):
    pass


class CheckpointError(PolicyError):
    pass


@dataclass(frozen=True)
class ActionMask:
    """Server-computed action mask.

    The mask may encode deterministic eligibility checks, but the DQN never
    computes ACL, tenant, publication, or secret-filter eligibility itself.
    """

    forget: bool = True
    move_to_episodic: bool = True
    move_to_semantic_candidate: bool = True

    def as_tuple(self) -> tuple[bool, bool, bool]:
        out = self.values()
        if not any(out):
            raise ActionMaskError("action mask rejects every storage action")
        return out

    def values(self) -> tuple[bool, bool, bool]:
        return (self.forget, self.move_to_episodic, self.move_to_semantic_candidate)

    @classmethod
    def only(cls, *actions: MemoryAction | str) -> "ActionMask":
        allowed = {_action(a) for a in actions}
        if not allowed:
            raise ActionMaskError("at least one action must be allowed")
        return cls(
            forget=MemoryAction.FORGET in allowed,
            move_to_episodic=MemoryAction.MOVE_TO_EPISODIC in allowed,
            move_to_semantic_candidate=MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE in allowed,
        )


@dataclass(frozen=True)
class FeatureSchema:
    candidate_embedding_dim: int
    task_embedding_dim: int
    subtask_embedding_dim: int
    graph_statistics_dim: int

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    @property
    def input_dim(self) -> int:
        # Nine scalar features follow the four vector feature groups.
        return (
            self.candidate_embedding_dim
            + self.task_embedding_dim
            + self.subtask_embedding_dim
            + self.graph_statistics_dim
            + 9
        )


@dataclass(frozen=True)
class MemoryState:
    candidate_embedding: tuple[float, ...]
    task_embedding: tuple[float, ...]
    subtask_embedding: tuple[float, ...]
    verification_outcome: float
    novelty: float
    redundancy: float
    recency: float
    reuse_frequency: float
    past_gain_loss: float
    version_validity: float
    memory_occupancy: float
    graph_statistics: tuple[float, ...]
    context_cost: float

    def __post_init__(self) -> None:
        for field in ("candidate_embedding", "task_embedding", "subtask_embedding", "graph_statistics"):
            object.__setattr__(self, field, tuple(float(v) for v in getattr(self, field)))
        for field in (
            "verification_outcome",
            "novelty",
            "redundancy",
            "recency",
            "reuse_frequency",
            "past_gain_loss",
            "version_validity",
            "memory_occupancy",
            "context_cost",
        ):
            object.__setattr__(self, field, float(getattr(self, field)))

    def vector(self, schema: FeatureSchema) -> tuple[float, ...]:
        expected = {
            "candidate_embedding": schema.candidate_embedding_dim,
            "task_embedding": schema.task_embedding_dim,
            "subtask_embedding": schema.subtask_embedding_dim,
            "graph_statistics": schema.graph_statistics_dim,
        }
        for field, size in expected.items():
            if len(getattr(self, field)) != size:
                raise ValueError(f"{field} has {len(getattr(self, field))} values; expected {size}")
        out = (
            self.candidate_embedding
            + self.task_embedding
            + self.subtask_embedding
            + (
                self.verification_outcome,
                self.novelty,
                self.redundancy,
                self.recency,
                self.reuse_frequency,
                self.past_gain_loss,
                self.version_validity,
                self.memory_occupancy,
            )
            + self.graph_statistics
            + (self.context_cost,)
        )
        if len(out) != schema.input_dim:
            raise AssertionError("feature schema/vector length mismatch")
        if not all(math.isfinite(v) for v in out):
            raise ValueError("memory state contains a non-finite value")
        return out

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MemoryState":
        """Duck-typed adapter for schema/store records owned by other modules."""

        return cls(**{name: value[name] for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class PolicyDecision:
    action: MemoryAction
    q_values: tuple[float, float, float]
    allowed: tuple[bool, bool, bool]
    epsilon: float
    evaluation: bool


@runtime_checkable
class MemoryPolicy(Protocol):
    def decide(
        self,
        state: MemoryState,
        action_mask: ActionMask = ActionMask(),
        *,
        evaluation: Optional[bool] = None,
    ) -> PolicyDecision: ...


@dataclass(frozen=True)
class DoubleDQNConfig:
    feature_schema: FeatureSchema
    hidden_dim: int = 16
    replay_capacity: int = 2048
    batch_size: int = 32
    min_replay_size: int = 32
    gamma: float = 0.99
    learning_rate: float = 0.002
    target_sync_interval: int = 50
    epsilon_start: float = 1.0
    epsilon_end: float = 0.05
    epsilon_decay_steps: int = 1000
    seed: int = 23

    def __post_init__(self) -> None:
        for name in (
            "hidden_dim",
            "replay_capacity",
            "batch_size",
            "min_replay_size",
            "target_sync_interval",
            "epsilon_decay_steps",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.batch_size > self.replay_capacity:
            raise ValueError("batch_size exceeds replay_capacity")
        if self.min_replay_size > self.replay_capacity:
            raise ValueError("min_replay_size exceeds replay_capacity")
        if not 0.0 <= self.gamma <= 1.0:
            raise ValueError("gamma must be in [0,1]")
        if self.learning_rate <= 0.0:
            raise ValueError("learning_rate must be positive")
        if not 0.0 <= self.epsilon_end <= self.epsilon_start <= 1.0:
            raise ValueError("epsilon must satisfy 0 <= end <= start <= 1")

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["feature_schema"] = asdict(self.feature_schema)
        return out

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DoubleDQNConfig":
        raw = dict(value)
        raw["feature_schema"] = FeatureSchema(**raw["feature_schema"])
        return cls(**raw)


@dataclass(frozen=True)
class Transition:
    state: tuple[float, ...]
    action_index: int
    reward: float
    next_state: tuple[float, ...]
    done: bool
    next_allowed: tuple[bool, bool, bool]

    def __post_init__(self) -> None:
        if self.action_index not in range(len(ACTION_ORDER)):
            raise ValueError("invalid action index")
        if not math.isfinite(float(self.reward)):
            raise ValueError("reward must be finite")
        if not self.done and not any(self.next_allowed):
            raise ActionMaskError("non-terminal transition has no allowed next action")

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": list(self.state),
            "action_index": self.action_index,
            "reward": self.reward,
            "next_state": list(self.next_state),
            "done": self.done,
            "next_allowed": list(self.next_allowed),
        }


@dataclass(frozen=True)
class FrozenCheckpoint:
    payload: Mapping[str, Any]
    digest: str


class _ReplayBuffer:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.items: list[Transition] = []

    def add(self, transition: Transition) -> None:
        if len(self.items) == self.capacity:
            self.items.pop(0)
        self.items.append(transition)

    def sample(self, count: int, rng: random.Random) -> list[Transition]:
        n = min(count, len(self.items))
        return [self.items[i] for i in rng.sample(range(len(self.items)), n)]


class _MLP:
    """One-hidden-layer ReLU network with deterministic SGD."""

    def __init__(self, input_dim: int, hidden_dim: int, output_dim: int, rng: random.Random):
        lim1 = math.sqrt(6.0 / (input_dim + hidden_dim))
        lim2 = math.sqrt(6.0 / (hidden_dim + output_dim))
        self.w1 = [[rng.uniform(-lim1, lim1) for _ in range(input_dim)] for _ in range(hidden_dim)]
        self.b1 = [0.0] * hidden_dim
        self.w2 = [[rng.uniform(-lim2, lim2) for _ in range(hidden_dim)] for _ in range(output_dim)]
        self.b2 = [0.0] * output_dim

    def forward(self, values: Sequence[float]) -> tuple[list[float], list[float]]:
        hidden = [max(0.0, _dot(row, values) + bias) for row, bias in zip(self.w1, self.b1)]
        output = [_dot(row, hidden) + bias for row, bias in zip(self.w2, self.b2)]
        return output, hidden

    def train_selected(self, values: Sequence[float], selected: int, target: float, rate: float) -> float:
        output, hidden = self.forward(values)
        error = output[selected] - target
        selected_weights = list(self.w2[selected])
        for j, activation in enumerate(hidden):
            self.w2[selected][j] -= rate * error * activation
        self.b2[selected] -= rate * error
        for j, activation in enumerate(hidden):
            if activation <= 0.0:
                continue
            grad = error * selected_weights[j]
            for i, value in enumerate(values):
                self.w1[j][i] -= rate * grad * value
            self.b1[j] -= rate * grad
        return 0.5 * error * error

    def state(self) -> dict[str, Any]:
        # A checkpoint must not alias the live network's mutable lists.
        return {
            "w1": [list(row) for row in self.w1],
            "b1": list(self.b1),
            "w2": [list(row) for row in self.w2],
            "b2": list(self.b2),
        }

    @classmethod
    def load(cls, value: Mapping[str, Any]) -> "_MLP":
        obj = cls.__new__(cls)
        obj.w1 = [[float(x) for x in row] for row in value["w1"]]
        obj.b1 = [float(x) for x in value["b1"]]
        obj.w2 = [[float(x) for x in row] for row in value["w2"]]
        obj.b2 = [float(x) for x in value["b2"]]
        return obj

    def copy(self) -> "_MLP":
        return self.load(self.state())

    def validate(self, input_dim: int, hidden_dim: int, output_dim: int) -> None:
        if len(self.w1) != hidden_dim or any(len(row) != input_dim for row in self.w1):
            raise CheckpointError("checkpoint input/hidden network shape mismatch")
        if len(self.b1) != hidden_dim:
            raise CheckpointError("checkpoint hidden bias shape mismatch")
        if len(self.w2) != output_dim or any(len(row) != hidden_dim for row in self.w2):
            raise CheckpointError("checkpoint hidden/output network shape mismatch")
        if len(self.b2) != output_dim:
            raise CheckpointError("checkpoint output bias shape mismatch")
        flat = self.b1 + self.b2 + [v for row in self.w1 + self.w2 for v in row]
        if not all(math.isfinite(v) for v in flat):
            raise CheckpointError("checkpoint network contains non-finite weights")


@dataclass(frozen=True)
class _PendingCredit:
    state: tuple[float, ...]
    action_index: int


class DoubleDQNMemoryPolicy:
    """Pure-Python Double DQN with deterministic replay and delayed credit."""

    CHECKPOINT_SCHEMA = "trimem/double_dqn/frozen/1.0"
    RUNTIME_CHECKPOINT_SCHEMA = "trimem/double_dqn/runtime/1.0"
    DEVELOPMENT_SPLIT = "development"

    def __init__(self, config: DoubleDQNConfig):
        self.config = config
        self._rng = random.Random(config.seed)
        self._online = _MLP(config.feature_schema.input_dim, config.hidden_dim, len(ACTION_ORDER), self._rng)
        self._target = self._online.copy()
        self._replay = _ReplayBuffer(config.replay_capacity)
        self._pending: dict[str, _PendingCredit] = {}
        self._training_steps = 0
        self._selection_steps = 0
        self._frozen = False
        self._evaluation = False

    @property
    def replay_size(self) -> int:
        return len(self._replay.items)

    @property
    def pending_credit_count(self) -> int:
        return len(self._pending)

    @property
    def training_steps(self) -> int:
        return self._training_steps

    @property
    def frozen(self) -> bool:
        return self._frozen

    def q_values(self, state: MemoryState) -> tuple[float, float, float]:
        values, _ = self._online.forward(state.vector(self.config.feature_schema))
        return tuple(values)  # type: ignore[return-value]

    def decide(
        self,
        state: MemoryState,
        action_mask: ActionMask = ActionMask(),
        *,
        evaluation: Optional[bool] = None,
    ) -> PolicyDecision:
        evaluating = self._evaluation if evaluation is None else bool(evaluation)
        if evaluating and not self._frozen:
            raise FrozenPolicyError("evaluation requires a frozen checkpoint")
        if self._frozen and not evaluating:
            raise FrozenPolicyError("a frozen policy may only run in evaluation mode")
        allowed = action_mask.as_tuple()
        q_values = self.q_values(state)
        epsilon = 0.0 if evaluating else self._epsilon()
        if evaluating:
            index = _argmax_masked(q_values, allowed)
        else:
            self._selection_steps += 1
            candidates = [i for i, ok in enumerate(allowed) if ok]
            if self._rng.random() < epsilon:
                index = candidates[self._rng.randrange(len(candidates))]
            else:
                index = _argmax_masked(q_values, allowed)
        return PolicyDecision(ACTION_ORDER[index], q_values, allowed, epsilon, evaluating)

    def select_action(
        self,
        state: MemoryState,
        action_mask: ActionMask = ActionMask(),
        *,
        evaluation: Optional[bool] = None,
    ) -> MemoryAction:
        return self.decide(state, action_mask, evaluation=evaluation).action

    def queue_delayed_credit(
        self,
        credit_id: str,
        state: MemoryState,
        action: MemoryAction | str,
        action_mask: ActionMask = ActionMask(),
        *,
        split: str,
    ) -> None:
        self._ensure_training_allowed(split)
        if not credit_id or credit_id in self._pending:
            raise PolicyError("credit_id must be non-empty and unique")
        action_value = _action(action)
        index = ACTION_ORDER.index(action_value)
        if not action_mask.as_tuple()[index]:
            raise ActionMaskError(f"{action_value.value} is masked")
        self._pending[credit_id] = _PendingCredit(state.vector(self.config.feature_schema), index)

    def credit_delayed_reward(
        self,
        credit_id: str,
        reward: float,
        next_state: MemoryState,
        *,
        done: bool,
        next_action_mask: ActionMask = ActionMask(),
        split: str,
        train_updates: int = 1,
    ) -> list[float]:
        self._ensure_training_allowed(split)
        pending = self._pending.get(credit_id)
        if pending is None:
            raise PolicyError(f"unknown delayed credit id: {credit_id}")
        transition = Transition(
            pending.state,
            pending.action_index,
            float(reward),
            next_state.vector(self.config.feature_schema),
            bool(done),
            next_action_mask.values() if done else next_action_mask.as_tuple(),
        )
        self._replay.add(transition)
        del self._pending[credit_id]
        return self.train(train_updates, split=split)

    def remember(
        self,
        state: MemoryState,
        action: MemoryAction | str,
        reward: float,
        next_state: MemoryState,
        *,
        done: bool,
        next_action_mask: ActionMask = ActionMask(),
        split: str,
        train_updates: int = 1,
    ) -> list[float]:
        self._ensure_training_allowed(split)
        transition = Transition(
            state.vector(self.config.feature_schema),
            ACTION_ORDER.index(_action(action)),
            float(reward),
            next_state.vector(self.config.feature_schema),
            bool(done),
            next_action_mask.values() if done else next_action_mask.as_tuple(),
        )
        self._replay.add(transition)
        return self.train(train_updates, split=split)

    def warm_start(
        self,
        examples: Iterable[tuple[MemoryState, MemoryAction | str, float, MemoryState, bool, ActionMask]],
        *,
        split: str,
        train_updates: int,
    ) -> list[float]:
        """Load deterministic heuristic demonstrations, then train on development only."""

        self._ensure_training_allowed(split)
        for state, action, reward, next_state, done, mask in examples:
            self._replay.add(
                Transition(
                    state.vector(self.config.feature_schema),
                    ACTION_ORDER.index(_action(action)),
                    float(reward),
                    next_state.vector(self.config.feature_schema),
                    bool(done),
                    mask.values() if done else mask.as_tuple(),
                )
            )
        return self.train(train_updates, split=split)

    def train(self, updates: int = 1, *, split: str) -> list[float]:
        self._ensure_training_allowed(split)
        if updates < 0:
            raise ValueError("updates cannot be negative")
        losses: list[float] = []
        for _ in range(updates):
            if len(self._replay.items) < self.config.min_replay_size:
                break
            batch = self._replay.sample(self.config.batch_size, self._rng)
            batch_loss = 0.0
            for transition in batch:
                target = transition.reward
                if not transition.done:
                    online_next, _ = self._online.forward(transition.next_state)
                    best = _argmax_masked(online_next, transition.next_allowed)
                    target_next, _ = self._target.forward(transition.next_state)
                    target += self.config.gamma * target_next[best]
                batch_loss += self._online.train_selected(
                    transition.state,
                    transition.action_index,
                    target,
                    self.config.learning_rate,
                )
            self._training_steps += 1
            losses.append(batch_loss / len(batch))
            if self._training_steps % self.config.target_sync_interval == 0:
                self._target = self._online.copy()
        return losses

    def heuristic_action(self, state: MemoryState, action_mask: ActionMask = ActionMask()) -> MemoryAction:
        """Deterministic warm-start label; it is not used during frozen evaluation."""

        allowed = action_mask.as_tuple()
        preference: list[MemoryAction]
        if state.version_validity <= 0.0 or state.verification_outcome < 0.0:
            preference = [MemoryAction.FORGET, MemoryAction.MOVE_TO_EPISODIC]
        elif state.verification_outcome > 0.0 and state.novelty > state.redundancy:
            preference = [MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE, MemoryAction.MOVE_TO_EPISODIC]
        else:
            preference = [MemoryAction.MOVE_TO_EPISODIC, MemoryAction.FORGET]
        for action in preference + list(ACTION_ORDER):
            if allowed[ACTION_ORDER.index(action)]:
                return action
        raise ActionMaskError("action mask rejects every storage action")

    def freeze_checkpoint(self) -> FrozenCheckpoint:
        if self._pending:
            raise CheckpointError("cannot freeze with uncredited delayed transitions")
        self._frozen = True
        self._evaluation = True
        payload = self._frozen_payload()
        return FrozenCheckpoint(payload=payload, digest=_digest(payload))

    def runtime_state(self) -> dict[str, Any]:
        """Return complete mutable development state for exact crash/resume."""
        payload = {
            "schema": self.RUNTIME_CHECKPOINT_SCHEMA,
            "config": self.config.as_dict(),
            "online_network": self._online.state(),
            "target_network": self._target.state(),
            "replay": [item.as_dict() for item in self._replay.items],
            "pending": {
                key: {"state": list(item.state), "action_index": item.action_index}
                for key, item in sorted(self._pending.items())
            },
            "rng_state": _json_tree(self._rng.getstate()),
            "training_steps": self._training_steps,
            "selection_steps": self._selection_steps,
            "frozen": self._frozen,
            "evaluation": self._evaluation,
        }
        return {"payload": payload, "digest": _digest(payload)}

    def restore_runtime_state(self, value: Mapping[str, Any]) -> None:
        payload = value.get("payload")
        digest = value.get("digest")
        if not isinstance(payload, Mapping) or _digest(payload) != digest:
            raise CheckpointError("runtime checkpoint digest mismatch")
        if payload.get("schema") != self.RUNTIME_CHECKPOINT_SCHEMA:
            raise CheckpointError("unsupported runtime checkpoint schema")
        if DoubleDQNConfig.from_dict(payload["config"]) != self.config:
            raise CheckpointError("runtime checkpoint config mismatch")
        if bool(payload.get("frozen")) != self._frozen or bool(
            payload.get("evaluation")
        ) != self._evaluation:
            raise CheckpointError("runtime checkpoint policy mode mismatch")
        online = _MLP.load(payload["online_network"])
        target = _MLP.load(payload["target_network"])
        for network in (online, target):
            network.validate(
                self.config.feature_schema.input_dim,
                self.config.hidden_dim,
                len(ACTION_ORDER),
            )
        replay = []
        for raw in payload.get("replay", ()):
            replay.append(Transition(
                state=tuple(float(item) for item in raw["state"]),
                action_index=int(raw["action_index"]),
                reward=float(raw["reward"]),
                next_state=tuple(float(item) for item in raw["next_state"]),
                done=bool(raw["done"]),
                next_allowed=tuple(bool(item) for item in raw["next_allowed"]),
            ))
        if len(replay) > self.config.replay_capacity:
            raise CheckpointError("runtime replay exceeds configured capacity")
        pending = {}
        for key, raw in payload.get("pending", {}).items():
            if not isinstance(key, str) or not key:
                raise CheckpointError("runtime pending credit id is invalid")
            action_index = int(raw["action_index"])
            if action_index not in range(len(ACTION_ORDER)):
                raise CheckpointError("runtime pending action is invalid")
            state = tuple(float(item) for item in raw["state"])
            if len(state) != self.config.feature_schema.input_dim:
                raise CheckpointError("runtime pending state dimension mismatch")
            pending[key] = _PendingCredit(state, action_index)
        training_steps = int(payload["training_steps"])
        selection_steps = int(payload["selection_steps"])
        if training_steps < 0 or selection_steps < 0:
            raise CheckpointError("runtime counters cannot be negative")
        rng = random.Random()
        try:
            rng.setstate(_tuple_tree(payload["rng_state"]))
        except (TypeError, ValueError) as exc:
            raise CheckpointError("runtime RNG state is invalid") from exc
        self._online = online
        self._target = target
        self._replay.items = replay
        self._pending = pending
        self._training_steps = training_steps
        self._selection_steps = selection_steps
        self._rng = rng

    @classmethod
    def from_frozen_checkpoint(cls, checkpoint: FrozenCheckpoint | Mapping[str, Any]) -> "DoubleDQNMemoryPolicy":
        if isinstance(checkpoint, FrozenCheckpoint):
            payload, expected = checkpoint.payload, checkpoint.digest
        else:
            payload = checkpoint["payload"]
            expected = str(checkpoint["digest"])
        if _digest(payload) != expected:
            raise CheckpointError("frozen checkpoint digest mismatch")
        if payload.get("schema") != cls.CHECKPOINT_SCHEMA:
            raise CheckpointError("unsupported checkpoint schema")
        if payload.get("action_order") != [a.value for a in ACTION_ORDER]:
            raise CheckpointError("checkpoint action order mismatch")
        obj = cls(DoubleDQNConfig.from_dict(payload["config"]))
        obj._online = _MLP.load(payload["online_network"])
        obj._target = _MLP.load(payload["target_network"])
        for network in (obj._online, obj._target):
            network.validate(
                obj.config.feature_schema.input_dim,
                obj.config.hidden_dim,
                len(ACTION_ORDER),
            )
        obj._training_steps = int(payload["training_steps"])
        obj._selection_steps = int(payload["selection_steps"])
        obj._frozen = True
        obj._evaluation = True
        return obj

    def _frozen_payload(self) -> dict[str, Any]:
        return {
            "schema": self.CHECKPOINT_SCHEMA,
            "algorithm": "DoubleDQN",
            "action_order": [a.value for a in ACTION_ORDER],
            "authority_exclusions": [
                "access_permissions",
                "tenant_boundaries",
                "private_to_shared_publication",
                "secret_filtering",
            ],
            "config": self.config.as_dict(),
            "online_network": self._online.state(),
            "target_network": self._target.state(),
            "training_steps": self._training_steps,
            "selection_steps": self._selection_steps,
            "training_split": self.DEVELOPMENT_SPLIT,
            "evaluation_exploration": False,
            "frozen": True,
        }

    def _ensure_training_allowed(self, split: str) -> None:
        if split != self.DEVELOPMENT_SPLIT:
            raise TrainingScopeError("DoubleDQN training is development-only")
        if self._frozen or self._evaluation:
            raise FrozenPolicyError("frozen/evaluation policy cannot mutate or train")

    def _epsilon(self) -> float:
        progress = min(1.0, self._selection_steps / self.config.epsilon_decay_steps)
        return self.config.epsilon_start + progress * (self.config.epsilon_end - self.config.epsilon_start)


def _action(value: MemoryAction | str) -> MemoryAction:
    try:
        return value if isinstance(value, MemoryAction) else MemoryAction(str(value))
    except ValueError as exc:
        raise ActionMaskError(f"unknown memory action: {value}") from exc


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _argmax_masked(values: Sequence[float], allowed: Sequence[bool]) -> int:
    candidates = [i for i, ok in enumerate(allowed) if ok]
    if not candidates:
        raise ActionMaskError("action mask rejects every storage action")
    # Stable action-order tie break.
    return max(candidates, key=lambda i: (values[i], -i))


def _json_tree(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_tree(item) for item in value]
    if isinstance(value, list):
        return [_json_tree(item) for item in value]
    return value


def _tuple_tree(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_tuple_tree(item) for item in value)
    return value


def _digest(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
