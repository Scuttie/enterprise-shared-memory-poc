"""P5.2 §3 — select and FREEZE the retrieval abstention thresholds on EXP_P5_2_RETRIEVAL_DEV only. Model-free
and deterministic. Writes artifacts/experiments/p5_2/retrieval_thresholds.json (thresholds + full score grid +
metrics + embedder config). Run BEFORE any P5.2 model call; the seal test then locks it."""
import json
import os

from experiments.p5_2 import retrieval as R
from enterprise_memory.indexing.embeddings import DeterministicTestEmbedder

ART = os.path.join("artifacts", "experiments", "p5_2")
N_RELEVANT = 32
N_NOMATCH = 16


def main():
    emb = DeterministicTestEmbedder(R.DIM)
    dev = R.build_dev("retrieval_dev", N_RELEVANT, N_NOMATCH)
    sel, grid = R.select_thresholds(dev, emb)
    if sel is None:
        raise SystemExit("no feasible thresholds on retrieval-dev (recall>=0.90 AND specificity>=0.80)")
    m = R.metrics(dev, emb, sel["tau_abs"], sel["tau_margin"])
    out = {
        "split": "EXP_P5_2_RETRIEVAL_DEV",
        "embedder": {"model_id": emb.model_id, "dim": R.DIM, "query_tag_repeat": R.QUERY_TAG_REPEAT,
                     "mem_tag_repeat": R.MEM_TAG_REPEAT},
        "pool": {"relevant_query_pool": "1 relevant + 3 same-domain near-miss + 4 cross-technique irrelevant",
                 "no_match_query_pool": "0 relevant + 4 same-domain near-miss + 4 cross-technique irrelevant",
                 "n_relevant": N_RELEVANT, "n_nomatch": N_NOMATCH},
        "decision_rule": "inject top-1 iff top1>=tau_abs AND (top1-top2)>=tau_margin, else abstain",
        "objective": ["recall>=0.90", "no_match_specificity>=0.80", "maximise macro_f1",
                      "tie-break larger tau_abs then larger tau_margin"],
        "tau_abs": sel["tau_abs"], "tau_margin": sel["tau_margin"],
        "metrics": {k: m[k] for k in ("precision", "recall", "no_match_specificity", "false_injection_rate",
                                      "mrr", "mean_margin", "macro_f1", "abstention_rate")},
        "grid": grid,
    }
    os.makedirs(ART, exist_ok=True)
    with open(os.path.join(ART, "retrieval_thresholds.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=2, sort_keys=True); f.write("\n")
    print("FROZE retrieval thresholds: tau_abs=%s tau_margin=%s recall=%.3f spec=%.3f macro_f1=%.3f"
          % (sel["tau_abs"], sel["tau_margin"], m["recall"], m["no_match_specificity"], m["macro_f1"]))


if __name__ == "__main__":
    main()
