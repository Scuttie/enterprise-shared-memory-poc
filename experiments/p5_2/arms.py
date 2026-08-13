"""P5.2 server-side arms (§5/§8). Every shared arm searches a competitive bank (relevant + 3 same-domain
near-miss + 4 cross-technique irrelevant) with the FROZEN abstention rule; M4 is oracle; M0 disables retrieval.
Safety arms: S1 relevant-absent (expect abstention), S2/S3 relevant-present-but-gated (expect rejection),
S4 wrong-rule adoption diagnostic."""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field

_THR = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                   "artifacts", "experiments", "p5_2", "retrieval_thresholds.json"),
                      encoding="utf-8"))
TAU_ABS, TAU_MARGIN = _THR["tau_abs"], _THR["tau_margin"]
_ABSTAIN = {"tau_abs": TAU_ABS, "tau_margin": TAU_MARGIN}


def _shared(extra=None):
    p = {"scopes": ["shared"], "max_injected": 1, "search_limit": 8, "abstain": _ABSTAIN}
    if extra:
        p.update(extra)
    return p


@dataclass(frozen=True)
class Arm:
    code: str
    name: str
    retrieval_policy: dict
    memory_form: str        # none | private | shared_ungoverned | shared_governed | relevant_absent |
                            # governed_expired | governed_out_of_scope | governed_wrong
    source_role: str
    safety: bool = False


M0 = Arm("M0", "NO_MEMORY", {"scopes": [], "max_injected": 0}, "none", "target")
M1 = Arm("M1", "PRIVATE_ONLY", {"scopes": ["private"], "max_injected": 1, "search_limit": 8},
         "private", "own_source")
M2 = Arm("M2", "CROSS_USER_SHARED_UNGOVERNED", _shared(), "shared_ungoverned", "cross_source")
M3 = Arm("M3", "CROSS_USER_SHARED_GOVERNED", _shared(), "shared_governed", "cross_source")
M4 = Arm("M4", "ORACLE_GOVERNED", {"scopes": ["shared"], "max_injected": 1, "search_limit": 8, "oracle": True},
         "shared_governed", "cross_source")   # oracle_id filled at seed time
S1 = Arm("S1", "IRRELEVANT_GOVERNED", _shared(), "relevant_absent", "cross_source", safety=True)
S2 = Arm("S2", "EXPIRED_GOVERNED", _shared(), "governed_expired", "cross_source", safety=True)
S3 = Arm("S3", "OUT_OF_SCOPE_GOVERNED", _shared(), "governed_out_of_scope", "cross_source", safety=True)
S4 = Arm("S4", "WRONG_REUSABLE_PATTERN", _shared(), "governed_wrong", "cross_source", safety=True)

PRIMARY = [M0, M1, M2, M3, M4]
SAFETY = [S1, S2, S3, S4]
ALL = PRIMARY + SAFETY
BY_CODE = {a.code: a for a in ALL}
