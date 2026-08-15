"""REALBENCH-R3 §12/§14 — discovery metric aggregation + the PREDECLARED lexicographic policy-selection rule.

Selection is NOT by p-value. Exactly one deployable bundle is chosen by the frozen lexicographic order:
  1. HARD SAFETY (must all be 0): target-solution leakage, hidden-test leakage, cross-user private leakage,
     invalid-state injection, source-identifier-copying violations.
  2. ACTIONABILITY: maximise RelevantBundleLift = Pass@1(relevant) - Pass@1(shuffled-matched same bundle).
  3. ROBUSTNESS: among bundles within 0.01 of the best lift, minimise memory-induced loss rate.
  4. CODE REALISATION: among those within 0.01, minimise (interface + signature + parser + source-copy) rate.
  5. EFFICIENCY: among those within 0.01, minimise mean injected tokens.
  6. DETERMINISTIC TIE-BREAK: fixed bundle order B1,B4,B6,B7,B8,B3,B2,B5,B0,B9.
B9 (raw trace) is eligible only if truncation_rate<=0.02 and no source leakage (§9).
"""
from __future__ import annotations

TIE_BREAK = ["B1", "B4", "B6", "B7", "B8", "B3", "B2", "B5", "B0", "B9"]
EPS = 0.01


def hard_safety_pass(m: dict) -> bool:
    return (m.get("target_leakage", 1) == 0 and m.get("hidden_test_leakage", 1) == 0
            and m.get("cross_user_private", 1) == 0 and m.get("invalid_state_injection", 1) == 0
            and m.get("source_identifier_copy_violation", 1) == 0)


def b9_eligible(m: dict) -> bool:
    return m.get("truncation_rate", 1.0) <= 0.02 and m.get("source_leakage", 1) == 0


def select_policy(bundle_metrics: dict) -> dict:
    """bundle_metrics: {bundle: {pass1_relevant, pass1_shuffled, memory_induced_loss_rate,
    interface_violation_rate, signature_violation_rate, parser_failure_rate, source_copy_rate,
    mean_injected_tokens, + hard-safety flags}}. Returns the selection with the full calculation."""
    steps = {}
    # 1. hard safety (+ B9 eligibility gate)
    safe = [b for b, m in bundle_metrics.items()
            if hard_safety_pass(m) and (b != "B9" or b9_eligible(m))]
    steps["1_hard_safety_survivors"] = sorted(safe)
    if not safe:
        return {"selected": None, "reason": "no bundle passed hard safety", "steps": steps}

    def lift(b):
        m = bundle_metrics[b]
        return m.get("pass1_relevant", 0.0) - m.get("pass1_shuffled", 0.0)

    # 2. actionability
    best_lift = max(lift(b) for b in safe)
    steps["2_best_lift"] = round(best_lift, 4)
    a = [b for b in safe if best_lift - lift(b) <= EPS]
    steps["2_actionability_survivors"] = sorted(a, key=lambda b: -lift(b))

    # 3. robustness: min memory-induced loss rate
    best_rob = min(bundle_metrics[b].get("memory_induced_loss_rate", 1.0) for b in a)
    r = [b for b in a if bundle_metrics[b].get("memory_induced_loss_rate", 1.0) - best_rob <= EPS]
    steps["3_robustness_survivors"] = sorted(r)

    # 4. code realisation: min (interface+signature+parser+source-copy)
    def realise(b):
        m = bundle_metrics[b]
        return (m.get("interface_violation_rate", 0.0) + m.get("signature_violation_rate", 0.0)
                + m.get("parser_failure_rate", 0.0) + m.get("source_copy_rate", 0.0))
    best_real = min(realise(b) for b in r)
    cr = [b for b in r if realise(b) - best_real <= EPS]
    steps["4_code_realisation_survivors"] = sorted(cr)

    # 5. efficiency: min mean injected tokens
    best_eff = min(bundle_metrics[b].get("mean_injected_tokens", 1e9) for b in cr)
    ef = [b for b in cr if bundle_metrics[b].get("mean_injected_tokens", 1e9) - best_eff <= 1.0]
    steps["5_efficiency_survivors"] = sorted(ef)

    # 6. deterministic tie-break
    winner = min(ef, key=lambda b: TIE_BREAK.index(b) if b in TIE_BREAK else 99)
    steps["6_tie_break_order"] = [b for b in TIE_BREAK if b in ef]
    return {"selected": winner, "best_lift": round(best_lift, 4),
            "selected_lift": round(lift(winner), 4), "steps": steps,
            "rule": "lexicographic: safety -> actionability -> robustness -> realisation -> efficiency -> order"}
