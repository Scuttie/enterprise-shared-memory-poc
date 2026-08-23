#!/usr/bin/env python3
"""REALBENCH-R11 — relevance candidates (no Solar). For each frozen TARGET, rank SOURCE_POOL problems by semantic
similarity of the problem statement using a PINNED embedder (sentence-transformers/all-MiniLM-L6-v2), so a
verified relevant source can later be chosen for M1/M3 and a matched-unrelated source for M2. Relevance is defined
here on PUBLIC problem statements only (title+content); it never uses any target solution or tests.

Emits artifacts/livecodebench_r11/target_source_candidates.json:
  { target_qid: {"topk":[{source_qid, sim, difficulty}], "difficulty":..., "platform":...} }
Env: R11_RELEASE, R11_TOPK. Deterministic (no randomness in embedding order).
"""
import os, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

RELEASE = os.environ.get("R11_RELEASE", "release_v6")
TOPK = int(os.environ.get("R11_TOPK", "10"))
EMBEDDER = "sentence-transformers/all-MiniLM-L6-v2"
EMB_REV = os.environ.get("R11_EMB_REV", "main")  # pin recorded in provenance

from lcb_runner.benchmarks.code_generation import load_code_generation_dataset
import numpy as np
from sentence_transformers import SentenceTransformer


def text_of(p):
    t = (getattr(p, "question_title", "") or "") + "\n" + (getattr(p, "question_content", "") or "")
    return t[:4000]


def main():
    part = json.load(open("artifacts/livecodebench_r11/task_partition.json", encoding="utf-8"))
    tset = set(part["main_target"]["ids"]); sset = set(part["source_pool"]["ids"])
    allp = load_code_generation_dataset(release_version=RELEASE)
    by_id = {p.question_id: p for p in allp}
    tgt = [q for q in part["main_target"]["ids"] if q in by_id]
    src = [q for q in part["source_pool"]["ids"] if q in by_id]
    diff = {q: str(getattr(by_id[q], "difficulty", "")) for q in tgt + src}
    plat = {q: str(getattr(by_id[q], "platform", "")) for q in tgt + src}

    model = SentenceTransformer(EMBEDDER)
    print("[R11] embedding %d source + %d target statements with %s" % (len(src), len(tgt), EMBEDDER))
    se = model.encode([text_of(by_id[q]) for q in src], normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    te = model.encode([text_of(by_id[q]) for q in tgt], normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    se = np.asarray(se); te = np.asarray(te)

    out = {}
    for i, tq in enumerate(tgt):
        sims = te[i] @ se.T  # cosine (normalized)
        order = np.argsort(-sims)[:TOPK]
        out[tq] = {"difficulty": diff[tq], "platform": plat[tq],
                   "topk": [{"source_qid": src[j], "sim": round(float(sims[j]), 4), "difficulty": diff[src[j]]}
                            for j in order]}
    meta = {"embedder": EMBEDDER, "embedder_revision": EMB_REV, "topk": TOPK,
            "n_target": len(tgt), "n_source": len(src),
            "relevance_definition": "cosine similarity of PINNED sentence embeddings over public title+content; no target solution/tests used",
            "candidates": out}
    os.makedirs("artifacts/livecodebench_r11", exist_ok=True)
    json.dump(meta, open("artifacts/livecodebench_r11/target_source_candidates.json", "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)
    print("[R11] wrote candidates for %d targets (top%d each)" % (len(out), TOPK))


if __name__ == "__main__":
    main()
