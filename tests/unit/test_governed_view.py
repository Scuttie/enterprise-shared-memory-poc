"""§7 M7 deterministic compiler tests (offline; no Solar). Verifies structural guarantees only —
efficacy is NOT tested here."""
import os
import sys
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
from enterprise_memory.serving.governed_view import (  # noqa: E402
    compile_execution_view, canonical_hash_is_authoritative, ViewCompileError, MAX_WORDS)

CACHE = {"func": "cache_ttl", "args": ["num_keys", "txn_active", "cache_tier"],
         "applicability": ["txn_active is True", "cache_tier == 'HOT'"],
         "action": {"op": "multiply", "operand": 6, "target": "num_keys"},
         "default": "return num_keys unchanged", "validity": {"state": "CURRENT"}, "scope_ok": True}
API = {"func": "compute_retry_delay", "args": ["retry_after", "tenant_class", "api_version"],
       "applicability": ["tenant_class == 'ORCHID'", "api_version >= 2"],
       "action": {"op": "add", "operand": 10, "target": "retry_after"},
       "default": "return retry_after unchanged", "validity": {"state": "CURRENT"}, "scope_ok": True}


def test_action_atom_retained():
    v = compile_execution_view(CACHE)
    assert "multiply num_keys by 6" in v            # operation + operand + target atom preserved


def test_parameter_polarity_retained():
    assert "add 10 to retry_after" in compile_execution_view(API)     # add, not multiply
    assert "multiply" not in compile_execution_view(API)


def test_operation_order_retained():
    v = compile_execution_view(CACHE)
    assert v.index("txn_active is True") < v.index("cache_tier == 'HOT'")   # applicability order preserved
    assert v.index("When ") < v.index("multiply")                          # applicability before action


def test_no_target_specific_values():
    # numbers in the view may only be the policy operand(s), never a target input/output
    v = compile_execution_view(CACHE)
    nums = set(re.findall(r"\d+", v))
    assert nums == {"6"}                                                    # only the operand


def test_applicability_explanation_correct():
    v = compile_execution_view(CACHE)
    assert v.startswith("When txn_active is True and cache_tier == 'HOT',")


def test_expired_never_compiles():
    c = dict(CACHE); c["validity"] = {"state": "EXPIRED"}
    try:
        compile_execution_view(c); assert False
    except ViewCompileError as e:
        assert "validity" in str(e)


def test_out_of_scope_never_compiles():
    c = dict(CACHE); c["scope_ok"] = False
    try:
        compile_execution_view(c); assert False
    except ViewCompileError as e:
        assert "scope" in str(e)


def test_view_has_no_provenance_or_ids():
    assert canonical_hash_is_authoritative(CACHE, compile_execution_view(CACHE))


def test_interface_named_exactly():
    assert "cache_ttl(num_keys, txn_active, cache_tier)" in compile_execution_view(CACHE)


def test_word_budget():
    assert len(compile_execution_view(CACHE).split()) <= MAX_WORDS


def test_output_stable_across_runs():
    assert compile_execution_view(CACHE) == compile_execution_view(CACHE)
    assert compile_execution_view(API) == compile_execution_view(API)
