"""P5.2 §3 — competitive retrieval + frozen abstention rule. Model-free: candidate ranking is the vector
embedder's cosine similarity; relevance is engineered through domain + technique-family-tag token overlap so a
realistic pool separates (relevant > same-domain near-miss > cross-technique irrelevant). Deterministic.

Frozen decision rule: inject top-1 ONLY when
    top1_score >= tau_abs  AND  (top1_score - top2_score) >= tau_margin
otherwise ABSTAIN. tau_abs / tau_margin are selected on the retrieval-dev split ONLY, then frozen."""
from __future__ import annotations
import hashlib
from enterprise_memory.indexing.embeddings import DeterministicTestEmbedder

DIM = 128
QUERY_TAG_REPEAT = 8         # frozen embedding-signal weights (chosen so the deterministic bag-of-tokens
MEM_TAG_REPEAT = 10          # embedder separates relevant / same-domain near-miss / cross-domain cleanly)
DOMAINS = ("internal_api", "cache", "config", "schema")

# domain vocabulary (6 tokens) shared by every memory in a domain -> same-domain near-misses partially overlap
_DOMAIN_VOCAB = {
    "internal_api": "retry backoff attempt request timeout idempotency",
    "cache": "cache ttl tier eviction lookup invalidation",
    "config": "config precedence branch environment override profile",
    "schema": "schema field normalization mapping version compatibility",
}


def _tag(split, domain, family_idx):
    return "technique_%s_%s_%d" % (domain, hashlib.sha256(split.encode()).hexdigest()[:4], family_idx)


def _mem_text(domain, tag, extra="convention applies_when edge case branch"):
    # the tag is repeated so a single technique-family match dominates the shared-domain baseline
    return "%s %s %s" % (_DOMAIN_VOCAB[domain], " ".join([tag] * MEM_TAG_REPEAT), extra)


def _query_text(domain, tag):
    return "%s %s task edit function implement" % (_DOMAIN_VOCAB[domain], " ".join([tag] * QUERY_TAG_REPEAT))


def build_dev(split="retrieval_dev", n_relevant=32, n_nomatch=16):
    """Return a list of queries. Each has 8 candidates that all pass hard org/repo/path/state gates:
    a relevant query pool = 1 relevant + 3 same-domain near-miss + 4 cross-technique irrelevant; a no-match
    query pool = 0 relevant + 4 same-domain near-miss + 4 cross-technique irrelevant."""
    out = []
    for i in range(n_relevant + n_nomatch):
        domain = DOMAINS[i % 4]
        has_rel = i < n_relevant
        qtag = _tag(split, domain, i)
        cands = []
        if has_rel:
            cands.append({"label": "relevant", "relevant": True, "text": _mem_text(domain, qtag)})
        # same-domain near-miss (different technique tag)
        n_near = 3 if has_rel else 4
        for k in range(n_near):
            cands.append({"label": "near_miss", "relevant": False,
                          "text": _mem_text(domain, _tag(split, domain, 1000 + i * 10 + k))})
        # cross-technique irrelevant (different domain)
        for k in range(4):
            od = DOMAINS[(i + 1 + k) % 4]
            cands.append({"label": "irrelevant", "relevant": False,
                          "text": _mem_text(od, _tag(split, od, 5000 + i * 10 + k))})
        out.append({"query": _query_text(domain, qtag), "domain": domain, "has_relevant": has_rel,
                    "candidates": cands})
    return out


def score_pool(embedder, q):
    qv = embedder.embed([q["query"]])[0]
    cvs = embedder.embed([c["text"] for c in q["candidates"]])
    scored = []
    for c, cv in zip(q["candidates"], cvs):
        scored.append((sum(a * b for a, b in zip(qv, cv)), c))
    scored.sort(key=lambda t: -t[0])
    return scored                      # list of (score, candidate) descending


def decide(scored, tau_abs, tau_margin):
    top1 = scored[0][0]
    top2 = scored[1][0] if len(scored) > 1 else 0.0
    inject = (top1 >= tau_abs) and ((top1 - top2) >= tau_margin)
    return {"inject": inject, "top1": top1, "top2": top2, "margin": top1 - top2,
            "top1_relevant": bool(scored[0][1]["relevant"])}


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
            elif d["inject"] and not d["top1_relevant"]:
                fn += 1; inj_total += 1                       # injected the wrong one
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
    f1_inj = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    p_abs = tn / (tn + fn) if (tn + fn) else 1.0
    r_abs = tn / (tn + fp) if (tn + fp) else 1.0
    f1_abs = (2 * p_abs * r_abs / (p_abs + r_abs)) if (p_abs + r_abs) else 0.0
    n = len(dev)
    return {"precision": precision, "recall": recall, "no_match_specificity": specificity,
            "false_injection_rate": (fp / (fp + tn) if (fp + tn) else 0.0),
            "mrr": (sum(rr) / len(rr) if rr else 0.0), "mean_margin": (sum(margins) / len(margins)),
            "abstention_rate": ((tn + (fn if False else 0)) + (n - inj_total)) / n if n else 0.0,
            "macro_f1": (f1_inj + f1_abs) / 2, "tp": tp, "fn": fn, "fp": fp, "tn": tn,
            "injections": inj_total}


TAU_ABS_GRID = [round(0.30 + 0.05 * i, 2) for i in range(11)]      # 0.30..0.80
TAU_MARGIN_GRID = [round(0.05 + 0.05 * i, 2) for i in range(10)]   # 0.05..0.50


def select_thresholds(dev, embedder, recall_min=0.90, spec_min=0.80):
    """Predeclared objective: (1) recall>=0.90; (2) no-match specificity>=0.80; (3) among feasible maximise
    macro F1; (4) deterministic tie-break larger tau_abs then larger tau_margin."""
    grid = []
    feasible = []
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
    best = feasible[0]
    return {"tau_abs": best["tau_abs"], "tau_margin": best["tau_margin"]}, grid
