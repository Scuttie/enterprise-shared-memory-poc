"""BigCode-R2 evaluator-side relevance labels (§6.1). Computed OFFLINE from the official source+target
canonical solutions (imports / called APIs / algorithmic operations / control-flow). They define, for each
target set (discovery / calibration / main): the evaluator-relevant source, a frozen derangement
(shuffled-matched negative), and a length-matched irrelevant source. These labels NEVER enter a target
prompt, a memory, the retrieval query, the harness, or the backend — only SOURCE memories (source-only) are
ever injected, and only the PUBLIC instruct prompt/signature drive deployable retrieval (§6.2). Sealed before
any discovery/main model call."""
from __future__ import annotations
import hashlib
import json

from experiments.bigcode_r2 import grader as G
from experiments import patch_forensics as PF


def _sig(tid):
    code = G.reference_solution(tid)               # complete_prompt + canonical_solution (evaluator-side only)
    return PF.patch_signature(code) or {"imports": set(), "apis": set(), "control_flow": set(), "operations": set()}


def _elems(sig):
    return sig["imports"] | sig["apis"] | sig["operations"] | sig["control_flow"]


def _overlap(a, b):
    ea, eb = _elems(a), _elems(b)
    return (len(ea & eb) / len(ea | eb)) if (ea and eb) else 0.0


def _key(*p):
    return hashlib.sha256("|".join(map(str, p)).encode("utf-8")).hexdigest()


def build_labels(sources, targets, memory_len):
    """sources: source task ids. targets: target task ids. memory_len: {source_tid: int} deployable memory
    length (for length-matched irrelevant selection). Returns relevant/irrelevant/shuffled maps + overlaps."""
    ssig = {s: _sig(s) for s in sources}
    tsig = {t: _sig(t) for t in targets}
    relevant, irrelevant, overlap = {}, {}, {}
    for t in targets:
        scored = sorted(((_overlap(tsig[t], ssig[s]), s) for s in sources),
                        key=lambda kv: (-kv[0], _key("rel", t, kv[1])))
        relevant[t] = scored[0][1]
        overlap[t] = round(scored[0][0], 4)
        tlen = memory_len.get(relevant[t], 0)
        zero = [s for ov, s in scored if ov == 0.0] or [s for ov, s in scored[-15:]]
        irrelevant[t] = sorted(zero, key=lambda s: (abs(memory_len.get(s, 0) - tlen), _key("irr", t, s)))[0]
    # derangement over the relevant assignment (no target keeps its own relevant source)
    order = sorted(targets, key=lambda t: _key("shuf", t))
    rel = [relevant[t] for t in order]
    rot = rel[1:] + rel[:1]
    shuffled = {}
    for t, s in zip(order, rot):
        if s == relevant[t]:
            s = rel[(rel.index(s) + 2) % len(rel)]
        shuffled[t] = s
    return {"relevant": relevant, "irrelevant": irrelevant, "shuffled": shuffled,
            "relevance_overlap": overlap,
            "source_sig": {s: {k: sorted(v) for k, v in ssig[s].items()} for s in sources}}


def labels_hash(labels):
    payload = {k: labels[k] for k in ("relevant", "irrelevant", "shuffled")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
