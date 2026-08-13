"""Immutable server-side experiment arms (P5.1 §8). The client never selects an arm; the arm is assigned
from the frozen manifest and stored on the server-owned task policy. Each arm maps to a retrieval policy
(scopes / max injected / oracle) that drives the worker, and a memory form that is seeded server-side. The
backend never receives a human-readable arm label."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Arm:
    code: str
    name: str
    retrieval_policy: dict
    memory_form: str          # none | private | shared_ungoverned | shared_governed | negative_*
    source_role: str          # own_source | cross_source | (unused for M0)
    oracle: bool = False
    safety: bool = False


# primary efficacy arms
M0 = Arm("M0", "NO_MEMORY", {"scopes": [], "max_injected": 0}, "none", "target")
M1 = Arm("M1", "PRIVATE_ONLY", {"scopes": ["private"], "max_injected": 1}, "private", "own_source")
M2 = Arm("M2", "CROSS_USER_SHARED_UNGOVERNED", {"scopes": ["shared"], "max_injected": 1},
         "shared_ungoverned", "cross_source")
M3 = Arm("M3", "CROSS_USER_SHARED_GOVERNED", {"scopes": ["shared"], "max_injected": 1},
         "shared_governed", "cross_source")
M4 = Arm("M4", "ORACLE_GOVERNED", {"scopes": ["shared"], "max_injected": 1, "oracle": True},
         "shared_governed", "cross_source", oracle=True)

# safety arms (evaluated separately)
S1 = Arm("S1", "IRRELEVANT_GOVERNED", {"scopes": ["shared"], "max_injected": 1},
         "negative_irrelevant", "cross_source", safety=True)
S2 = Arm("S2", "EXPIRED_GOVERNED", {"scopes": ["shared"], "max_injected": 1},
         "negative_expired", "cross_source", safety=True)
S3 = Arm("S3", "OUT_OF_SCOPE_GOVERNED", {"scopes": ["shared"], "max_injected": 1},
         "negative_out_of_scope", "cross_source", safety=True)
S4 = Arm("S4", "WRONG_REUSABLE_PATTERN", {"scopes": ["shared"], "max_injected": 1},
         "negative_wrong_pattern", "cross_source", safety=True)

PRIMARY = [M0, M1, M2, M3, M4]
SAFETY = [S1, S2, S3, S4]
ALL = PRIMARY + SAFETY
BY_CODE = {a.code: a for a in ALL}
