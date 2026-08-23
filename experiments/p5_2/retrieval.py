"""P5.2 §3 — competitive retrieval + frozen abstention rule. The retrieval-dev split is REPRESENTATIVE: its
candidate texts are the SAME governed-contract retrieval projections used in the experiment bank, and its query
is the same task instruction, so thresholds selected here transfer to calibration/main. Model-free,
deterministic. Frozen rule: inject top-1 iff top1>=tau_abs AND (top1-top2)>=tau_margin, else abstain."""
from __future__ import annotations
from enterprise_memory.indexing.embeddings import DeterministicTestEmbedder
from enterprise_memory.contracts import codec
from . import tokens as T

DIM = T.DIM
DOMAINS = T.DOMAINS
QUERY_TAG_REPEAT = T.QUERY_TAG_REPEAT
MEM_TAG_REPEAT = T.MEM_TAG_REPEAT

DEV_SPLIT = "retrieval_dev"
DEV_N = 8                      # 32 dev families (disjoint from calibration/main/instrument_dev by split name)


def _dev_families():
    from benchmarks.p5_2_static import generate
    return generate(DEV_SPLIT, DEV_N)


def _relevant_text(family):
    from . import memory_bank as MB
    ct, _ = MB.governed_relevant("o", "r", family, form="shared_governed")
    return codec.retrieval_text(MB.canonical_of(ct))


def _decoy_text(domain, tag):
    from . import memory_bank as MB
    return codec.retrieval_text(MB.canonical_of(MB.decoy_contract("o", "r", domain, tag)))


def build_dev(n_relevant=24, n_nomatch=8):
    """Representative dev queries. relevant-query pool = 1 relevant + 3 same-domain near-miss + 4 cross-domain
    irrelevant; no-match pool = 0 relevant + 4 near-miss + 4 irrelevant. All pass hard metadata gates."""
    from . import plan as PLAN
    fams = _dev_families()
    by_domain = {d: [f for f in fams if f.domain == d] for d in DOMAINS}
    out = []
    for i in range(n_relevant + n_nomatch):
        domain = DOMAINS[i % 4]
        pool_fams = by_domain[domain]
        f = pool_fams[(i // 4) % len(pool_fams)]
        has_rel = i < n_relevant
        query = PLAN.instruction_for(f)
        cands = []
        if has_rel:
            cands.append({"label": "relevant", "relevant": True, "text": _relevant_text(f)})
        n_near = 3 if has_rel else 4
        for k in range(n_near):
            nf = pool_fams[(i // 4 + 1 + k) % len(pool_fams)]
            cands.append({"label": "near_miss", "relevant": False, "text": _relevant_text(nf)})
        others = [d for d in DOMAINS if d != domain]
        for k in range(4):
            od = others[k % len(others)]
            cands.append({"label": "irrelevant", "relevant": False,
                          "text": _decoy_text(od, T.tag(DEV_SPLIT + "irr", od, i * 10 + k))})
        out.append({"query": query, "domain": domain, "has_relevant": has_rel, "candidates": cands})
    return out


def score_pool(embedder, q):
    qv = embedder.embed([q["query"]])[0]
    cvs = embedder.embed([c["text"] for c in q["candidates"]])
    return sorted([(sum(a * b for a, b in zip(qv, cv)), c) for c, cv in zip(q["candidates"], cvs)],
                 key=lambda t: -t[0])


def decide(scored, tau_abs, tau_margin):
    top1 = scored[0][0]
    top2 = scored[1][0] if len(scored) > 1 else 0.0
    return {"inject": (top1 >= tau_abs) and ((top1 - top2) >= tau_margin), "top1": top1, "top2": top2,
            "margin": top1 - top2, "top1_relevant": bool(scored[0][1]["relevant"])}


def _rank_of_relevant(scored):
    for r, (_, c) in enumerate(scored, start=1):
        if c["relevant"]:
            return r
    return 0


def metrics(dev, embedder, tau_abs, tau_margin):
    tp = fn = fp = tn = 0
    inj_total = inj_correct = 0
    rr, margins = [], []
    for q in dev:
        scored = score_pool(embedder, q)
        d = decide(scored, tau_abs, tau_margin)
        margins.append(d["margin"])
        if q["has_relevant"]:
            rr.append(1.0 / _rank_of_relevant(scored))
            if d["inject"] and d["top1_relevant"]:
                tp += 1; inj_total += 1; inj_correct += 1
            elif d["inject"]:
                fn += 1; inj_total += 1
            else:
                fn += 1
        else:
            if d["inject"]:
                fp += 1; inj_total += 1
            else:
                tn += 1
    precision = inj_correct / inj_total if inj_total else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    specificity = tn / (tn + fp) if (tn + fp) else 1.0
    f1_i = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    p_a = tn / (tn + fn) if (tn + fn) else 1.0
    r_a = tn / (tn + fp) if (tn + fp) else 1.0
    f1_a = (2 * p_a * r_a / (p_a + r_a)) if (p_a + r_a) else 0.0
    n = len(dev)
    return {"precision": precision, "recall": recall, "no_match_specificity": specificity,
            "false_injection_rate": (fp / (fp + tn) if (fp + tn) else 0.0),
            "mrr": (sum(rr) / len(rr) if rr else 0.0), "mean_margin": (sum(margins) / len(margins)),
            "abstention_rate": (n - inj_total) / n if n else 0.0, "macro_f1": (f1_i + f1_a) / 2,
            "tp": tp, "fn": fn, "fp": fp, "tn": tn, "injections": inj_total}


TAU_ABS_GRID = [round(0.30 + 0.05 * i, 2) for i in range(11)]
TAU_MARGIN_GRID = [round(0.05 + 0.05 * i, 2) for i in range(10)]


def select_thresholds(dev, embedder, recall_min=0.90, spec_min=0.80):
    grid, feasible = [], []
    for ta in TAU_ABS_GRID:
        for tm in TAU_MARGIN_GRID:
            m = metrics(dev, embedder, ta, tm)
            row = {"tau_abs": ta, "tau_margin": tm, "recall": m["recall"],
                   "no_match_specificity": m["no_match_specificity"], "macro_f1": m["macro_f1"],
                   "false_injection_rate": m["false_injection_rate"]}
            grid.append(row)
            if m["recall"] >= recall_min and m["no_match_specificity"] >= spec_min:
                feasible.append(row)
    if not feasible:
        return None, grid
    feasible.sort(key=lambda r: (-r["macro_f1"], -r["tau_abs"], -r["tau_margin"]))
    b = feasible[0]
    return {"tau_abs": b["tau_abs"], "tau_margin": b["tau_margin"]}, grid
