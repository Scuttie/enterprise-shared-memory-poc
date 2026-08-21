"""P6/R19 §8.4 — nontrivial-use accounting. The evaluation router must not get a clean safety result by
abstaining from everything; a coverage floor is predeclared on the development set and checked here."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CoverageAccountant:
    n_candidates: int = 0
    n_use: int = 0
    n_abstain: int = 0
    n_use_helpful: int = 0        # USE decisions later credited MEMORY_GAIN
    n_use_harmful: int = 0        # USE decisions later credited MEMORY_LOSS
    n_abstain_would_help: int = 0  # ABSTAIN where a counterfactual shows the memory would have helped
    reason_counts: dict = field(default_factory=dict)

    def record(self, decision) -> None:
        self.n_candidates += 1
        if decision.decision == "USE":
            self.n_use += 1
        else:
            self.n_abstain += 1
        for rc in decision.reason_codes:
            self.reason_counts[rc] = self.reason_counts.get(rc, 0) + 1

    # outcome-linked (filled by the outcome-credit stage; never before a target is graded)
    def credit(self, used: bool, outcome_class: str) -> None:
        if used and outcome_class == "MEMORY_GAIN":
            self.n_use_helpful += 1
        elif used and outcome_class == "MEMORY_LOSS":
            self.n_use_harmful += 1
        elif (not used) and outcome_class == "MEMORY_GAIN":
            self.n_abstain_would_help += 1

    @property
    def injection_coverage(self) -> float:
        return self.n_use / self.n_candidates if self.n_candidates else 0.0

    @property
    def abstention(self) -> float:
        return self.n_abstain / self.n_candidates if self.n_candidates else 0.0

    @property
    def precision_among_injections(self) -> float:
        graded = self.n_use_helpful + self.n_use_harmful
        return self.n_use_helpful / graded if graded else 0.0

    @property
    def false_use_rate(self) -> float:
        return self.n_use_harmful / self.n_use if self.n_use else 0.0

    @property
    def false_abstention_rate(self) -> float:
        return self.n_abstain_would_help / self.n_abstain if self.n_abstain else 0.0

    def meets_floor(self, coverage_floor: float) -> bool:
        return self.injection_coverage >= coverage_floor

    def summary(self) -> dict:
        return {
            "n_candidates": self.n_candidates, "n_use": self.n_use, "n_abstain": self.n_abstain,
            "injection_coverage": round(self.injection_coverage, 4), "abstention": round(self.abstention, 4),
            "precision_among_injections": round(self.precision_among_injections, 4),
            "false_use_rate": round(self.false_use_rate, 4),
            "false_abstention_rate": round(self.false_abstention_rate, 4),
            "reason_counts": dict(self.reason_counts),
        }
