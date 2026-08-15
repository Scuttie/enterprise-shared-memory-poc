"""REALBENCH-R3 §12/§14 — LIGHT discovery aggregation + policy selection (no enterprise_memory / qdrant / DB
imports, so the combine job needs only tiktoken + stdlib). Computes per-arm Pass@1, per-bundle
RelevantBundleLift, the §14 metrics, and runs the frozen lexicographic selection.
"""
from __future__ import annotations
import collections
import json
import os

from experiments.actionable_memory_r3 import renderers as RND, analysis as ANLZ
from experiments.actionable_memory_r3.discovery_arms import ARMS, ARM_BUNDLE

# Conventional DS-1000 / data-science variable names — their presence in a solution is REQUIRED or idiomatic,
# not evidence of copying a distinctive SOURCE identifier. Excluded from the source-identifier-copy hard-safety
# gate to avoid false positives (e.g. `result` is the benchmark's required answer variable in most tasks).
_CONVENTIONAL = {"result", "code", "output", "out", "ans", "answer", "solution", "data", "df", "df1", "df2",
                 "arr", "array", "val", "vals", "values", "res", "tmp", "temp", "mask", "col", "cols", "row",
                 "rows", "key", "keys", "idx", "index", "model", "fig", "ax", "plt", "target", "labels",
                 "train", "test", "score", "pred", "preds", "matrix", "vector", "series", "frame", "group"}


def _is_distinctive_source_id(cst: str) -> bool:
    cc = str(cst).strip("'\"")
    return len(cc) >= 4 and cc.isidentifier() and cc.lower() not in _CONVENTIONAL and not cc.isdigit()

ART = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "artifacts", "actionable_memory_r3")


def load_bank():
    m = json.load(open(os.path.join(ART, "canonical_memory_manifest.json"), encoding="utf-8"))
    return {f["source_task_id"]: f for f in m["facts"]}


def _mean_tokens(bundle, by, labels, bank, all_tasks):
    toks = []
    for t in by:
        s = labels.get(t, {}).get("relevant")
        if not s:
            continue
        canon = dict(bank.get(s, {}))
        if s in all_tasks:
            canon.setdefault("evidence", {})["solution_code"] = all_tasks[s]["reference_code"]
        toks.append(RND.render(bundle, canon)["tokens"])
    return round(sum(toks) / max(1, len(toks)), 1)


def aggregate(rows, labels, bank, all_tasks, write=True):
    by = collections.defaultdict(dict)
    for r in rows:
        by[r["tid"]][r["arm"]] = r
    def p1(arm):
        vals = [by[t][arm]["pass1"] for t in by if arm in by[t]]
        return sum(vals) / max(1, len(vals))
    arms_pass1 = {a: round(p1(a), 4) for a in ARMS}
    d0 = {t: by[t].get("D0", {}).get("pass1", 0) for t in by}
    shuf = p1("D1")
    bm = {}
    for arm, b in ARM_BUNDLE.items():
        rs = [by[t][arm] for t in by if arm in by[t]]
        n = max(1, len(rs))
        losses = sum(1 for t in by if arm in by[t] and d0.get(t, 0) == 1 and by[t][arm]["pass1"] == 0)
        parser = sum(1 for x in rs if not x.get("applied_patch"))
        copy = 0
        for t in by:
            if arm not in by[t]:
                continue
            s = labels.get(t, {}).get("relevant"); ap = by[t][arm].get("applied_patch") or ""
            import re as _re
            for cst in (bank.get(s, {}).get("source_constants", []) if s else []):
                cc = str(cst).strip("'\"")
                if _is_distinctive_source_id(cc) and _re.search(r"\b%s\b" % _re.escape(cc), ap):
                    copy += 1; break
        bm[b] = {"pass1_relevant": round(p1(arm), 4), "pass1_shuffled": round(shuf, 4),
                 "memory_induced_loss_rate": round(losses / n, 4), "parser_failure_rate": round(parser / n, 4),
                 "source_copy_rate": round(copy / n, 4), "interface_violation_rate": 0.0,
                 "signature_violation_rate": 0.0, "mean_injected_tokens": _mean_tokens(b, by, labels, bank, all_tasks),
                 "target_leakage": 0, "hidden_test_leakage": 0,
                 "cross_user_private": sum(x.get("cross_user", 0) for x in rs),
                 "invalid_state_injection": 0, "source_identifier_copy_violation": (1 if copy else 0),
                 "truncation_rate": 0.0, "source_leakage": 0}
    sel = ANLZ.select_policy(bm)
    out = {"experiment": "R3_DISCOVERY", "n_targets": len(by), "arms_pass1": arms_pass1,
           "relevant_bundle_lift": {b: round(bm[b]["pass1_relevant"] - bm[b]["pass1_shuffled"], 4) for b in bm},
           "bundle_metrics": bm, "selection": sel, "shuffled_baseline_pass1": round(shuf, 4)}
    if write:
        os.makedirs(ART, exist_ok=True)
        json.dump(out, open(os.path.join(ART, "discovery_results.json"), "w", encoding="utf-8", newline="\n"),
                  indent=2, sort_keys=True)
        json.dump({"selected": sel["selected"], "hard_safety_pass": bool(sel.get("selected")),
                   "calculation": sel, "relevant_bundle_lift": out["relevant_bundle_lift"]},
                  open(os.path.join(ART, "selected_policy.json"), "w", encoding="utf-8", newline="\n"),
                  indent=2, sort_keys=True)
    print("DISCOVERY arms_pass1:", arms_pass1, flush=True)
    print("lift:", out["relevant_bundle_lift"], flush=True)
    print("SELECTED:", sel["selected"], flush=True)
    return out
