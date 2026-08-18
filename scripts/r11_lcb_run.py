#!/usr/bin/env python3
"""REALBENCH-R11 — LiveCodeBench code-generation runner (one batch of question_ids per invocation).

Uses the OFFICIAL LiveCodeBench artifacts (imported, not reimplemented): dataset loader
(lcb_runner.benchmarks.code_generation), code extraction (lcb_runner.utils.extraction_utils.extract_code), and
grader (lcb_runner.evaluation.compute_code_generation_metrics.codegen_metrics, Pass@1). Reader = solar-pro3
(temperature 0, ONE generation, no repair, fixed token budget). Optional per-task memory (M1/M2/M3) is injected as
a read-only block BEFORE the problem; it never contains any target solution or target tests.

Env: R11_RELEASE(release_v6), R11_QIDS(comma question_ids), R11_ARM(M0/M1/M2/M3), R11_MEMORY_JSON(optional
qid->memory text), R11_OUT, UPSTAGE_API_KEY, R11_MODEL(solar-pro3-260323), R11_MAX_TOKENS.
ITT: an infrastructure terminal failure is recorded as passed=false (never silently dropped).
"""
import os, sys, io, json, time, urllib.request, urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

RELEASE = os.environ.get("R11_RELEASE", "release_v6")
QIDS = [q for q in os.environ.get("R11_QIDS", "").split(",") if q]
ARM = os.environ.get("R11_ARM", "M0")
OUT = os.environ.get("R11_OUT", "lcb_out.json")
API_KEY = os.environ["UPSTAGE_API_KEY"]
MODEL = os.environ.get("R11_MODEL", "solar-pro3-260323")
MAX_TOKENS = int(os.environ.get("R11_MAX_TOKENS", "4096"))
BASE_URL = "https://api.upstage.ai/v1"
MEM = {}
if os.environ.get("R11_MEMORY_JSON") and os.path.isfile(os.environ["R11_MEMORY_JSON"]):
    MEM = json.load(open(os.environ["R11_MEMORY_JSON"], encoding="utf-8"))

from lcb_runner.benchmarks.code_generation import load_code_generation_dataset
from lcb_runner.utils.extraction_utils import extract_code
from lcb_runner.lm_styles import LMStyle
from lcb_runner.evaluation.compute_code_generation_metrics import codegen_metrics


def build_prompt(p, memory):
    """Standard LiveCodeBench code-generation prompt (functional vs stdin), optionally prefixed by a memory block."""
    has_starter = bool(getattr(p, "starter_code", "") and p.starter_code.strip())
    parts = []
    if memory:
        parts.append("### Retrieved lesson from a PREVIOUS, DIFFERENT solved problem (read-only guidance; it does "
                     "NOT contain this problem's solution or tests):\n" + memory + "\n")
    parts.append("You will be given a competitive programming problem. Generate a correct, efficient Python 3 "
                 "solution. Think briefly, then output the final solution in a single ```python code block.\n")
    parts.append("### Problem\n" + p.question_content.strip())
    if has_starter:
        parts.append("\n### Starter code (complete this; keep the signature)\n```python\n"
                     + p.starter_code.strip() + "\n```")
        parts.append("\nReturn the completed solution in one ```python block.")
    else:
        parts.append("\nRead input from standard input and write the answer to standard output. "
                     "Return the full program in one ```python block.")
    return "\n".join(parts)


