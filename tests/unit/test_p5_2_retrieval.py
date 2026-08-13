"""P5.2 §3 — competitive retrieval + frozen abstention rule (model-free, deterministic). Reproduces the
threshold selection and locks it to the committed retrieval_thresholds.json; verifies the pool is competitive
(not a cell-isolated singleton), the rule separates relevant vs no-match, and the predeclared objective holds."""
import json
import os

from experiments.p5_2 import retrieval as R
from enterprise_memory.indexing.embeddings import DeterministicTestEmbedder

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
THR = os.path.join(ROOT, "artifacts", "experiments", "p5_2", "retrieval_thresholds.json")


def _emb():
    return DeterministicTestEmbedder(R.DIM)


def test_pool_is_competitive_not_singleton():
    dev = R.build_dev("retrieval_dev", 32, 16)
    rel = [q for q in dev if q["has_relevant"]][0]
    nomatch = [q for q in dev if not q["has_relevant"]][0]
    assert len(rel["candidates"]) == 8 and sum(c["relevant"] for c in rel["candidates"]) == 1
    assert sum(c["label"] == "near_miss" for c in rel["candidates"]) == 3
    assert sum(c["label"] == "irrelevant" for c in rel["candidates"]) == 4
    assert len(nomatch["candidates"]) == 8 and sum(c["relevant"] for c in nomatch["candidates"]) == 0


def test_selection_matches_frozen_thresholds():
    thr = json.load(open(THR, encoding="utf-8"))
    dev = R.build_dev("retrieval_dev", thr["pool"]["n_relevant"], thr["pool"]["n_nomatch"])
    sel, _ = R.select_thresholds(dev, _emb())
    assert sel["tau_abs"] == thr["tau_abs"] and sel["tau_margin"] == thr["tau_margin"]


def test_objective_satisfied_and_no_false_injection():
    thr = json.load(open(THR, encoding="utf-8"))
    dev = R.build_dev("retrieval_dev", thr["pool"]["n_relevant"], thr["pool"]["n_nomatch"])
    m = R.metrics(dev, _emb(), thr["tau_abs"], thr["tau_margin"])
    assert m["recall"] >= 0.90 and m["no_match_specificity"] >= 0.80
    assert m["false_injection_rate"] == 0.0 and m["precision"] == 1.0 and m["mrr"] == 1.0


def test_rule_injects_relevant_abstains_nomatch():
    thr = json.load(open(THR, encoding="utf-8"))
    ta, tm = thr["tau_abs"], thr["tau_margin"]
    emb = _emb()
    dev = R.build_dev("retrieval_dev", 32, 16)
    rel = [q for q in dev if q["has_relevant"]]
    nm = [q for q in dev if not q["has_relevant"]]
    inj_rel = sum(R.decide(R.score_pool(emb, q), ta, tm)["inject"] for q in rel)
    inj_nm = sum(R.decide(R.score_pool(emb, q), ta, tm)["inject"] for q in nm)
    assert inj_rel >= 0.90 * len(rel)          # relevant queries inject
    assert inj_nm == 0                          # no-match queries abstain (zero false injection)
