"""BIGCODE-R2-C memory-format discovery (§7) + predeclared selection rule (§8). Discovery runs ONLY on the
MEMORY_DISCOVERY tasks and is DESCRIPTIVE — no confirmatory p-value. It selects exactly ONE deployable memory
policy for the confirmatory main by a PREDECLARED lexicographic rule (never by minimum p-value).

A discovery "cell" = (format, retrieval_policy). Formats F0-F4 are the renderers in render.py. Retrieval
policies:
  P0 FIXED_TRUE_RELEVANT   inject the evaluator-relevant source (fixed), always
  P1 PROD_TOP1             production embedder top-1 with abstention
  P2 PROD_TOP3             production embedder top-3, fixed total token budget
  P3 ALWAYS_TOP1           production top-1, threshold off
  P4 SHUFFLED_MATCHED      frozen derangement (matched), always inject

Fractional design (not full combinatorial): each F0-F4 under P0; F1/F2/F3 under P1; the P0 formats also under
P4 (the relevance control); F2 under P2 (top-3) to compare against F2/P1 (top-1)."""
from __future__ import annotations

FORMATS = ("F0_MINIMAL_HINT", "F1_PLAIN_LESSON", "F2_API_CARD", "F3_GOVERNED_COMPACT", "F4_RAW_VERIFIED_TRACE")
POLICIES = ("P0_FIXED_TRUE_RELEVANT", "P1_PROD_TOP1", "P2_PROD_TOP3", "P3_ALWAYS_TOP1", "P4_SHUFFLED_MATCHED")


def cells():
    """The frozen fractional set of discovery cells. Each cell is a dict {code, format, policy, source_kind}.
    source_kind drives seeding: relevant (P0), shuffled (P4), or retrieved (P1/P2/P3)."""
    out = []
    for f in FORMATS:                                  # F0-F4 under fixed true-relevant source
        out.append({"code": "%s@P0" % f, "format": f, "policy": "P0_FIXED_TRUE_RELEVANT", "source_kind": "relevant"})
    for f in FORMATS:                                  # relevance control: same formats under shuffled-matched
        out.append({"code": "%s@P4" % f, "format": f, "policy": "P4_SHUFFLED_MATCHED", "source_kind": "shuffled"})
    for f in ("F1_PLAIN_LESSON", "F2_API_CARD", "F3_GOVERNED_COMPACT"):   # deployable retrieval, top-1
        out.append({"code": "%s@P1" % f, "format": f, "policy": "P1_PROD_TOP1", "source_kind": "retrieved"})
    out.append({"code": "F2_API_CARD@P2", "format": "F2_API_CARD", "policy": "P2_PROD_TOP3", "source_kind": "retrieved"})
    return out


def select_policy(cell_pass1, cell_loss_rate, cell_mean_tokens, safety):
    """PREDECLARED lexicographic selection (§8). Inputs are per-cell descriptive stats keyed by cell code.
    cell_pass1: {code: Pass@1}. cell_loss_rate: {code: memory-induced loss rate}. cell_mean_tokens:
    {code: mean injected tokens}. safety: {"target_test_leakage": int, "cross_user_leakage": int,
    "invalid_injection": int}. Returns {selected, relevance_effect_by_format, calculation}.

    1. hard safety must pass (all three counters == 0), else no policy is deployable.
    2. maximise Pass@1(RELEVANT_FIXED,F) - Pass@1(SHUFFLED_MATCHED,F) over formats F.
    3. among formats within 0.01 of the best relevance effect: minimise memory-induced loss rate.
    4. among those within 0.01: minimise mean injected tokens.
    5. final tie-break: lexicographic policy/format id.
    """
    hard_ok = (safety.get("target_test_leakage", 1) == 0 and safety.get("cross_user_leakage", 1) == 0
               and safety.get("invalid_injection", 1) == 0)
    rel_effect = {}
    for f in FORMATS:
        r = cell_pass1.get("%s@P0" % f)
        s = cell_pass1.get("%s@P4" % f)
        if r is not None and s is not None:
            rel_effect[f] = round(r - s, 6)
    if not rel_effect or not hard_ok:
        return {"selected": None, "hard_safety_pass": hard_ok, "relevance_effect_by_format": rel_effect,
                "reason": "hard safety failed" if not hard_ok else "no comparable cells"}
    best = max(rel_effect.values())
    near = [f for f, v in rel_effect.items() if best - v <= 0.01 + 1e-9]
    # step 3: minimise loss rate (use the P0 cell's loss rate as the format's deployable-candidate loss)
    near.sort(key=lambda f: (cell_loss_rate.get("%s@P0" % f, 1.0),
                             cell_mean_tokens.get("%s@P0" % f, 1e9), f))
    lr0 = cell_loss_rate.get("%s@P0" % near[0], 1.0)
    near2 = [f for f in near if cell_loss_rate.get("%s@P0" % f, 1.0) - lr0 <= 0.01 + 1e-9]
    near2.sort(key=lambda f: (cell_mean_tokens.get("%s@P0" % f, 1e9), f))
    tk0 = cell_mean_tokens.get("%s@P0" % near2[0], 1e9)
    near3 = sorted([f for f in near2 if cell_mean_tokens.get("%s@P0" % f, 1e9) - tk0 <= 1e-9])
    selected_format = near3[0]
    # deployable retrieval policy for the selected format: prefer P1 (production top-1 w/ abstention) if that
    # format was run under retrieval; else fall back to the fixed-relevant policy label (the format is what
    # the main deploys; M4 uses production retrieval regardless).
    return {"selected": {"format": selected_format, "policy": "P1_PROD_TOP1"},
            "hard_safety_pass": True, "relevance_effect_by_format": rel_effect,
            "calculation": {"best_relevance_effect": best, "within_0.01": near,
                            "after_loss_tiebreak": near2, "after_token_tiebreak": near3,
                            "loss_rate_P0": {f: cell_loss_rate.get("%s@P0" % f) for f in FORMATS},
                            "mean_tokens_P0": {f: cell_mean_tokens.get("%s@P0" % f) for f in FORMATS}}}
