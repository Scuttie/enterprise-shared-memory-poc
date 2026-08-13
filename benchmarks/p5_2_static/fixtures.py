"""P5.2 snapshot + memory-fact rendering (§4/§5). The snapshot ships the stub + core-only public test (the
context_inferable stub also carries a weak clue). The memory fact is the target-free reusable convention (the
edge rule + the edge multiplier K), never the target's edge value base*K."""
from __future__ import annotations


def render_snapshot(task):
    return task.snapshot()


def memory_fact(family, source_role="own_source"):
    return {"domain": family.domain, "technique": family.technique_note,
            "edge_multiplier": family.edge_multiplier, "edge_name": family.own_source.edge_name,
            "applies_when": ["completing a %s function with an edge-case rule" % family.domain],
            "does_not_apply_when": ["a different codebase / edge convention"], "tag": family.tag}
