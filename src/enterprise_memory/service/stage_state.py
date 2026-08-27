"""R22 §4 — agent stage state machine (COMPREHEND→REPRODUCE→LOCALIZE→EDIT→VERIFY) + transition legality.

Deterministic, no model calls. EDIT memory may not be searched without LOCALIZE evidence; VERIFY memory may not be
searched without a patch; stages cannot be selected arbitrarily by the client; moving backward may not delete
accumulated evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..experience.stage_schema import Stage

ORDER = [Stage.COMPREHEND, Stage.REPRODUCE, Stage.LOCALIZE, Stage.EDIT, Stage.VERIFY]

# what evidence must exist to ENTER a stage (gate on the observation accumulated so far)
_ENTRY = {
    Stage.REPRODUCE: "issue_contract",
    Stage.LOCALIZE: "reproduction",
    Stage.EDIT: "candidate_locations",
    Stage.VERIFY: "applied_patch",
}


class StageTransitionError(Exception):
    pass


@dataclass
class StageObservation:
    issue_contract: str = ""
    reproduction: str = ""
    candidate_locations: List[str] = field(default_factory=list)
    applied_patch: str = ""
    grader_result: str = ""
    failing_tests: List[str] = field(default_factory=list)
    stack_trace: str = ""
    candidate_symbols: List[str] = field(default_factory=list)
    hypothesis: str = ""
    rejected_hypotheses: List[str] = field(default_factory=list)

    def has(self, key: str) -> bool:
        v = getattr(self, key, None)
        return bool(v)


@dataclass
class StageState:
    stage: Stage = Stage.COMPREHEND
    obs: StageObservation = field(default_factory=StageObservation)
    audit: List[dict] = field(default_factory=list)
    search_calls: Dict[str, int] = field(default_factory=dict)
    browse_calls: int = 0

    def _record(self, event: str, **kw):
        self.audit.append({"event": event, "stage": self.stage.value, **kw})

    def advance(self, to: Stage) -> None:
        i, j = ORDER.index(self.stage), ORDER.index(to)
        if j == i:
            return
        if j > i:
            # forward: every intervening entry gate must be satisfied
            for st in ORDER[i + 1:j + 1]:
                need = _ENTRY.get(st)
                if need and not self.obs.has(need):
                    raise StageTransitionError("cannot enter %s without %s" % (st.value, need))
        else:
            # backward is allowed but must not delete accumulated evidence
            self._record("stage_backward", to=to.value)
        self.stage = to
        self._record("stage_enter", to=to.value)

    def can_search(self, stage: Stage) -> bool:
        # EDIT memory needs LOCALIZE evidence; VERIFY memory needs a patch (§4 / §10)
        if stage == Stage.EDIT and not self.obs.has("candidate_locations"):
            return False
        if stage == Stage.VERIFY and not self.obs.has("applied_patch"):
            return False
        return True
