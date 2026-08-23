"""P6/R19 §8 utility-aware router (clean-room, deterministic)."""
from . import reason_codes  # noqa: F401
from .reason_codes import USE_CODES, ABSTAIN_CODES, ALL_CODES  # noqa: F401
from .rule_router_v1 import (  # noqa: F401
    RuleRouterV1, TaskContext, TrajectoryState, Candidate, Policy, UtilityDecision,
    RouterLeakageError, WEIGHTS, USE_THRESHOLD, MIN_MARGIN,
)
from .metrics import CoverageAccountant  # noqa: F401
