#!/usr/bin/env python3
"""R18 — collective-intelligence-as-a-SET. Instead of one prior fix, inject the TOP-K (K=5) semantically-retrieved
same-repo prior fixes together (M1multi), vs K matched cross-repo prior fixes (M2multi control). Tests whether a
DISTRIBUTION of related experience (not a single anecdote) transfers. Product embedder (multi-qa-MiniLM-L6-cos-v1),
target ISSUE TEXT only (no gold leakage). Compact per-source (problem<=900, diff<=700) so K=5 fits the inject cap."""
import os, sys, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import pandas as pd
import numpy as np
from sentence_transformers import SentenceTransformer

SP = os.path.expanduser("C:/Users/jewon/AppData/Local/Temp/claude/g-----------PC----2026-1-------/"
                        "3ac33feb-5c89-4bf4-84af-fb1563bea476/scratchpad")
df = pd.read_parquet(SP + "/swebv2.parquet")
df["ts"] = pd.to_datetime(df["created_at"]).astype("int64")
INFO = {r["instance_id"]: r for _, r in df.iterrows()}
byrepo = {r: g.sort_values("ts") for r, g in df.groupby("repo")}
K = 5
import hashlib


def files_of(p):
    return set(re.findall(r"diff --git a/(\S+) b/\S+", str(p or "")))


def compact(sid, i):
    p = str(INFO[sid]["problem_statement"])[:900]
    d = str(INFO[sid]["patch"])[:700]
    return "### Prior resolved issue #%d\n%s\n--- fix applied ---\n%s" % (i, p, d)


def bundle(sids, tag):
    body = "\n\n".join(compact(s, i + 1) for i, s in enumerate(sids))
    return ("%d real prior resolved issues in this repository (%s), each with the actual fix applied — a set of "
            "worked examples, not this issue's solution:\n\n%s" % (len(sids), tag, body))


def main():
    main60 = json.load(open("configs/swebench_r14/main_targets.json"))["ids"]
    model = SentenceTransformer("multi-qa-MiniLM-L6-cos-v1")

    def emb(texts):
        return model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)

    M1 = {}; M2 = {}; audit = []
    allids = list(df["instance_id"])
    for tgt in main60:
        row = INFO[tgt]; repo = row["repo"]; ts = row["ts"]; tf = files_of(row["patch"])
        cand = [s for s in byrepo[repo][byrepo[repo]["ts"] < ts]["instance_id"] if s != tgt]
        if len(cand) < 1:
            continue
        tvec = emb([str(row["problem_statement"])[:2000]])[0]
        cvecs = emb([str(INFO[s]["problem_statement"])[:2000] for s in cand])
        order = list(np.argsort(-(cvecs @ tvec)))
        topk = [cand[i] for i in order[:K]]
        # control: K earlier cross-repo issues, deterministic
        pool = list(df[(df["repo"] != repo) & (df["ts"] < ts)]["instance_id"])
        ctrl = sorted(pool, key=lambda s: hashlib.sha256((tgt + s).encode()).hexdigest())[:K]
        M1[tgt] = bundle(topk, "same repository, semantically retrieved")
        M2[tgt] = bundle(ctrl, "different repositories, control")
        relshare = sum(1 for s in topk if len(tf & files_of(INFO[s]["patch"])) >= 1)
        audit.append({"tgt": tgt, "k": len(topk), "any_shares_file": int(relshare >= 1),
                      "n_share": relshare, "m1_len": len(M1[tgt]), "sources": topk})
    json.dump(M1, open("artifacts/swebench_r14/memory_M1_multi.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump(M2, open("artifacts/swebench_r14/memory_M2_multi.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump(audit, open("artifacts/swebench_r14/multi_audit.json", "w", encoding="utf-8"), indent=1)
    n = len(audit)
    import statistics as st
    print("R18 multi-memory built for %d/%d targets, K=%d" % (n, len(main60), K))
    print("targets whose TOP-5 set contains >=1 source sharing a gold file: %d/%d = %.1f%%"
          % (sum(a["any_shares_file"] for a in audit), n, 100 * sum(a["any_shares_file"] for a in audit) / n))
    print("  (single-source semantic was 15.0%%; a SET of 5 should cover more)")
    print("mean #of the 5 that share a gold file: %.2f" % (sum(a["n_share"] for a in audit) / n))
    print("M1multi injected length: median=%d max=%d chars" % (st.median([a["m1_len"] for a in audit]),
                                                               max(a["m1_len"] for a in audit)))


if __name__ == "__main__":
    main()
