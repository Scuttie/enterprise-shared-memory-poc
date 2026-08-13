"""Snapshot + memory-fact rendering for the frozen instrument (P5.1 §6/§7). The snapshot ships to the model
(stub + incomplete public test only); the hidden test never ships. The memory fact is the SAFE, target-free
reusable convention (contains the convention constant C, never a target answer)."""
from __future__ import annotations


def render_snapshot(task) -> dict:
    """The read-only repository snapshot the coding backend sees for `task`."""
    return task.snapshot()


def memory_fact(family, source_role: str = "own_source") -> dict:
    """The canonical source fact derived from a source task, rendered target-free. Both the private and shared
    arms are rendered from this SAME fact so arm differences are governance/rendering, not content."""
    src = family.tasks[source_role]
    return {
        "domain": family.domain,
        "technique": family.technique_note,           # contains C, not any target answer
        "formula_shape": src.formula_label,
        "convention_constant": family.world_constant,
        "applies_when": ["completing a %s function in this codebase" % family.domain],
        "does_not_apply_when": ["a different codebase/convention"],
    }
