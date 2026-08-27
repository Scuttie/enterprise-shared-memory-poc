"""R22-P0.8.1 §8 — frozen reader-candidate order enforcement (reconcile only; no paid run).

The v2 plan freezes the candidate order deepseek-chat -> gpt-4o-mini -> gpt-4o and selects the FIRST in-band
candidate. A human must not skip directly to a later candidate: a later candidate may be selected only after every
earlier candidate has a recorded (out-of-band) decision. This module is the single enforcement point; the plan file
is the single source of truth for the order."""
from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PLAN = os.path.join(ROOT, "configs", "r22", "paid_run_plan_v2.json")
_FALLBACK_ORDER = ["deepseek-chat", "gpt-4o-mini", "gpt-4o"]


class CandidateOrderViolation(Exception):
    pass


def frozen_order():
    try:
        order = json.load(open(PLAN, encoding="utf-8")).get("reader_candidate_order")
        if order:
            return list(order)
    except Exception:
        pass
    return list(_FALLBACK_ORDER)


def next_allowed(decided):
    """The next candidate that must be attempted, given the models already decided out-of-band (any order subset)."""
    for m in frozen_order():
        if m not in set(decided or []):
            return m
    return None


def assert_not_skipping(requested, decided=None):
    """Reject selecting `requested` if any earlier frozen candidate has no recorded decision yet."""
    order = frozen_order()
    if requested not in order:
        raise CandidateOrderViolation("unknown reader candidate %r (frozen order %s)" % (requested, order))
    nxt = next_allowed(decided)
    if requested != nxt:
        raise CandidateOrderViolation(
            "candidate-order violation: cannot select %r before %r (frozen order %s; decided=%s). "
            "A later candidate is selectable only after every earlier one has a recorded decision."
            % (requested, nxt, order, sorted(set(decided or []))))
    return requested
