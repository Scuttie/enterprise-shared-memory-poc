"""§8 generalised, versioned typed execution-view compiler. Extends the v0.1 pilot compiler (which
supported only a multiply/add family) to a typed ExecutionDirective IR with a plugin registry. The
compiler is deterministic, emits literal interface/enum/operator names, never emits opaque IDs /
provenance / target answers / LLM paraphrase, and REFUSES unsupported directives and invalid contracts.
The parent contract hash is retained OUTSIDE the model-facing view."""
from __future__ import annotations
from dataclasses import dataclass, field

IR_VERSION = "1"
REFUSE_STATES = ("UNAUTHORIZED", "OUT_OF_SCOPE", "EXPIRED", "DEPRECATED", "QUARANTINED", "SUPERSEDED",
                 "CONFLICTING_UNRESOLVED")
OPERATORS = ("==", "!=", "<", "<=", ">", ">=", "is_true", "is_false", "in", "not_in", "matches",
             "version_satisfies")


class ViewRefused(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Predicate:
    left_symbol: str
    operator: str
    right_literal_or_symbol: object
    value_type: str
    polarity: bool = True

    def literal(self) -> str:
        assert self.operator in OPERATORS, self.operator
        r = self.right_literal_or_symbol
        rep = ("'%s'" % r) if self.value_type == "str" else str(r)
        base = {"is_true": "%s is true" % self.left_symbol, "is_false": "%s is false" % self.left_symbol,
                "in": "%s in %s" % (self.left_symbol, rep), "not_in": "%s not in %s" % (self.left_symbol, rep),
                "matches": "%s matches %s" % (self.left_symbol, rep),
                "version_satisfies": "%s satisfies %s" % (self.left_symbol, rep)}.get(
            self.operator, "%s %s %s" % (self.left_symbol, self.operator, rep))
        return ("not (%s)" % base) if not self.polarity else base


@dataclass
class Operation:
    operation_id: str
    template_id: str
    parameters: dict
    target_symbol: str


@dataclass
class ExecutionDirective:
    directive_id: str
    language: str
    target_symbol: str
    exact_signature: str
    predicates: list           # list[Predicate]
    operation: Operation
    operation_order: list = field(default_factory=list)
    forbidden_operations: list = field(default_factory=list)
    verification: str = ""
    source_contract_id: str = ""
    source_contract_version: str = ""
    source_contract_hash: str = ""
    governance_state: str = "PROMOTED"
    validity_state: str = "CURRENT"
    scope_ok: bool = True
    authorized: bool = True


# ---- plugin registry: template_id -> renderer(op) -> (action_text, result_expr) ------------------
_PLUGINS = {}


def plugin(template_id):
    def deco(fn):
        _PLUGINS[template_id] = fn
        return fn
    return deco


@plugin("arithmetic.scale")
def _scale(op):
    k = int(op.parameters["operand"])
    return "multiply %s by %d" % (op.target_symbol, k), "%s * %d" % (op.target_symbol, k)


@plugin("arithmetic.offset")
def _offset(op):
    k = int(op.parameters["operand"])
    return "add %d to %s" % (k, op.target_symbol), "%s + %d" % (op.target_symbol, k)


@plugin("select.source")
def _select(op):
    src = op.parameters["source_symbol"]
    return "return %s" % src, src


@plugin("map.constant")
def _mapc(op):
    val = op.parameters["value_symbol"]
    return "return %s" % val, val


SUPPORTED_TEMPLATES = tuple(sorted(_PLUGINS))


def compile_directive(d: ExecutionDirective, max_words: int = 120):
    """Deterministically compile a directive to a compact literal execution view, or raise ViewRefused."""
    if not d.authorized:
        raise ViewRefused("UNAUTHORIZED")
    if d.governance_state in REFUSE_STATES:
        raise ViewRefused(d.governance_state)
    if d.validity_state != "CURRENT":
        raise ViewRefused("EXPIRED")
    if not d.scope_ok:
        raise ViewRefused("OUT_OF_SCOPE")
    if d.operation.template_id not in _PLUGINS:
        raise ViewRefused("REFUSED_UNSUPPORTED_DIRECTIVE")
    action_text, result_expr = _PLUGINS[d.operation.template_id](d.operation)
    applic = " and ".join(p.literal() for p in d.predicates)   # order preserved
    forb = (" Do not %s." % "; do not ".join(d.forbidden_operations)) if d.forbidden_operations else ""
    verify = d.verification or ("the result equals %s when applicable, else the unchanged value" % result_expr)
    view = ("When %s, %s; otherwise return the unchanged value. Edit only %s, keeping its signature.%s "
            "Verify: %s." % (applic, action_text, d.exact_signature, forb, verify))
    if len(view.split()) > max_words:
        raise ViewRefused("EXCEEDS_WORD_BUDGET")
    # control-plane hygiene: no opaque IDs / provenance / answers in the model-facing view
    lowered = view.lower()
    assert not any(x in lowered for x in ("contract_id", "ct_", "cl_", "provenance", "audit", "score=")), view
    return {"ir_version": IR_VERSION, "view": view, "parent_contract_hash": d.source_contract_hash,
            "source_contract_id": d.source_contract_id, "source_contract_version": d.source_contract_version}
