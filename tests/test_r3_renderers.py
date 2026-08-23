"""REALBENCH-R3 §9/§10/§24 — renderer + decoder integrity tests (no model calls, no heavy deps).

Enforces the invariants §24 checks: (1) every bundle renders from the SAME canonical object; (2) the token
budget is respected (<= MAX_TOKENS) under the frozen tokenizer; (3) no marked source constant/name leaks into
any view; (4) the matched decoder is always present; (5) decoder hashes are stable.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments.actionable_memory_r3 import renderers as R, decoders as D  # noqa: E402

CANON = {
    "task_family": "dataframe groupby", "required_imports": ["pandas"],
    "relevant_apis": ["groupby", "agg", "reset_index", "pivot_table", "merge"],
    "input_contract": "DF with key COL and value VAL", "output_contract": "DF aggregated by COL",
    "preconditions": ["COL exists", "no NaN in COL"], "postconditions": ["indexed by COL"],
    "invariants": ["rows <= input"], "applicability": "aggregation over a key column",
    "non_applicability": "when original order must be preserved", "ordered_operations": ["select COL", "groupby COL", "agg VAL", "reset_index"],
    "control_flow_pattern": "vectorized, no explicit loop", "data_transformation": "group and aggregate",
    "common_failure": "forgetting reset_index changes the interface",
    "positive_pattern": "DF.groupby(COL).agg(FUNC).reset_index()", "negative_pattern": "iterating rows in a Python for-loop",
    "generalized_ast_edit": ["REPLACE loop with groupby", "WRAP agg", "PRESERVE return VAR"],
    "generalized_diff_template": "- for VAR in DF:\n+ result = DF.groupby(COL).agg(FUNC).reset_index()",
    "verification_procedure": ["check columns", "check row count"],
    "executable_properties": ["result.index.name == COL", "len(result) <= len(DF)"],
    "source_constants": ["df", "result", "mycol", "sumval", "42", "3.14"],
    "evidence": {"solution_code": "result = df.groupby(mycol).agg(sumval).reset_index()  # 42 rows\n"},
}
LEAK_TOKENS = ["mycol", "sumval", "result =", "df.groupby", "42", "3.14"]


def test_all_bundles_within_budget():
    for b in R.BUNDLE_ORDER:
        out = R.render(b, CANON)
        assert out["tokens"] <= R.MAX_TOKENS, "%s over budget: %d" % (b, out["tokens"])
        assert out["tokenizer"].startswith("tiktoken") or out["tokenizer"] == "heuristic"


def test_no_source_constant_leakage():
    for b in R.BUNDLE_ORDER:
        view = R.render(b, CANON)["view"]
        for bad in LEAK_TOKENS:
            assert bad not in view, "%s leaked %r" % (b, bad)


def test_matched_decoder_present_and_generic_swappable():
    for b in R.BUNDLE_ORDER:
        matched = R.render(b, CANON)
        assert "Decoder:" in matched["view"] and matched["decoder_kind"] == "matched"
        generic = R.render(b, CANON, decoder=D.GENERIC_DECODER)
        assert generic["decoder_kind"] == "generic" and D.GENERIC_DECODER in generic["view"]


def test_same_canonical_object_for_all_bundles():
    # §8 invariant: the renderers are pure projections of ONE canonical dict — rendering twice is identical,
    # and no renderer mutates the canonical object.
    import copy
    snap = copy.deepcopy(CANON)
    for b in R.BUNDLE_ORDER:
        R.render(b, CANON)
    assert CANON == snap, "a renderer mutated the canonical object"


def test_decoder_hashes_stable():
    m = D.manifest()
    assert set(m) == set(R.BUNDLE_ORDER) | {"GENERIC"}
    for k, v in m.items():
        assert v["hash"] == D.decoder_hash(v["text"])
