#!/usr/bin/env python3
"""REALBENCH-R11 — build the M1/M2/M3 memory maps from VERIFIED source successes.

Inputs (committed): task_partition.json, target_source_candidates.json, and source-solve results
(artifacts/livecodebench_r11/source_solves.json: verified source qid -> {code}). For each target:
  - M1/M3 source = the nearest source in the target's top-K that the reader VERIFIABLY solved (same source ID).
  - Generate two lessons from that source's problem + verified solution via Solar (cached per source):
      plain (M1)      = concise technique + pitfall + verification (2-4 sentences)
      actionable (M3) = algorithm/procedure/preconditions/edge cases/invariants
  - M2 source = a verified source NOT in the target's top-K (unrelated), difficulty-matched to the M1 source;
    M2 memory = that source's PLAIN lesson (same format/position/indicator as M1, ~matched length).
Controls enforced: M1 and M3 share the exact source ID; M1/M2/M3 all inject one plain-or-actionable block at the
same prompt position; M2 is technique-mismatched (outside top-K). No target solution/tests ever enter a memory.

Emits artifacts/livecodebench_r11/memory_{M1,M2,M3}.json (qid->text) + memory_assignments.json (provenance).
Env: R11_RELEASE, UPSTAGE_API_KEY, R11_MODEL, R11_MAX_TOKENS.
"""
import os, sys, io, json, time, urllib.request, urllib.error, hashlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

RELEASE = os.environ.get("R11_RELEASE", "release_v6")
API_KEY = os.environ["UPSTAGE_API_KEY"]
MODEL = os.environ.get("R11_MODEL", "solar-pro3-260323")
BASE_URL = "https://api.upstage.ai/v1"
A = "artifacts/livecodebench_r11"

from lcb_runner.benchmarks.code_generation import load_code_generation_dataset


def call_solar(prompt, max_tokens=1200):
    import random
    body = json.dumps({"model": MODEL, "temperature": 0, "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    last = None
    for attempt in range(8):
        try:
            req = urllib.request.Request(BASE_URL + "/chat/completions", data=body,
                headers={"Authorization": "Bearer %s" % API_KEY, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as ex:
            last = "HTTP %s" % ex.code
            if ex.code in (429, 500, 502, 503, 504):
                time.sleep(min(60, 5 * (2 ** attempt)) + random.uniform(0, 5)); continue
            raise
        except Exception as ex:
            last = str(ex)[:100]; time.sleep(min(60, 5 * (2 ** attempt)) + random.uniform(0, 5))
    raise RuntimeError("solar failed: %s" % last)


def gen_lessons(problem, solution_code):
    prompt = ("Below is a competitive-programming problem and a CORRECT Python solution. Write reusable guidance "
              "for solving SIMILAR future problems. Do NOT mention or assume any other specific problem.\n\n"
              "Return STRICT JSON with two keys:\n"
              '  "plain": 2-4 sentences — the key technique/idea, one common pitfall, and how to verify.\n'
              '  "actionable": a structured lesson with lines for Algorithm (ordered steps), Preconditions, '
              'Edge cases, Invariants.\n\n'
              "### Problem\n" + (problem.question_content or "")[:3500] +
              "\n\n### Correct solution\n```python\n" + (solution_code or "")[:3000] + "\n```")
    out = call_solar(prompt)
    # extract JSON
    import re
    m = re.search(r"\{.*\}", out, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except Exception:
        d = {}
    plain = str(d.get("plain", "")).strip() or out.strip()[:600]
    actionable = str(d.get("actionable", "")).strip() or plain
    return plain, actionable


def main():
    part = json.load(open(A + "/task_partition.json", encoding="utf-8"))
    cand = json.load(open(A + "/target_source_candidates.json", encoding="utf-8"))["candidates"]
    solves = json.load(open(A + "/source_solves.json", encoding="utf-8"))
    verified = {q: v for q, v in solves.items() if v.get("passed")}
    print("[R11] verified sources: %d" % len(verified))
    allp = load_code_generation_dataset(release_version=RELEASE)
    by_id = {p.question_id: p for p in allp}
    diff = {q: str(getattr(by_id[q], "difficulty", "")) for q in by_id}

    lesson_cache = {}  # source_qid -> (plain, actionable)

    def lessons_for(sq):
        if sq not in lesson_cache:
            lesson_cache[sq] = gen_lessons(by_id[sq], verified[sq].get("code", ""))
        return lesson_cache[sq]

    M1, M2, M3, assign = {}, {}, {}, {}
    verified_ids = list(verified.keys())
    for i, tq in enumerate(part["main_target"]["ids"]):
        info = cand.get(tq)
        if not info:
            continue
        topk_ids = [c["source_qid"] for c in info["topk"]]
        rel = next((s for s in topk_ids if s in verified), None)  # nearest VERIFIED source
        if rel is None:
            assign[tq] = {"relevant_source": None, "reason": "no verified source in top-K"}
            continue
        plain, actionable = lessons_for(rel)
        # M2: a verified source OUTSIDE this target's top-K, difficulty-matched to the relevant source
        topk_set = set(topk_ids)
        cand_m2 = [s for s in verified_ids if s not in topk_set and diff.get(s) == diff.get(rel)]
        # deterministic pick: hash(target) to index into the matched pool (no randomness API)
        if not cand_m2:
            cand_m2 = [s for s in verified_ids if s not in topk_set]
        m2src = cand_m2[int(hashlib.sha256(tq.encode()).hexdigest(), 16) % len(cand_m2)] if cand_m2 else None
        m2plain = lessons_for(m2src)[0] if m2src else ""
        M1[tq] = plain; M3[tq] = actionable; M2[tq] = m2plain
        assign[tq] = {"relevant_source": rel, "rel_sim": info["topk"][topk_ids.index(rel)]["sim"],
                      "rel_difficulty": diff.get(rel), "m2_source": m2src, "m2_difficulty": diff.get(m2src),
                      "m1_len": len(plain), "m2_len": len(m2plain), "m3_len": len(actionable)}
        if (i + 1) % 20 == 0:
            print("[R11] processed %d/%d targets (lessons cached=%d)" % (i + 1, len(part["main_target"]["ids"]), len(lesson_cache)))

    for name, mp in [("M1", M1), ("M2", M2), ("M3", M3)]:
        json.dump(mp, open("%s/memory_%s.json" % (A, name), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump({"n_targets_with_memory": len(M1), "n_verified_sources": len(verified),
               "n_lessons_generated": len(lesson_cache), "assignments": assign},
              open(A + "/memory_assignments.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("[R11] memory built: %d targets have M1/M2/M3; %d lessons generated" % (len(M1), len(lesson_cache)))


if __name__ == "__main__":
    main()
