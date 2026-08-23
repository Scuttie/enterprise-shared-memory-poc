#!/usr/bin/env python3
"""R14 relevance audit (post-hoc, no API/Docker). Was the M1 source ("same-repo temporally-nearest resolved
issue") actually TOPICALLY relevant to its target, or only same-repo? Measures source<->target overlap on: patched
files (Jaccard), shared top-dir, problem-statement token Jaccard, patch token Jaccard. Compares M1 vs M2, and
stratifies M1-M0 / M1-M2 lift by whether M1 shared >=1 patched file with the target's gold. Uses ONLY frozen data
already produced (the target gold patch is used for AUDIT ONLY, never entered any agent context)."""
import os, sys, io, json, glob, re, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import pandas as pd

# scratch data root; override with ESM_SCRATCH (was a hardcoded local path — see reports/OSS_V03_WORKFLOW_TRIGGER_AUDIT.md D-2)
SP = os.environ.get("ESM_SCRATCH") or os.path.join(tempfile.gettempdir(), "claude_scratchpad")
df = pd.read_parquet(SP + "/swebv2.parquet")
INFO = {r["instance_id"]: r for _, r in df.iterrows()}

STOP = set("the a an and or of to in is for with that this it be on as by from at are was not you your can if".split())


def files_of(patch):
    return set(re.findall(r"diff --git a/(\S+) b/\S+", str(patch or "")))


def topdir(fs):
    return set(f.split("/")[0] + "/" + (f.split("/")[1] if "/" in f[len(f.split('/')[0]) + 1:] else "") for f in fs)


def toks(t):
    return set(w for w in re.findall(r"[a-zA-Z_][a-zA-Z_0-9]{2,}", str(t or "").lower()) if w not in STOP)


def jacc(a, b):
    return round(len(a & b) / len(a | b), 4) if (a or b) else 0.0


def load_arm(base, arm):
    d = {}
    for f in glob.glob("%s/%s/*.json" % (base, arm)):
        if f.endswith(".patch"):
            continue
        r = json.load(open(f, encoding="utf-8"))
        d[r["instance_id"]] = r.get("resolved") is True
    return d


def main():
    assign = {}
    for pf in ["artifacts/swebench_r14/main_partition.json", "artifacts/swebench_r14/confirm_partition.json"]:
        assign.update(json.load(open(pf, encoding="utf-8"))["assignments"])
    arms = {}
    for a in ["M0", "M1", "M2"]:
        arms[a] = {**load_arm("artifacts/swebench_r14/arms", a),
                   **load_arm("artifacts/swebench_r14/arms_confirm", a)}
    rows = []
    for tgt, a in assign.items():
        if tgt not in arms["M1"]:
            continue
        tp = INFO[tgt]["patch"]; tf = files_of(tp); tprob = toks(INFO[tgt]["problem_statement"])
        rec = {"tgt": tgt}
        for tag, sid in [("m1", a["m1_source"]), ("m2", a.get("m2_source"))]:
            if not sid or sid not in INFO:
                rec[tag + "_file_j"] = None; continue
            sf = files_of(INFO[sid]["patch"])
            rec[tag + "_file_j"] = jacc(tf, sf)
            rec[tag + "_shared_files"] = len(tf & sf)
            rec[tag + "_topdir_j"] = jacc(topdir(tf), topdir(sf))
            rec[tag + "_prob_j"] = jacc(tprob, toks(INFO[sid]["problem_statement"]))
            rec[tag + "_patch_j"] = jacc(toks(tp), toks(INFO[sid]["patch"]))
        rec["M0"] = arms["M0"].get(tgt); rec["M1"] = arms["M1"].get(tgt); rec["M2"] = arms["M2"].get(tgt)
        rows.append(rec)

    import statistics as st
    def med(key):
        vs = [r[key] for r in rows if r.get(key) is not None]
        return round(st.median(vs), 4), round(sum(vs) / len(vs), 4)
    print("N audited =", len(rows))
    print("\n=== Is M1 ('same-repo nearest') actually more relevant to the TARGET than M2 (cross-repo)? ===")
    print("%-18s %-16s %-16s" % ("overlap metric", "M1 (relevant?)", "M2 (control)"))
    for label, k in [("patched-file Jacc", "file_j"), ("shared file count", "shared_files"),
                     ("top-dir Jacc", "topdir_j"), ("problem-text Jacc", "prob_j"), ("patch-text Jacc", "patch_j")]:
        m1 = med("m1_" + k); m2 = med("m2_" + k)
        print("%-18s med=%-.3f avg=%-.3f  med=%-.3f avg=%-.3f" % (label, m1[0], m1[1], m2[0], m2[1]))

    share1 = [r for r in rows if (r.get("m1_shared_files") or 0) >= 1]
    print("\nM1 sources sharing >=1 patched file with the target's gold: %d / %d = %.1f%%"
          % (len(share1), len(rows), 100 * len(share1) / len(rows)))
    m2share1 = sum(1 for r in rows if (r.get("m2_shared_files") or 0) >= 1)
    print("M2 (cross-repo) same: %d / %d = %.1f%%" % (m2share1, len(rows), 100 * m2share1 / len(rows)))

    def rate(sub, arm):
        vs = [r[arm] for r in sub if r.get(arm) is not None]
        return (round(sum(vs) / len(vs), 4), sum(vs), len(vs)) if vs else (None, 0, 0)
    print("\n=== Stratify M1 lift by whether the M1 memory was actually relevant (shared file) ===")
    for name, sub in [("RELEVANT (M1 shares >=1 file)", share1),
                      ("NOT relevant (M1 shares 0 files)", [r for r in rows if (r.get("m1_shared_files") or 0) == 0])]:
        r0, r1, r2 = rate(sub, "M0"), rate(sub, "M1"), rate(sub, "M2")
        print("%-34s n=%-3d  M0=%.3f  M1=%.3f  M2=%.3f  | M1-M0=%+.3f  M1-M2=%+.3f"
              % (name, len(sub), r0[0] or 0, r1[0] or 0, r2[0] or 0,
                 (r1[0] or 0) - (r0[0] or 0), (r1[0] or 0) - (r2[0] or 0)))
    json.dump(rows, open("artifacts/swebench_r14/relevance_audit.json", "w", encoding="utf-8"), indent=1, default=str)


if __name__ == "__main__":
    main()
