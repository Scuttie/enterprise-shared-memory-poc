"""R23-R0 clean-room reproduction of the coarse author method.

This module implements only the paper-described category/subtask memory triple
``m=(z,d,e)``. It deliberately does not import the R23 proposed-method schema:
R23-X graph/atom construction belongs to later A0/G0/F1 gates and its outputs
must never be pooled with this reproduction track.

The author implementation and verbatim author prompts are unavailable. Every
prompt below is therefore an independently written, frozen clean-room contract.
The solver itself is injected by :mod:`experiments.r23.r0_runtime`; importing
this module performs no network, model, grader, or Docker call.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable, List, Mapping, Optional, Sequence

CATEGORIES = ("ANALYZE", "REPRODUCE", "EDIT", "VERIFY")
WHOLE_TASK = "WHOLE_TASK"
TERMINAL = "COMPLETE"

# Clean-room prompts. These are not represented as author prompt text.
STRUCTURED_CONTROL_PROMPT = """R23 clean-room category controller:
Work only on the current coarse category supplied in r23_control.current_category.
Return shell/tool work through the pinned Mini-SWE-Agent tool interface. When the
current category is complete, report exactly one allowed transition signal. Do
not create graph nodes, semantic atoms, dependencies, or proposed-method fields.
"""

MEMORY_INJECTION_PROMPT = """A prior completed task produced the following bounded
coarse experience. Treat it as fallible process advice, never as target evidence
or an answer. Ignore it when it conflicts with the current repository state:
{experience}
"""

SUBTASK_EXTRACTION_PROMPT = """Independently summarize this completed coarse
category trajectory as one reusable process experience. If the local outcome is
SUCCESS, state a reusable success pattern. Otherwise state a failure-avoidance
lesson. Return only a JSON object with keys evaluation and experience. Do not
emit graph, atom, dependency, patch, test-oracle, or target-answer fields.
"""

INSTANCE_EXTRACTION_PROMPT = """Independently summarize this completed task as one
reusable whole-task process experience. If the outcome is SUCCESS, state a
reusable success pattern. Otherwise state a failure-avoidance lesson. Return
only a JSON object with keys evaluation and experience. Do not reproduce a patch,
test oracle, target answer, graph, atom, or dependency structure.
"""

RAW_TRAJECTORY_POLICY = """For the raw-trajectory ablation, retain a deterministic
bounded rendering of the local coarse-category trajectory after the extractor has
classified SUCCESS versus FAILURE. The same injection token cap applies as in
the abstract-experience arms.
"""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TaskInput:
    """Target-visible task input. Gold patches and grader fields are absent by construction."""

    task_id: str
    repository: str
    problem_statement: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "TaskInput":
        allowed = {"task_id", "instance_id", "repository", "repo", "problem_statement"}
        answer_fields = {"patch", "gold_patch", "test_patch", "fail_to_pass", "pass_to_pass", "resolved"}
        present_answer_fields = answer_fields.intersection(str(key).lower() for key in value)
        if present_answer_fields:
            raise ValueError("R0 task input contains prohibited answer fields: %s" % sorted(present_answer_fields))
        unknown = set(value) - allowed
        if unknown:
            raise ValueError("R0 task input contains unsupported fields: %s" % sorted(unknown))
        task_id = str(value.get("task_id") or value.get("instance_id") or "")
        repository = str(value.get("repository") or value.get("repo") or "")
        problem = str(value.get("problem_statement") or "")
        if not task_id or not repository or not problem:
            raise ValueError("task_id/instance_id, repository/repo, and problem_statement are required")
        return cls(task_id=task_id, repository=repository, problem_statement=problem)


@dataclass(frozen=True)
class SubtaskIntent:
    z: str
    objective: str
    keywords: tuple[str, ...] = ()

    @property
    def d(self) -> dict:
        return {"objective": self.objective, "keywords": list(self.keywords)}


@dataclass
class MemoryEntry:
    """The complete R0 memory schema: coarse ``m=(z,d,e)`` plus provenance labels."""

    z: str
    d: dict
    e: str
    source_task_id: str
    kind: str = "success"

    def validate(self) -> "MemoryEntry":
        if self.z not in (*CATEGORIES, WHOLE_TASK):
            raise ValueError("invalid coarse category %r" % self.z)
        if set(self.d) != {"objective", "keywords"}:
            raise ValueError("description d must contain exactly objective and keywords")
        if not isinstance(self.d["objective"], str) or not isinstance(self.d["keywords"], list):
            raise ValueError("invalid description d types")
        if not self.e.strip() or not self.source_task_id:
            raise ValueError("experience and source_task_id are required")
        if self.kind not in {"success", "failure"}:
            raise ValueError("kind must be success or failure")
        _reject_proposed_method_fields(asdict(self))
        return self

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "MemoryEntry":
        if set(value) != {"z", "d", "e", "source_task_id", "kind"}:
            raise ValueError("unexpected coarse memory fields")
        return cls(
            z=str(value["z"]),
            d=dict(value["d"]),
            e=str(value["e"]),
            source_task_id=str(value["source_task_id"]),
            kind=str(value["kind"]),
        ).validate()


@dataclass(frozen=True)
class TrajectoryEvent:
    category: str
    content: str
    actions: tuple[dict, ...]
    transition_signal: str
    local_outcome: str
    subtask_complete: bool
    task_complete: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _reject_proposed_method_fields(value: object) -> None:
    """Fail closed if a coarse R0 payload acquires R23-X fields."""

    banned_keys = {
        "atom_id",
        "node_id",
        "predecessor_atom_ids",
        "predecessors",
        "graph_hash",
        "operation_arguments",
        "evidence_refs",
        "abstraction_confidence",
    }

    def walk(item: object) -> None:
        if isinstance(item, Mapping):
            keys = {str(key).lower() for key in item}
            overlap = keys.intersection(banned_keys)
            if overlap:
                raise ValueError("proposed-method fields prohibited in R0: %s" % sorted(overlap))
            for child in item.values():
                walk(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                walk(child)

    walk(value)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError("embedding dimensions differ")
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def retrieve(
    query_z: str,
    query_d: dict,
    store: List[MemoryEntry],
    embed: Callable[[dict], list],
) -> Optional[MemoryEntry]:
    """Paper-described category hard-filter followed by forced semantic Top-1."""

    return _retrieve(query_z, query_d, store, embed, category_filter=True)


def _retrieve(
    query_z: str,
    query_d: dict,
    store: Sequence[MemoryEntry],
    embed: Callable[[dict], Sequence[float]],
    *,
    category_filter: bool,
) -> Optional[MemoryEntry]:
    candidates = [entry.validate() for entry in store if not category_filter or entry.z == query_z]
    if not candidates:
        return None
    query_vector = embed(query_d)
    scored = [
        (_cosine(query_vector, embed(entry.d)), entry.source_task_id, content_hash(asdict(entry)), entry)
        for entry in candidates
    ]
    # A deterministic secondary ordering makes equal-cosine replays byte-stable.
    return sorted(scored, key=lambda item: (-item[0], item[1], item[2]))[0][3]


# R23-R reproduction arms only. ``unit=coarse_subtask`` is intentionally not the
# proposed semantic-atom/DAG representation.
ARMS = {
    "AR0": {
        "name": "VANILLA",
        "memory": False,
        "structured_transitions": False,
        "unit": "none",
        "extraction_scope": "none",
        "extraction_call_cap": 0,
    },
    "AR1": {
        "name": "STRUCTURED_ONLY",
        "memory": False,
        "structured_transitions": True,
        "unit": "coarse_subtask",
        "extraction_scope": "none",
        "extraction_call_cap": 0,
    },
    "AR2": {
        "name": "INSTANCE_MEMORY",
        "memory": True,
        "structured_transitions": False,
        "unit": "whole_task",
        "category_filter": True,
        "experience": "abstract",
        "extraction_scope": "whole_task",
        "extraction_call_cap": 1,
    },
    "AR3": {
        "name": "AUTHOR_COARSE_SUBTASK_MEMORY",
        "memory": True,
        "structured_transitions": True,
        "unit": "coarse_subtask",
        "category_filter": True,
        "topk": 1,
        "experience": "abstract",
        "extraction_scope": "per_subtask",
        "extraction_call_cap": 4,
    },
    "AR4": {
        "name": "NO_CATEGORY_FILTER",
        "memory": True,
        "structured_transitions": True,
        "unit": "coarse_subtask",
        "category_filter": False,
        "topk": 1,
        "experience": "abstract",
        "extraction_scope": "per_subtask",
        "extraction_call_cap": 4,
    },
    "AR5": {
        "name": "RAW_COARSE_SUBTASK_TRAJECTORY",
        "memory": True,
        "structured_transitions": True,
        "unit": "coarse_subtask",
        "category_filter": True,
        "topk": 1,
        "experience": "raw_bounded_trajectory",
        "extraction_scope": "per_subtask",
        "extraction_call_cap": 4,
    },
}
REPRO_ESTIMANDS = {"R-Q1": ("AR3", "AR0"), "R-Q2": ("AR3", "AR2"), "R-Q3": ("AR3", "AR1")}


def arm_config(arm: str) -> dict:
    if arm not in ARMS:
        raise ValueError("unknown R0 arm %r" % arm)
    return dict(ARMS[arm])


def retrieve_for_arm(
    arm: str,
    intent: SubtaskIntent,
    store: Sequence[MemoryEntry],
    embed: Callable[[dict], Sequence[float]],
) -> Optional[MemoryEntry]:
    config = arm_config(arm)
    if not config["memory"]:
        return None
    return _retrieve(
        intent.z,
        intent.d,
        store,
        embed,
        category_filter=bool(config.get("category_filter", True)),
    )


TRANSITIONS = {
    "ANALYZE": {"CONTINUE": "ANALYZE", "ANALYSIS_COMPLETE": "REPRODUCE", "TASK_FAILED": TERMINAL},
    "REPRODUCE": {
        "CONTINUE": "REPRODUCE",
        "REPRODUCTION_COMPLETE": "EDIT",
        "TASK_FAILED": TERMINAL,
    },
    "EDIT": {"CONTINUE": "EDIT", "EDIT_COMPLETE": "VERIFY", "TASK_FAILED": TERMINAL},
    "VERIFY": {
        "CONTINUE": "VERIFY",
        "VERIFICATION_PASSED": TERMINAL,
        "VERIFICATION_FAILED": TERMINAL,
        "TASK_FAILED": TERMINAL,
    },
}


@dataclass
class CategoryMachine:
    current: str = "ANALYZE"
    finished: bool = False
    signals: list[str] = field(default_factory=list)

    def allowed_signals(self) -> tuple[str, ...]:
        if self.finished:
            return ()
        return tuple(TRANSITIONS[self.current])

    def apply(self, signal: str) -> str:
        if self.finished:
            raise ValueError("category machine already complete")
        if signal not in TRANSITIONS[self.current]:
            raise ValueError("invalid transition %s from %s" % (signal, self.current))
        self.signals.append(signal)
        target = TRANSITIONS[self.current][signal]
        if target == TERMINAL:
            self.finished = True
        else:
            self.current = target
        return target


def _keywords(text: str, limit: int = 12) -> tuple[str, ...]:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.-]{2,}", text.lower())
    stop = {"the", "and", "for", "with", "from", "that", "this", "into", "when", "then"}
    return tuple(dict.fromkeys(token for token in tokens if token not in stop))[:limit]


def derive_intent(task: TaskInput, category: str) -> SubtaskIntent:
    if category == WHOLE_TASK:
        objective = "Solve the target issue and produce a valid source-only patch."
    else:
        objectives = {
            "ANALYZE": "Locate the relevant code and explain the target-visible failure mechanism.",
            "REPRODUCE": "Reproduce or otherwise establish target-visible failing behavior.",
            "EDIT": "Implement the smallest general source change that addresses the issue.",
            "VERIFY": "Run target-visible checks and assess whether the change resolves the issue.",
        }
        if category not in objectives:
            raise ValueError("invalid category %r" % category)
        objective = objectives[category]
    return SubtaskIntent(category, objective, _keywords(task.problem_statement))


def bounded_text(text: str, token_cap: int) -> str:
    """Deterministic whitespace-token bound used for equal R0 memory injection caps."""

    if token_cap <= 0:
        return ""
    tokens = text.split()
    if len(tokens) <= token_cap:
        return text.strip()
    return " ".join(tokens[:token_cap]) + " [TRUNCATED_BY_R0_TOKEN_CAP]"


def render_raw_trajectory(events: Iterable[TrajectoryEvent], token_cap: int) -> str:
    rows = []
    for event in events:
        rows.append(
            canonical_json(
                {
                    "category": event.category,
                    "content": event.content,
                    "actions": list(event.actions),
                    "transition_signal": event.transition_signal,
                    "local_outcome": event.local_outcome,
                }
            )
        )
    return bounded_text("\n".join(rows), token_cap)


def build_solve_payload(
    *,
    scaffold: Mapping[str, object],
    arm: str,
    task: TaskInput,
    intent: SubtaskIntent,
    history: Sequence[TrajectoryEvent],
    memory: Optional[MemoryEntry],
    allowed_signals: Sequence[str],
    max_output_tokens: int,
    injection_token_cap: int,
) -> dict:
    config = arm_config(arm)
    if memory is not None:
        memory.validate()
        if memory.source_task_id == task.task_id:
            raise ValueError("online no-self-memory violation")
        injected = {
            "source_task_id": memory.source_task_id,
            "category": memory.z,
            "kind": memory.kind,
            "text": MEMORY_INJECTION_PROMPT.format(
                experience=bounded_text(memory.e, injection_token_cap)
            ),
            "token_cap": injection_token_cap,
        }
    else:
        injected = None

    if config["structured_transitions"]:
        control = {
            "prompt": STRUCTURED_CONTROL_PROMPT,
            "current_category": intent.z,
            "description": intent.d,
            "allowed_transition_signals": list(allowed_signals),
            "memory": injected,
        }
    elif config["memory"]:
        control = {
            "prompt": "Use only the bounded prior whole-task process advice when relevant.",
            "current_category": WHOLE_TASK,
            "description": intent.d,
            "allowed_transition_signals": ["CONTINUE", "TASK_COMPLETE", "TASK_FAILED"],
            "memory": injected,
        }
    else:
        control = None  # AR0 leaves the pinned scaffold prompt unextended.

    payload = {
        "schema_version": "r23/r0/solve_payload/1.0.0",
        "track": "R23-R",
        "arm": arm,
        "scaffold": dict(scaffold),
        "message_render_contract": {
            "system_template": {
                "source": "%s#agent.system_template" % scaffold["config_path"],
                "sha256": scaffold["system_prompt_sha256"],
                "render": "UNCHANGED",
            },
            "instance_template": {
                "source": "%s#agent.instance_template" % scaffold["config_path"],
                "sha256": scaffold["instance_prompt_sha256"],
                "variables": {"task": task.problem_statement},
            },
            "r23_control_injection": "NONE" if control is None else "APPEND_AS_USER_CONTROL_MESSAGE",
            "tool_schema_sha256": scaffold["tool_schema_canonical_sha256"],
            "tool_call_parser_source_sha256": scaffold["tool_call_parser_source_sha256"],
            "patch_parser_source_sha256": scaffold["patch_parser_source_sha256"],
        },
        "task": asdict(task),
        "history": [event.to_dict() for event in history],
        "r23_control": control,
        "generation": {"temperature": 0, "max_output_tokens": max_output_tokens},
    }
    _reject_proposed_method_fields(payload)
    return payload


def build_extraction_payload(
    *,
    arm: str,
    task: TaskInput,
    intent: SubtaskIntent,
    events: Sequence[TrajectoryEvent],
    local_outcome: str,
    max_output_tokens: int,
) -> dict:
    config = arm_config(arm)
    if config["extraction_scope"] == "none":
        raise ValueError("arm %s has no extraction call" % arm)
    outcome = local_outcome.upper()
    if outcome not in {"SUCCESS", "FAILURE"}:
        raise ValueError("local_outcome must be SUCCESS or FAILURE")
    prompt = INSTANCE_EXTRACTION_PROMPT if config["unit"] == "whole_task" else SUBTASK_EXTRACTION_PROMPT
    payload = {
        "schema_version": "r23/r0/extraction_payload/1.0.0",
        "track": "R23-R",
        "arm": arm,
        "task": {"task_id": task.task_id, "repository": task.repository},
        "intent": {"z": intent.z, "d": intent.d},
        "local_outcome": outcome,
        "prompt": prompt,
        "trajectory": [event.to_dict() for event in events],
        "generation": {"temperature": 0, "max_output_tokens": max_output_tokens},
    }
    _reject_proposed_method_fields(payload)
    return payload


def parse_extracted_memory(
    *,
    arm: str,
    task: TaskInput,
    intent: SubtaskIntent,
    events: Sequence[TrajectoryEvent],
    local_outcome: str,
    extracted: Mapping[str, object],
    injection_token_cap: int,
) -> MemoryEntry:
    if set(extracted) != {"evaluation", "experience"}:
        raise ValueError("extractor output must contain exactly evaluation and experience")
    _reject_proposed_method_fields(extracted)
    outcome = local_outcome.upper()
    if str(extracted["evaluation"]).upper() != outcome:
        raise ValueError("extractor evaluation disagrees with observed local outcome")
    config = arm_config(arm)
    if config.get("experience") == "raw_bounded_trajectory":
        experience = render_raw_trajectory(events, injection_token_cap)
    else:
        experience = bounded_text(str(extracted["experience"]), injection_token_cap)
    return MemoryEntry(
        z=intent.z,
        d=intent.d,
        e=experience,
        source_task_id=task.task_id,
        kind="success" if outcome == "SUCCESS" else "failure",
    ).validate()


@dataclass
class StreamingState:
    """Prefix-only online memory; a target's buffered entries are committed after target completion."""

    store: List[MemoryEntry] = field(default_factory=list)
    completed: set[str] = field(default_factory=set)

    def visible_for(self, task_id: str) -> List[MemoryEntry]:
        visible = [
            entry
            for entry in self.store
            if entry.source_task_id != task_id and entry.source_task_id in self.completed
        ]
        if any(entry.source_task_id == task_id for entry in visible):
            raise AssertionError("online no-self-memory violation")
        return visible

    def commit(self, task_id: str, entries: List[MemoryEntry]) -> None:
        if task_id in self.completed:
            raise ValueError("task already committed (no re-commit)")
        if any(entry.source_task_id != task_id for entry in entries):
            raise ValueError("cannot commit another task's memory")
        for entry in entries:
            entry.validate()
        self.store.extend(entries)
        self.completed.add(task_id)

    def to_dict(self) -> dict:
        return {
            "store": [asdict(entry) for entry in self.store],
            "completed": sorted(self.completed),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "StreamingState":
        state = cls(
            store=[MemoryEntry.from_dict(item) for item in value.get("store", [])],
            completed=set(str(item) for item in value.get("completed", [])),
        )
        if any(entry.source_task_id not in state.completed for entry in state.store):
            raise ValueError("checkpoint contains uncommitted visible memory")
        return state


PROMPT_HASHES = {
    "structured_control_prompt_sha256": text_hash(STRUCTURED_CONTROL_PROMPT),
    "memory_injection_prompt_sha256": text_hash(MEMORY_INJECTION_PROMPT),
    "subtask_extraction_prompt_sha256": text_hash(SUBTASK_EXTRACTION_PROMPT),
    "instance_extraction_prompt_sha256": text_hash(INSTANCE_EXTRACTION_PROMPT),
    "raw_trajectory_policy_sha256": text_hash(RAW_TRAJECTORY_POLICY),
}