def call_solar(prompt):
    import random
    body = json.dumps({"model": MODEL, "temperature": 0, "max_tokens": MAX_TOKENS,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    last = None
    for attempt in range(8):
        try:
            req = urllib.request.Request(BASE_URL + "/chat/completions", data=body,
                headers={"Authorization": "Bearer %s" % API_KEY, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read())
            return d["choices"][0]["message"]["content"], d.get("usage", {}), d.get("model", MODEL)
        except urllib.error.HTTPError as ex:
            last = "HTTP %s" % ex.code
            if ex.code in (429, 500, 502, 503, 504):
                time.sleep(min(60, 5 * (2 ** attempt)) + random.uniform(0, 5)); continue
            raise
        except Exception as ex:
            last = str(ex)[:100]; time.sleep(min(60, 5 * (2 ** attempt)) + random.uniform(0, 5))
    raise RuntimeError("solar failed: %s" % last)


def main():
    import random
    time.sleep(random.uniform(0, 20))
    allp = load_code_generation_dataset(release_version=RELEASE)
    if os.environ.get("R11_DUMP") == "1":
        universe = [{"question_id": p.question_id, "contest_date": str(getattr(p, "contest_date", "")),
                     "platform": str(getattr(p, "platform", "")), "difficulty": str(getattr(p, "difficulty", "")),
                     "has_starter": bool(getattr(p, "starter_code", "") and p.starter_code.strip())} for p in allp]
        json.dump({"release": RELEASE, "n": len(universe), "universe": universe},
                  open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print("[R11] dumped %d tasks -> %s" % (len(universe), OUT)); return
    by_id = {p.question_id: p for p in allp}
    part_path = "artifacts/livecodebench_r11/task_partition.json"
    if QIDS == ["TARGETS"] or QIDS == ["SOURCES"]:
        part = json.load(open(part_path, encoding="utf-8"))
        key = "main_target" if QIDS == ["TARGETS"] else "source_pool"
        ids = part[key]["ids"]
        off = int(os.environ.get("R11_OFFSET", "0")); lim = int(os.environ.get("R11_LIMIT", "0") or "0")
        ids = ids[off:off + lim] if lim else ids[off:]
        targets = [by_id[q] for q in ids if q in by_id]
    elif QIDS:
        targets = [by_id[q] for q in QIDS if q in by_id]
    else:
        limit = int(os.environ.get("R11_LIMIT", "20"))
        targets = sorted(allp, key=lambda p: p.question_id)[:limit]  # deterministic smoke selection
    print("[R11] release=%s arm=%s targets=%d (dataset=%d)" % (RELEASE, ARM, len(targets), len(allp)))

    WRONG = os.environ.get("R11_WRONG") == "1"  # grader-discrimination check: inject a deliberately wrong body
    gens, samples, meta = [], [], []
    for p in targets:
        rec = {"question_id": p.question_id, "contest_date": str(getattr(p, "contest_date", "")),
               "difficulty": str(getattr(p, "difficulty", "")), "platform": str(getattr(p, "platform", "")),
               "arm": ARM, "terminal": "ok", "returned_model": None, "usage": {}}
        if WRONG:
            code = "import sys\ndef f(*a, **k):\n    return None\nprint(-987654321)\n"  # passes nothing
            rec["returned_model"] = "WRONG_INJECTED"
        else:
            try:
                out, usage, rmodel = call_solar(build_prompt(p, MEM.get(p.question_id, "") if ARM != "M0" else ""))
                code = extract_code(out, LMStyle.OpenAIChat)
                rec["returned_model"] = rmodel; rec["usage"] = usage; rec["code_len"] = len(code)
            except Exception as ex:
                code = ""; rec["terminal"] = "infra_error"; rec["error"] = str(ex)[:200]
        gens.append([code])
        samples.append(p.get_evaluation_sample())
        meta.append(rec)

    # official grading (Pass@1). ITT: empty/failed code grades as fail, not dropped.
    passed = [False] * len(targets)
    try:
        res = codegen_metrics(samples, gens, k_list=[1], num_process_evaluate=4, timeout=6)
        metrics = res[0]; results = res[1]
        detail = (metrics or {}).get("detail", {}).get("pass@1", {})
        print("[R11] official metrics pass@1 aggregate=%s" % (metrics or {}).get("pass@1"))
        for i in range(len(targets)):
            # prefer the official per-problem pass@1 detail (0.0/1.0 for a single generation)
            if str(i) in detail or i in detail:
                passed[i] = float(detail.get(str(i), detail.get(i, 0.0))) >= 1.0
            else:
                r = results.get(i) if isinstance(results, dict) else results[i]
                g0 = r[0] if r else []
                flat = g0 if isinstance(g0, (list, tuple)) else [g0]
                passed[i] = len(flat) > 0 and all((x is True or x == 1) for x in flat)
    except Exception as ex:
        print("[R11] grader error: %s" % str(ex)[:300])
        for m in meta:
            if m["terminal"] == "ok":
                m["terminal"] = "grader_error"
    for i, m in enumerate(meta):
        m["passed"] = bool(passed[i])

    n = len(meta); npass = sum(m["passed"] for m in meta)
    out = {"release": RELEASE, "arm": ARM, "n": n, "n_pass": npass,
           "pass_at_1": round(npass / n, 4) if n else None, "results": meta}
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print("[R11] arm=%s Pass@1=%s (%d/%d)" % (ARM, out["pass_at_1"], npass, n))


if __name__ == "__main__":
    main()
