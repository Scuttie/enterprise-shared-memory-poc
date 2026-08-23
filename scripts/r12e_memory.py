#!/usr/bin/env python3
"""REALBENCH-R12-E — build SWE-PolyBench M1/M2/M3/M4 memory maps (frozen partition).

M1/M3: distil a plain + executable lesson from each target's frozen relevant SOURCE (source problem + source gold
patch) with gpt-4o-mini; the distilled lesson is target-free and contains NO gold patch verbatim; the target's
gold is never used. M2: plain lesson from the matched cross-repo source. M4: deployable retrieval — pinned
all-MiniLM embeds ONLY public target problem statements + source problem statements; nearest source above a frozen
abstention threshold contributes its plain lesson, else abstain (empty). No target solution/tests enter memory.

Env: OPENAI_API_KEY, R12E_CSV (Verified test.csv). Writes artifacts/swe_polybench_r12_openai/memory_{M1..M4}.json.
"""
import os, sys, io, json, time, urllib.request, urllib.error, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import pandas as pd

API_KEY = os.environ["OPENAI_API_KEY"]
BASE = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
CSV = os.environ["R12E_CSV"]
A = "artifacts/swe_polybench_r12_openai"
ABSTAIN = float(os.environ.get("R12E_ABSTAIN", "0.45"))


def gpt4omini(prompt, max_tokens=900):
    import random
    body = json.dumps({"model": "gpt-4o-mini-2024-07-18", "temperature": 0, "max_output_tokens": max_tokens,
                       "input": [{"role": "user", "content": prompt}]}).encode()
    last = None
    for attempt in range(6):
        try:
            req = urllib.request.Request(BASE + "/responses", data=body,
                headers={"Authorization": "Bearer %s" % API_KEY, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read())
            if isinstance(d.get("output_text"), str) and d["output_text"]:
                return d["output_text"]
            parts = []
            for it in d.get("output", []):
                for c in it.get("content", []) or []:
                    if c.get("type") in ("output_text", "text"):
                        parts.append(c.get("text", ""))
            return "".join(parts)
        except urllib.error.HTTPError as ex:
            last = "HTTP %s" % ex.code
            if ex.code in (429, 500, 502, 503, 504):
                time.sleep(min(40, 4 * (2 ** attempt)) + random.uniform(0, 3)); continue
            raise
        except Exception as ex:
            last = str(ex)[:100]; time.sleep(min(40, 4 * (2 ** attempt)) + random.uniform(0, 3))
    raise RuntimeError("gpt-4o-mini failed: %s" % last)


def distil(problem, patch):
    prompt = ("Below is a resolved software issue and its reference fix. Write reusable guidance for solving "
              "SIMILAR future issues in the same codebase. Do NOT reference any other specific issue and do NOT "
              "include the patch verbatim.\n\nReturn STRICT JSON with two keys:\n"
              '  "plain": 2-4 sentences — the root cause pattern, the fix technique, one pitfall, how to verify.\n'
              '  "executable": lines for Approach (ordered steps), Files/APIs to touch, Preconditions, Edge cases.\n\n'
              "### Issue\n" + str(problem)[:2500] + "\n\n### Reference fix (for your understanding only)\n"
              + str(patch)[:2500])
    out = gpt4omini(prompt)
    m = re.search(r"\{.*\}", out, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except Exception:
        d = {}
    plain = str(d.get("plain", "")).strip() or out.strip()[:500]
    ex = str(d.get("executable", "")).strip() or plain
    return plain, ex


def main():
    part = json.load(open(A + "/main_partition.json", encoding="utf-8"))
    asg = part["assignments"]
    df = pd.read_csv(CSV)
    prob = {r["instance_id"]: r["problem_statement"] for _, r in df.iterrows()}
    patch = {r["instance_id"]: r["patch"] for _, r in df.iterrows()}

    cache = {}

    def lessons(sid):
        if sid not in cache:
            cache[sid] = distil(prob.get(sid, ""), patch.get(sid, ""))
        return cache[sid]

    M1, M2, M3 = {}, {}, {}
    for i, (tq, a) in enumerate(asg.items()):
        pl, ex = lessons(a["m1_source"])
        M1[tq] = "### Lesson from a related earlier fix in this repository (guidance only)\n" + pl
        M3[tq] = "### Actionable procedure from a related earlier fix in this repository (guidance only)\n" + ex
        if a.get("m2_source"):
            pl2, _ = lessons(a["m2_source"])
            M2[tq] = "### Lesson from a related earlier fix in this repository (guidance only)\n" + pl2
        if (i + 1) % 10 == 0:
            print("[R12E] %d/%d targets, %d source lessons" % (i + 1, len(asg), len(cache)))

    # M4 deployable retrieval: pinned embedder over PUBLIC problem statements + abstention
    from sentence_transformers import SentenceTransformer
    import numpy as np
    emb = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    src_ids = sorted({a["m1_source"] for a in asg.values()} | {a["m2_source"] for a in asg.values() if a.get("m2_source")})
    tgt_ids = list(asg.keys())
    se = np.asarray(emb.encode([str(prob.get(s, ""))[:2000] for s in src_ids], normalize_embeddings=True))
    te = np.asarray(emb.encode([str(prob.get(t, ""))[:2000] for t in tgt_ids], normalize_embeddings=True))
    M4 = {}
    for i, tq in enumerate(tgt_ids):
        sims = te[i] @ se.T
        j = int(np.argmax(sims))
        if float(sims[j]) >= ABSTAIN:
            pl, _ = lessons(src_ids[j])
            M4[tq] = "### Retrieved lesson (deployable) from a similar earlier fix (guidance only)\n" + pl
        else:
            M4[tq] = ""  # abstain

    for name, mp in [("M1", M1), ("M2", M2), ("M3", M3), ("M4", M4)]:
        json.dump(mp, open("%s/memory_%s.json" % (A, name), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump({"n_targets": len(asg), "n_source_lessons": len(cache), "M4_abstain_threshold": ABSTAIN,
               "M4_injected": sum(1 for v in M4.values() if v), "M4_abstained": sum(1 for v in M4.values() if not v)},
              open(A + "/memory_build_summary.json", "w", encoding="utf-8"), indent=1)
    print("[R12E] memory built: %d targets, %d lessons, M4 injected=%d abstained=%d"
          % (len(asg), len(cache), sum(1 for v in M4.values() if v), sum(1 for v in M4.values() if not v)))


if __name__ == "__main__":
    main()
