"""M7 (SPEC, not executed against Solar): governed canonical backend UNCHANGED + a deterministic compact
EXECUTION VIEW frontend. The authoritative MemoryContract + gates + audit are untouched; this compiler
emits a reader-facing view ONLY after all gates pass. No LLM rewriting, no provenance/audit metadata, no
registry scores. It exists to test the E5 hypothesis (the governed-contract *serialization*, not memory
availability, degraded executable commitment) — by rendering governed content in the compact imperative
form that scored best (M4). Efficacy is NOT evaluated here; this is offline structural code + tests."""
from __future__ import annotations

MAX_WORDS = 120


class ViewCompileError(Exception):
    pass


def compile_execution_view(contract: dict) -> str:
    """Deterministically compile a canonical contract dict into a <=120-word execution view.

    Required keys: func, args (list), applicability (list of predicate strings), action
    ({op in multiply|add, operand:int, target:str}), default (str), validity ({state}), scope_ok (bool).
    Raises ViewCompileError for expired/out-of-scope contracts (they never compile)."""
    if contract.get("validity", {}).get("state") != "CURRENT":
        raise ViewCompileError("expired_or_invalid_validity")
    if not contract.get("scope_ok", False):
        raise ViewCompileError("out_of_scope")
    func = contract["func"]; args = contract["args"]; act = contract["action"]
    op = act["op"]; operand = int(act["operand"]); target = act["target"]
    if op not in ("multiply", "add"):
        raise ViewCompileError("unsupported_operation")
    verb = {"multiply": "multiply %s by %d" % (target, operand),
            "add": "add %d to %s" % (operand, target)}[op]
    result = {"multiply": "%s * %d" % (target, operand), "add": "%s + %d" % (target, operand)}[op]
    applic = " and ".join(contract["applicability"])   # ORDER preserved from canonical
    default = contract["default"]
    view = ("When %s, %s; otherwise %s. Edit only %s(%s), keeping its signature. "
            "Verify: the result equals %s when applicable, else the unchanged value."
            % (applic, verb, default, func, ", ".join(args), result))
    if len(view.split()) > MAX_WORDS:
        raise ViewCompileError("exceeds_word_budget")
    return view


REFUSE_STATES = ("OUT_OF_SCOPE", "EXPIRED", "DEPRECATED", "QUARANTINED", "SUPERSEDED",
                 "UNAUTHORIZED", "CONFLICTING_UNRESOLVED")


def compile_or_refuse(contract: dict):
    """Deterministic control-plane property (NOT an LLM result). Returns ('REFUSED', reason) when the
    contract is out-of-scope/expired/deprecated/quarantined/superseded/unauthorized/conflicting, else
    ('OK', view). No model-facing execution text is produced on refusal."""
    gov = contract.get("governance_state", "PROMOTED")
    if gov in REFUSE_STATES:
        return "REFUSED", gov
    if contract.get("validity", {}).get("state") != "CURRENT":
        return "REFUSED", "EXPIRED"
    if not contract.get("scope_ok", False):
        return "REFUSED", "OUT_OF_SCOPE"
    try:
        return "OK", compile_execution_view(contract)
    except ViewCompileError as e:
        return "REFUSED", str(e)


def canonical_hash_is_authoritative(contract: dict, view: str) -> bool:
    """The compiled view is derived, never authoritative: it must not be usable to reconstruct or
    override the canonical contract's identity. We assert the view carries no contract_id / provenance."""
    lowered = view.lower()
    banned = ("contract_id", "ct_", "cl_", "provenance", "audit", "episode", "score", "confidence")
    return not any(b in lowered for b in banned)
