#!/usr/bin/env python3
"""REALBENCH-R13 — representation (encoding) study. Encode each R11 verified source in FIVE formats F0-F4 via
gpt-4o-mini, then assemble per-target memory files for the {relevant, shuffled} × {F0..F4} panel. Source,
relevance mapping, targets, reader, benchmark are all held FIXED (reused from R11); ONLY the encoding varies.

F0 PLAIN_LESSON · F1 DEPENDENCY_API_CARD · F2 EXECUTABLE_PROCEDURE · F3 POS_NEG_CONTRAST · F4 MINIMAL_CODE_SKELETON.
Encodings are derived from the source problem + the reader's verified source solution; they are target-free and
never contain the target's solution/tests. Env: OPENAI_API_KEY, R13_RELEASE(release_v6).
"""
import os, sys, io, json, time, urllib.request, urllib.error, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
API_KEY = os.environ["OPENAI_API_KEY"]
BASE = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
RELEASE = os.environ.get("R13_RELEASE", "release_v6")
A = "artifacts/repr_r13"

FORMATS = {
 "F0": ('PLAIN_LESSON', 'Write a 2-4 sentence plain lesson: the key technique/idea, one common pitfall, and how to verify.'),
 "F1": ('DEPENDENCY_API_CARD', 'Write an API/dependency card: required APIs/libraries, preconditions, the ordered way to use them, interface constraints, one common misuse, and a verification check. No prose story.'),
 "F2": ('EXECUTABLE_PROCEDURE', 'Write a SOURCE-INDEPENDENT executable procedure: numbered pseudocode steps with explicit decision points and a verification step. Use NO identifiers/constants from the specific problem.'),
 "F3": ('POS_NEG_CONTRAST', 'Write a positive/negative contrast: (a) the correct reusable operation, (b) a matched INCORRECT operation people often write, (c) the discriminating condition that tells them apart, (d) a verification check.'),
 "F4": ('MINIMAL_CODE_SKELETON', 'Write a MINIMAL generalized code skeleton with placeholders and fixed interface constraints. Use NO source-specific identifiers or constants — only <PLACEHOLDER> names.'),
}


def gpt4omini(prompt, max_tokens=700):
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
            return "".join(c.get("text", "") for it in d.get("output", []) for c in (it.get("content") or [])
                           if c.get("type") in ("output_text", "text"))
        except urllib.error.HTTPError as ex:
            last = "HTTP %s" % ex.code
            if ex.code in (429, 500, 502, 503, 504):
                time.sleep(min(40, 4 * (2 ** attempt)) + random.uniform(0, 3)); continue
            raise
        except Exception as ex:
            last = str(ex)[:100]; time.sleep(min(40, 4 * (2 ** attempt)) + random.uniform(0, 3))
    raise RuntimeError("gpt-4o-mini failed: %s" % last)


def main():
    from lcb_runner.benchmarks.code_generation import load_code_generation_dataset
    asg = json.load(open(A + "/r13_assignments.json", encoding="utf-8"))
    solves = json.load(open("artifacts/livecodebench_r11/source_solves.json", encoding="utf-8"))
    allp = load_code_generation_dataset(release_version=RELEASE)
    prob = {p.question_id: (p.question_content or "") for p in allp}
    src_ids = asg["unique_sources"]

    # encode each source in F0-F4
    enc = {sid: {} for sid in src_ids}
    for i, sid in enumerate(src_ids):
        base = ("### Source problem\n" + str(prob.get(sid, ""))[:2500] +
                "\n\n### A correct solution (for your understanding only)\n```python\n"
                + str(solves.get(sid, {}).get("code", ""))[:2500] + "\n```\n\n")
        for fk, (nm, instr) in FORMATS.items():
            out = gpt4omini(base + "TASK: " + instr + " Do not reference any other problem. Output only the guidance.")
            enc[sid][fk] = ("### Retrieved guidance (%s) from a PREVIOUS, DIFFERENT solved problem "
                            "(read-only; not this problem's solution/tests)\n" % nm) + out.strip()
        if (i + 1) % 10 == 0:
            print("[R13] encoded %d/%d sources" % (i + 1, len(src_ids)))

    # assemble per-target memory files: {relevant, shuffled} x F0..F4
    rel = asg["relevant_source"]; shuf = asg["shuffled_source"]; tgts = asg["covered_targets"]
    os.makedirs(A, exist_ok=True)
    for fk in FORMATS:
        mr = {t: enc[rel[t]][fk] for t in tgts if rel.get(t) in enc}
        ms = {t: enc[shuf[t]][fk] for t in tgts if shuf.get(t) in enc}
        json.dump(mr, open("%s/memory_%sR.json" % (A, fk), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        json.dump(ms, open("%s/memory_%sS.json" % (A, fk), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump({sid: {k: len(v) for k, v in e.items()} for sid, e in enc.items()},
              open(A + "/encoding_lengths.json", "w", encoding="utf-8"), indent=1)
    print("[R13] built %d formats x {R,S} memory files for %d targets, %d sources" % (len(FORMATS), len(tgts), len(src_ids)))


if __name__ == "__main__":
    main()
