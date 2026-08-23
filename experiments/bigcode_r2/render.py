"""BigCode-R2 memory renderers (§7 formats F0-F4). Each renders a SOURCE fact (derived from a verified source
outcome; target-free) into one representation. Rendering happens AFTER source selection (§6.3), so the same
source ID can be rendered in any format without changing which source was chosen. Nothing target-specific is
ever included. Motivated by the R1.1 diagnostic: API_CARD / GOVERNED beat PLAIN; RAW_TRACE is weak.

A "source fact" is a dict:
  {source_task, entry_point, summary, verified_code, imports[], apis[], operations[], control_flow[], pitfall}
`verified_code` is the source user's OWN verified solve (USER_SUCCESS_BANK) or the official reference
(GOLD_VERIFIED_BANK, diagnostic only). It is a SOURCE solution — never the target's."""
from __future__ import annotations

FORMATS = ("F0_MINIMAL_HINT", "F1_PLAIN_LESSON", "F2_API_CARD", "F3_GOVERNED_COMPACT", "F4_RAW_VERIFIED_TRACE")


def _apis(fact, n=10):
    return ", ".join(sorted(fact.get("apis", []))[:n]) or "builtins"


def _libs(fact):
    return ", ".join(sorted(fact.get("imports", []))) or "standard library"


def _ops(fact):
    return ", ".join(sorted(fact.get("operations", []))) or "n/a"


def f0_minimal_hint(fact):
    return ("Reusable operation from a prior solved task: use %s (%s)."
            % (_ops(fact), _apis(fact, 5)))


def f1_plain_lesson(fact):
    return ("Lesson from a verified prior task (%s): %s. Technique: use %s via %s. Common pitfall: %s."
            % (fact["source_task"], fact.get("summary", ""), _ops(fact), _apis(fact),
               fact.get("pitfall", "handle empty / boundary inputs")))


def f2_api_card(fact):
    return ("API card (verified prior task %s)\n- libraries: %s\n- key calls: %s\n- operation: %s\n"
            "- precondition: inputs match the required signature/types\n- common misuse: %s"
            % (fact["source_task"], _libs(fact), _apis(fact), _ops(fact),
               fact.get("pitfall", "unhandled empty input / wrong return type")))


def f3_governed_compact(fact):
    return ("Governed lesson (verified prior task %s).\n"
            "applies-when: a task needing %s with %s.\n"
            "does-not-apply-when: an unrelated problem.\n"
            "action: %s using %s.\n"
            "validity: language=python; verify by running the target's own tests.\n"
            "verification: target unit tests must pass."
            % (fact["source_task"], _ops(fact), _libs(fact), fact.get("summary", "solve the task"), _apis(fact)))


def f4_raw_verified_trace(fact):
    return ("Verified solution to a prior task (%s):\n%s" % (fact["source_task"], fact.get("verified_code", "").strip()))


RENDERERS = {"F0_MINIMAL_HINT": f0_minimal_hint, "F1_PLAIN_LESSON": f1_plain_lesson,
             "F2_API_CARD": f2_api_card, "F3_GOVERNED_COMPACT": f3_governed_compact,
             "F4_RAW_VERIFIED_TRACE": f4_raw_verified_trace}


def render(fmt, fact):
    return RENDERERS[fmt](fact)
