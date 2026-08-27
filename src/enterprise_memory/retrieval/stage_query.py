"""R22 §5 — build a stage-scoped retrieval query from the current agent observation (deterministic)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from ..experience.stage_schema import Stage


@dataclass
class StageQuery:
    stage: Stage
    error_signature: str = ""
    stack_trace_signature: str = ""
    failing_test_signature: str = ""
    symbols: List[str] = field(default_factory=list)
    apis: List[str] = field(default_factory=list)
    contract: str = ""
    operation_type: str = ""
    attempted_actions: List[str] = field(default_factory=list)
    language: str = ""
    repository: str = ""

    def terms(self) -> List[str]:
        t = [self.error_signature, self.stack_trace_signature, self.failing_test_signature, self.contract,
             self.operation_type] + list(self.symbols) + list(self.apis)
        return [x for x in t if x]
