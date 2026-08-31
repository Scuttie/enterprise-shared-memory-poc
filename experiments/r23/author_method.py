"""R23-R0 — CLEAN-ROOM author-method (arXiv:2602.21611). NOT the author's code (unreleased). Implements the
described behavior: memory triple m=(z,d,e), category hard-filter + forced semantic Top-1, per-subtask extraction,
streaming. Prompts here are clean-room, written from the paper's described behavior (not verbatim author prompts);
deviations are in artifacts/r23/reproduction_deviations.json. Credential-free (no model call in this module — the
reader is injected)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

CATEGORIES = ["ANALYZE", "REPRODUCE", "EDIT", "VERIFY"]


@dataclass
class MemoryEntry:
    z: str                      # category
    d: dict                     # description = {objective, keywords}
    e: str                      # abstracted experience (success pattern | failure-avoidance)
    source_task_id: str
    kind: str = "success"       # success | failure


def retrieve(query_z: str, query_d: dict, store: List[MemoryEntry], embed: Callable[[dict], list]) -> Optional[MemoryEntry]:
    """Category hard-filter -> forced semantic Top-1 (no threshold, no abstention) — exactly the author rule."""
    import math
    cands = [m for m in store if m.z == query_z]
    if not cands:
        return None
    q = embed(query_d)

    def cos(a, b):
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(x * x for x in b)) or 1.0
        return sum(x * y for x, y in zip(a, b)) / (na * nb)

    return max(cands, key=lambda m: cos(q, embed(m.d)))


# Reproduction arms (map 1:1 to A's ablations); see artifacts/r23/author_method_spec.json.
ARMS = {
    "AR0": {"name": "VANILLA", "memory": False, "structured_transitions": False},
    "AR1": {"name": "STRUCTURED_ONLY", "memory": False, "structured_transitions": True},
    "AR2": {"name": "INSTANCE_MEMORY", "memory": True, "unit": "whole_task", "query": "whole_task"},
    "AR3": {"name": "AUTHOR_SUBTASK_MEMORY", "memory": True, "unit": "subtask", "category_filter": True, "topk": 1},
    "AR4": {"name": "NO_CATEGORY_FILTER", "memory": True, "unit": "subtask", "category_filter": False, "topk": 1},
    "AR5": {"name": "RAW_SUBTASK_TRAJECTORY", "memory": True, "unit": "subtask", "experience": "raw_bounded_trajectory"},
}
REPRO_ESTIMANDS = {"R-Q1": ("AR3", "AR0"), "R-Q2": ("AR3", "AR2"), "R-Q3": ("AR3", "AR1")}


@dataclass
class StreamingState:
    """Empty at run start; a task's experience is added only AFTER it finishes; a task never reuses its own memory."""
    store: List[MemoryEntry] = field(default_factory=list)
    completed: set = field(default_factory=set)

    def visible_for(self, task_id: str) -> List[MemoryEntry]:
        return [m for m in self.store if m.source_task_id != task_id and m.source_task_id in self.completed]

    def commit(self, task_id: str, entries: List[MemoryEntry]):
        assert task_id not in self.completed, "task already committed (no re-commit)"
        self.completed.add(task_id)
        self.store.extend(entries)
