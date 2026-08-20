#!/usr/bin/env python3
"""R15 — rebuild M1 by SEMANTIC retrieval using the product's own embedder (multi-qa-MiniLM-L6-cos-v1, 384-dim,
the same model enterprise_memory/backends/mem0_backend.py uses), instead of R14's recency pick. For each of the
frozen main-60 targets, embed the target's problem_statement (ISSUE TEXT ONLY — no gold, no leakage) and cosine-
rank all EARLIER same-repo issues; take top-1 as the relevant M1 source. Emit memory_M1_sem.json (raw worked-
example: source problem + real gold diff, identical format to R14) and an audit of the relevance gain. M0 and M2
from R14 are reused unchanged (target set and those arms are independent of how M1's source is chosen)."""
import os, sys, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import pandas as pd
from sentence_transformers import SentenceTransformer
import numpy as np

SP = os.path.expanduser("C:/Users/jewon/AppData/Local/Temp/claude/g-----------PC----2026-1-------/"
                        "3ac33feb-5c89-4bf4-84af-fb1563bea476/scratchpad")
df = pd.read_parquet(SP + "/swebv2.parquet")
df["ts"] = pd.to_datetime(df["created_at"]).astype("int64")
INFO = {r["instance_id"]: r for _, r in df.iterrows()}
byrepo = {r: g.sort_values("ts") for r, g in df.groupby("repo")}


def files_of(p):
    return set(re.findall(r"diff --git a/(\S+) b/\S+", str(p or "")))


def raw_mem(sid, tag):
    p = str(INFO[sid]["problem_statement"])[:3500]
    d = str(INFO[sid]["patch"])[:4000]
    return ("A real prior resolved issue in this repository (%s) and the ACTUAL fix that was applied:\n\n"
            "--- prior issue ---\n%s\n\n--- the fix (unified diff that resolved it) ---\n%s" % (tag, p, d))


def main():
    main60 = json.load(open("configs/swebench_r14/main_targets.json"))["ids"]
    old = json.load(open("artifacts/swebench_r14/main_partition.json", encoding="utf-8"))["assignments"]
    model = SentenceTransformer("multi-qa-MiniLM-L6-cos-v1")

    # gather all texts to embed once
    def emb(texts):
        return model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)

    M1 = {}; assign = {}; gains = []
    for tgt in main60:
        row = INFO[tgt]; repo = row["repo"]; ts = row["ts"]
        cand = [s for s in byrepo[repo][byrepo[repo]["ts"] < ts]["instance_id"] if s != tgt]
        if not cand:
            continue
        tq = str(row["problem_statement"])[:2000]
        cvecs = emb([str(INFO[s]["problem_statement"])[:2000] for s in cand])
        tvec = emb([tq])[0]
        sims = cvecs @ tvec
        top = cand[int(np.argmax(sims))]
        M1[tgt] = raw_mem(top, "same repository, semantically retrieved")
        # relevance audit vs old recency pick
        tf = files_of(row["patch"])
        newf = files_of(INFO[top]["patch"]); oldf = files_of(INFO[old[tgt]["m1_source"]]["patch"])
        def j(a, b):
            return len(a & b) / len(a | b) if (a or b) else 0.0
        gains.append({"tgt": tgt, "sem_source": top, "old_source": old[tgt]["m1_source"],
                      "sem_cos": float(sims.max()), "sem_shares_file": int(len(tf & newf) >= 1),
                      "old_shares_file": int(len(tf & oldf) >= 1),
                      "sem_file_j": round(j(tf, newf), 4), "old_file_j": round(j(tf, oldf), 4)})
        assign[tgt] = {"m1_source_semantic": top, "m1_source_recency_old": old[tgt]["m1_source"],
                       "sem_cos": round(float(sims.max()), 4), "repo": repo}

    json.dump(M1, open("artifacts/swebench_r14/memory_M1_sem.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump({"n": len(assign), "embedder": "multi-qa-MiniLM-L6-cos-v1", "assignments": assign},
              open("artifacts/swebench_r14/sem_partition.json", "w", encoding="utf-8"), indent=1, default=str)
    json.dump(gains, open("artifacts/swebench_r14/sem_relevance_gain.json", "w", encoding="utf-8"), indent=1)

    n = len(gains)
    print("R15 semantic M1 built for %d/%d main-60 targets (embedder multi-qa-MiniLM-L6-cos-v1)" % (n, len(main60)))
    print("shares >=1 gold file with target:  semantic=%.1f%%  vs  recency(old)=%.1f%%"
          % (100 * sum(g["sem_shares_file"] for g in gains) / n, 100 * sum(g["old_shares_file"] for g in gains) / n))
    print("patched-file Jaccard (audit):      semantic=%.3f  vs  recency(old)=%.3f"
          % (sum(g["sem_file_j"] for g in gains) / n, sum(g["old_file_j"] for g in gains) / n))
    print("mean top-1 cosine similarity:      %.3f" % (sum(g["sem_cos"] for g in gains) / n))
    changed = sum(1 for g in gains if g["sem_source"] != g["old_source"])
    print("M1 source CHANGED vs recency:      %d/%d (%.0f%%)" % (changed, n, 100 * changed / n))


if __name__ == "__main__":
    main()
