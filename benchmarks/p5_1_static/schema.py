"""Frozen static coding-instrument schema (P5.1 §6). A Family binds a single reusable local CONVENTION (a
domain-specific integer constant that differs from the public/default prior) across three disjoint tasks:

  own_source   solved on behalf of the eventual target user (feeds the M1 private arm)
  cross_source owned by a DIFFERENT source user (feeds the M2/M3/M4 shared arms)
  target       assigned to the target user

All three share the technique but use different names/inputs/constants/files/tests. Public tests are
incomplete (they pin only a case that does NOT reveal the convention); hidden tests enforce the convention.
No target answer is ever placed in memory; target output values differ from source output values.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List

ROLES = ("own_source", "cross_source", "target")


@dataclass(frozen=True)
class Task:
    task_id: str
    family_id: str
    domain: str
    role: str                       # own_source | cross_source | target
    repo_fixture_id: str
    target_path: str
    editable_paths: List[str]
    target_symbol: str
    exact_signature: str
    public_test_path: str
    public_test: str                # ships in the snapshot (incomplete)
    hidden_test: str                # NEVER ships to the model; used only for grading
    src_stub: str                   # ships in the snapshot (the function to complete)
    world_constant: int             # the convention value C (family-shared)
    prior_default: int              # the common default D the un-memorised model tends to guess
    formula_label: str
    public_input: int
    hidden_input: int
    base: int
    gold_body: str                  # the correct function body (uses C) — audit only, NEVER in any prompt
    hidden_expected: int            # grading target for the hidden input (uses C + this task's base)

    def snapshot(self) -> Dict[str, str]:
        return {self.target_path: self.src_stub, self.public_test_path: self.public_test}


@dataclass(frozen=True)
class Family:
    family_id: str
    domain: str
    world_constant: int
    prior_default: int
    technique_note: str             # the safe, reusable convention text placed in memory (contains C, not the
                                    # target's answer)
    tasks: Dict[str, Task] = field(default_factory=dict)

    @property
    def own_source(self) -> Task:
        return self.tasks["own_source"]

    @property
    def cross_source(self) -> Task:
        return self.tasks["cross_source"]

    @property
    def target(self) -> Task:
        return self.tasks["target"]
