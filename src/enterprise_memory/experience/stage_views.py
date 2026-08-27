"""R22 §8 — the four projections of a StageMemoryRecord (deterministic; no model calls).

EpisodicPrecedent  : the concrete transition (state -> attempt -> failure -> fix -> confirm).
SemanticRecipe     : the reusable rule (when to apply / what to check / what edit / when NOT / how to verify).
SearchIndexView    : metadata-only vector-index payload (NO raw patch / trajectory / identity / gold / target).
ExecutionView      : gated, injected only after browse; <= 220 tokens by default; NO raw diff by default.
"""
from __future__ import annotations

from .stage_schema import StageMemoryRecord, assert_no_target_leakage

EXEC_TOKEN_BUDGET = 220


def _approx_tokens(s: str) -> int:
    # deterministic word/4-char heuristic; no tokenizer dependency
    return max(len(s.split()), len(s) // 4)


def episodic_precedent(rec: StageMemoryRecord) -> dict:
    t = rec.transition
    view = {
        "kind": "EpisodicPrecedent", "stage": rec.stage.value,
        "observation_before": t.observation_before,
        "attempted_action": t.attempted_action,
        "environment_feedback": t.environment_feedback,
        "failure_reason": t.failure_reason,
        "successful_action": t.successful_action,
        "observation_after": t.observation_after,
        "source_provenance": rec.identity.memory_id,
    }
    assert_no_target_leakage(view)
    return view


def semantic_recipe(rec: StageMemoryRecord) -> dict:
    a = rec.action
    view = {
        "kind": "SemanticRecipe", "stage": rec.stage.value,
        "when_to_apply": rec.trigger.violated_contract or rec.trigger.error_signature,
        "symbols_apis_to_check": sorted(set(rec.trigger.affected_symbols) | set(rec.trigger.affected_apis)),
        "violated_contract": rec.trigger.violated_contract,
        "operation_type": a.operation_type,
        "ordered_steps": a.ordered_steps,
        "preconditions": a.preconditions,
        "non_applicability": a.non_applicability,
        "verification": rec.verification.command_type,
    }
    assert_no_target_leakage(view)
    return view


def search_index_view(rec: StageMemoryRecord) -> dict:
    """Metadata only — safe to embed in Qdrant. Never contains raw patch, trajectory, identity, gold, or target."""
    tr = rec.trigger
    import hashlib
    import json
    payload = {
        "stage": rec.stage.value,
        "symptom": tr.error_signature or tr.issue_type,
        "error_signature": tr.error_signature,
        "stack_trace_signature": tr.stack_trace_signature,
        "failing_test_signature": tr.failing_test_signature,
        "symbols": sorted(tr.affected_symbols),
        "apis": sorted(tr.affected_apis),
        "contract": tr.violated_contract,
        "operation_type": rec.action.operation_type,
        "language": tr.language, "framework": tr.framework,
        "dependency_versions": tr.dependency_versions,
        "repository_scope": rec.identity.source_repository,
        "memory_id": rec.identity.memory_id,
    }
    payload["content_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    # Forbidden even to *reference* these in the index:
    for banned in ("patch", "trajectory", "user", "gold", "verdict", "test_patch"):
        assert banned not in payload, "search index leaked %s" % banned
    assert_no_target_leakage(payload)
    return payload


def execution_view(rec: StageMemoryRecord, token_budget: int = EXEC_TOKEN_BUDGET,
                   include_raw_diff: bool = False) -> dict:
    """Gated actionable view (post-browse). Raw diff is NOT included unless explicitly requested for an oracle arm."""
    t, a = rec.transition, rec.action
    situation = t.observation_before
    fix = a.edit_template or t.successful_action
    view = {
        "kind": "ExecutionView", "stage": rec.stage.value,
        "situation": situation,
        "failed_attempt": "%s -> %s" % (t.attempted_action, t.failure_reason),
        "successful_operation": fix,
        "operation_type": a.operation_type,
        "preconditions": a.preconditions,
        "non_applicability": a.non_applicability,
        "verification_recipe": rec.verification.command_type,
        "source_provenance": rec.identity.memory_id,
    }
    if include_raw_diff:
        # oracle-only upper-bound reference; NEVER used in product/main arms
        view["_oracle_raw_diff_ref"] = rec.raw_evidence.patch_artifact_id
    # enforce token budget by trimming free-text fields deterministically (longest first)
    text_keys = ["situation", "failed_attempt", "successful_operation", "verification_recipe"]
    while _approx_tokens(" ".join(str(view[k]) for k in text_keys)) > token_budget:
        k = max(text_keys, key=lambda kk: len(str(view[kk])))
        s = str(view[k])
        if not s:
            break
        view[k] = s[: max(0, len(s) - 40)].rstrip()
    view["approx_tokens"] = _approx_tokens(" ".join(str(view[k]) for k in text_keys))
    assert_no_target_leakage(view)
    return view
