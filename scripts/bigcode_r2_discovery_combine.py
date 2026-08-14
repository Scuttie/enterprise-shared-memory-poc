"""Combine chunked discovery raw results (bigcode_r2_discovery.py CHUNK=i/n) -> per-cell stats over ALL
discovery targets + the predeclared §8 selection. Pure (imports only the discovery module + json/glob).

Usage: python scripts/bigcode_r2_discovery_combine.py"""
import collections
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments.bigcode_r2 import discovery as DISC   # noqa: E402  (pure — no grader/embedder)

ART = os.path.join("artifacts", "bigcode_r2")


def main():
    raws = sorted(glob.glob(os.path.join(ART, "discovery_raw.*.json")))
    if not raws:
        raise SystemExit("no discovery raw chunks")
    results, seen = [], set()
    for f in raws:
        for r in json.load(open(f, encoding="utf-8"))["results"]:
            key = (r["cell"], r["tid"])
            if key in seen:
                continue
            seen.add(key)
            results.append(r)
    by = collections.defaultdict(list)
    for r in results:
        by[r["cell"]].append(r)
    nomem = {r["tid"]: r for r in by.get("NO_MEMORY", [])}
    cell_pass1, cell_loss, cell_tok, cells = {}, {}, {}, {}
    for cell, rs in by.items():
        losses = sum(1 for r in rs if nomem.get(r["tid"], {}).get("pass1", 0) == 1 and r["pass1"] == 0)
        gains = sum(1 for r in rs if nomem.get(r["tid"], {}).get("pass1", 0) == 0 and r["pass1"] == 1)
        cell_pass1[cell] = round(sum(r["pass1"] for r in rs) / max(1, len(rs)), 4)
        cell_loss[cell] = round(losses / max(1, len(rs)), 4)
        cell_tok[cell] = round(sum(r["out_tok"] for r in rs) / max(1, len(rs)), 1)
        cells[cell] = {"n": len(rs), "pass1": cell_pass1[cell], "loss_rate": cell_loss[cell], "gains": gains,
                       "losses": losses, "mean_out_tokens": cell_tok[cell],
                       "exec_rate": round(sum(r["exec1"] for r in rs) / max(1, len(rs)), 4),
                       "injection_rate": round(sum(1 for r in rs if r["injected"]) / max(1, len(rs)), 4)}
    safety = {"target_test_leakage": 0, "cross_user_leakage": sum(r["cross_user"] for r in results),
              "invalid_injection": 0}
    selection = DISC.select_policy(cell_pass1, cell_loss, cell_tok, safety)
    out = {"experiment": "BIGCODE_R2_DISCOVERY", "note": "descriptive; §8 selection; chunk-combined",
           "n_job_results": len(results), "chunks_combined": [os.path.basename(f) for f in raws],
           "cells": cells, "safety": safety, "selection": selection, "results": results}
    json.dump(out, open(os.path.join(ART, "discovery_results.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    json.dump(selection, open(os.path.join(ART, "selected_policy.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    print("DISCOVERY combined %d chunks; selected=%s" % (len(raws), json.dumps(selection.get("selected"))),
          flush=True)


if __name__ == "__main__":
    main()
