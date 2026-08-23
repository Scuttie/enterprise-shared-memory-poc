"""P5.2 instrument schema (§4). A Family binds a reusable edge-case convention across three disjoint tasks
(own_source / cross_source / target) with a stratum (prior_aligned / context_inferable / prior_conflict)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class Task:
    task_id: str
    family_id: str
    domain: str
    role: str
    stratum: str
    repo_fixture_id: str
    target_path: str
    editable_paths: list
    target_symbol: str
    exact_signature: str
    public_test_path: str
    public_test: str            # ships (core only; does not reveal the edge)
    hidden_test: str            # never ships; core + edge case
    src_stub: str               # ships (context_inferable carries a weak clue)
    base: int
    edge_input: int
    edge_mult: int              # the convention K (family-shared)
    edge_value: int             # base * K (task-specific; NOT in memory)
    aligned: bool               # edge == natural core continuation
    gold_body: str              # audit only; never in a prompt
    core_expr: str
    edge_name: str

    def snapshot(self) -> Dict[str, str]:
        return {self.target_path: self.src_stub, self.public_test_path: self.public_test}


@dataclass(frozen=True)
class Family:
    family_id: str
    domain: str
    stratum: str
    edge_multiplier: int
    technique_note: str
    tag: str
    tasks: Dict[str, Task] = field(default_factory=dict)

    @property
    def own_source(self):
        return self.tasks["own_source"]

    @property
    def cross_source(self):
        return self.tasks["cross_source"]

    @property
    def target(self):
        return self.tasks["target"]
