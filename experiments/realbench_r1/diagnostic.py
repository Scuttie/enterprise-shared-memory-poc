"""REALBENCH-R1.1 diagnostic (§2). Reuses the ALREADY-OBSERVED 120 MBPP+ main targets for MECHANISM
diagnostics only — descriptive, no confirmatory p-value. Isolates: (relevant memory) vs (generic matched
extra context) vs (retrieval), and memory format, through the same HTTP->worker path with the PINNED
PRODUCTION embedder.

Evaluator-side relevance labels are computed OFFLINE from the official source+target canonical solutions
(imports/APIs/operations/control-flow). They define the frozen relevant source, the shuffled derangement, and
the length-matched irrelevant source. They NEVER enter a prompt, a memory, the retrieval query, or the
backend — only the SOURCE lessons/traces (source-only) are ever injected. Target solutions/tests never enter
memory."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass

from . import experiment as X, grader as G
from experiments import patch_forensics as PF


# ---------------------------------------------------------------- evaluator-side signatures & labels
def _canonical_signature(tid):
    """AST signature of a task's OFFICIAL canonical solution (evaluator-side only)."""
    p = G.task(tid)
    code = (p.get("prompt", "") or "") + "\n" + (p.get("canonical_solution", "") or "")
    sig = PF.patch_signature(code) or {"imports": set(), "apis": set(), "control_flow": set(), "operations": set()}
    return sig


def _overlap(a, b):
    ea = a["imports"] | a["apis"] | a["operations"] | a["control_flow"]
    eb = b["imports"] | b["apis"] | b["operations"] | b["control_flow"]
    if not ea or not eb:
        return 0.0
    return len(ea & eb) / len(ea | eb)


def _order_key(*p):
    return hashlib.sha256("|".join(map(str, p)).encode("utf-8")).hexdigest()


def relevance_labels(split):
    """For each of the 120 main targets: the evaluator-relevant source (argmax canonical-signature overlap),
    a matched-irrelevant source (near-zero overlap, closest memory length), and a frozen derangement over the
    relevant sources for the shuffled-matched control. All from source-only signatures."""
    targets = split["main"]
    sources = split["source"]
    ssig = {s: _canonical_signature(s) for s in sources}
    tsig = {t: _canonical_signature(t) for t in targets}
    facts = {s: X.source_fact(s) for s in sources}
    slen = {s: len(X.ungoverned_text(facts[s])) for s in sources}

    relevant, irrelevant = {}, {}
    for t in targets:
        scored = sorted(((_overlap(tsig[t], ssig[s]), s) for s in sources),
                        key=lambda kv: (-kv[0], _order_key("rel", t, kv[1])))
        relevant[t] = scored[0][1]
        tlen = len(X.ungoverned_text(facts[relevant[t]]))
        zero = [s for ov, s in scored if ov == 0.0] or [s for ov, s in scored[-10:]]
        irrelevant[t] = sorted(zero, key=lambda s: (abs(slen[s] - tlen), _order_key("irr", t, s)))[0]

    # derangement of the relevant-source assignment (no target keeps its own relevant source)
    order = sorted(targets, key=lambda t: _order_key("shuf", t))
    rel_sources = [relevant[t] for t in order]
    rot = rel_sources[1:] + rel_sources[:1]
    shuffled = {}
    for t, s in zip(order, rot):
        if s == relevant[t]:                       # guarantee no fixed point
            s = rel_sources[(rel_sources.index(s) + 2) % len(rel_sources)]
        shuffled[t] = s
    return {"relevant": relevant, "irrelevant": irrelevant, "shuffled": shuffled,
            "source_sig": {s: {k: sorted(v) for k, v in ssig[s].items()} for s in sources},
            "target_relevance_overlap": {t: round(_overlap(tsig[t], ssig[relevant[t]]), 4) for t in targets}}


def labels_hash(labels):
    payload = {k: labels[k] for k in ("relevant", "irrelevant", "shuffled")}
    return hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()


def _stable(obj):
    import json
    return json.dumps(obj, sort_keys=True)


# ---------------------------------------------------------------- renderers (rendered AFTER source selection)
def render_plain(fact):
    return X.ungoverned_text(fact)


def render_governed(fact):
    return X.governed_summary(fact)


def render_api_card(source_tid):
    """imports / called APIs / operation / precondition / pitfall — derived from the source canonical only."""
    sig = _canonical_signature(source_tid)
    fact = X.source_fact(source_tid)
    libs = ", ".join(sorted(sig["imports"])) or "none"
    apis = ", ".join(sorted(sig["apis"])[:12]) or "builtins"
    ops = ", ".join(sorted(sig["operations"])) or "n/a"
    return ("API card from a verified prior task (%s). libraries: %s. key calls: %s. operations: %s. "
            "precondition: validate inputs match the signature. common pitfall: off-by-one / empty-input "
            "handling. keywords: %s" % (source_tid, libs, apis, ops, fact["tokens"]))


def render_raw_trace(source_tid):
    """Complete verified SOURCE solution trace (source-only; diagnostic/GOLD upper-bound)."""
    p = G.task(source_tid)
    return ("verified solution to a prior task (%s):\n%s"
            % (source_tid, (p.get("prompt", "") or "").strip() + "\n" + (p.get("canonical_solution", "") or "").strip()))


RENDERERS = {"plain": (lambda tid, fact: render_plain(fact)),
             "governed": (lambda tid, fact: render_governed(fact)),
             "api_card": (lambda tid, fact: render_api_card(tid)),
             "raw_trace": (lambda tid, fact: render_raw_trace(tid))}


# ---------------------------------------------------------------- arms (§2)
@dataclass(frozen=True)
class DArm:
    code: str
    name: str
    source_kind: str        # none | relevant | shuffled | irrelevant | retrieved
    render: str             # plain | governed | api_card | raw_trace | -
    always_inject: bool     # fixed-source arms always inject; retrieved arm may abstain unless threshold off
    note: str = ""


D0 = DArm("D0", "NO_MEMORY", "none", "-", False)
D1 = DArm("D1", "RELEVANT_PLAIN", "relevant", "plain", True)
D2 = DArm("D2", "RELEVANT_GOVERNED", "relevant", "governed", True, "same source ID + injection as D1")
D3 = DArm("D3", "RELEVANT_API_CARD", "relevant", "api_card", True)
D4 = DArm("D4", "RELEVANT_RAW_VERIFIED_TRACE", "relevant", "raw_trace", True, "GOLD diagnostic upper bound")
D5 = DArm("D5", "SHUFFLED_MATCHED", "shuffled", "plain", True, "frozen derangement; injects iff D2 injects")
D6 = DArm("D6", "IRRELEVANT_LENGTH_MATCHED", "irrelevant", "plain", True)
D7 = DArm("D7", "ALWAYS_INJECT_TOP1", "retrieved", "plain", True, "production retriever top-1, threshold off")
# D8 TRUE_ORACLE_RELEVANT == D1 by construction: the frozen relevant source IS the evaluator relevance label.
# Retain one physical arm; report D8 as the D1 result (§10 dedup philosophy). No duplicate calls.
D8 = DArm("D8", "TRUE_ORACLE_RELEVANT", "relevant", "plain", True, "== D1 by construction (evaluator oracle)")

PHYSICAL = [D0, D1, D2, D3, D4, D5, D6, D7]     # D8 aliases D1
ALL = PHYSICAL + [D8]
BY_CODE = {a.code: a for a in ALL}
