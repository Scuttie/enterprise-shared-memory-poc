"""Production patch utilities (no dependency on benchmarks/research)."""
from .applicator import apply_unified_diff, validate_bounded_edit, PatchError, LINE_BUDGET  # noqa: F401
