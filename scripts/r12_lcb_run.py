#!/usr/bin/env python3
"""REALBENCH-R12 — LiveCodeBench runner with the OpenAI reader (reuses R11 EXACTLY: same prompt, extraction,
official grader, arm memory; only the reader/provider differs). Solar stays the writer; OpenAI is the reader.

Env: R12_MODEL, R12_FAMILY(gpt5.6|gpt4o), R12_EFFORT, R12_ARM(M0/M1/M2/M3), R12_TASKSET(BAND|TARGETS),
R12_MEMORY_JSON(optional for arms), R12_OUT, R12_MAX_TOKENS(=4096, frozen R11 budget), OPENAI_API_KEY.
ITT: an infra terminal failure counts as passed=false. Identical prompt across readers (no per-model rewrite).
"""
import os, sys, io, json, time, asyncio
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "src")
import httpx

from lcb_runner.benchmarks.code_generation import load_code_generation_dataset
from lcb_runner.utils.extraction_utils import extract_code
from lcb_runner.lm_styles import LMStyle
from lcb_runner.evaluation.compute_code_generation_metrics import codegen_metrics
from enterprise_memory.providers.openai_responses import OpenAIResponsesProvider
from enterprise_memory.providers.base import ModelRequest, ProviderError


def build_prompt(p, memory):
    """EXACT copy of scripts/r11_lcb_run.py::build_prompt (verbatim; identical prompt across readers). Copied
    rather than imported because r11_lcb_run reads UPSTAGE_API_KEY at module import (Solar writer)."""
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

RELEASE = os.environ.get("R12_RELEASE", "release_v6")
MODEL = os.environ["R12_MODEL"]
FAMILY = os.environ.get("R12_FAMILY", "gpt5.6")
EFFORT = os.environ.get("R12_EFFORT", "medium")
ARM = os.environ.get("R12_ARM", "M0")
TASKSET = os.environ.get("R12_TASKSET", "BAND")
OUT = os.environ.get("R12_OUT", "r12_out.json")
MAX_TOKENS = int(os.environ.get("R12_MAX_TOKENS", "4096"))
MEM = {}
if os.environ.get("R12_MEMORY_JSON") and os.path.isfile(os.environ["R12_MEMORY_JSON"]):
    MEM = json.load(open(os.environ["R12_MEMORY_JSON"], encoding="utf-8"))

# per-USD rates (frozen at run date; overridable) — estimate only
RATE_IN = float(os.environ.get("R12_RATE_IN", "0.0"))
RATE_OUT = float(os.environ.get("R12_RATE_OUT", "0.0"))


class EnvSecrets:
    def get(self, name):
        return os.environ.get(name)


def taskset_ids():
    if TASKSET == "BAND":
        return json.load(open("artifacts/openai_reader_r12/band_tasks.json", encoding="utf-8"))["ids"]
    if TASKSET == "R13COVERED":
        return json.load(open("artifacts/repr_r13/r13_assignments.json", encoding="utf-8"))["covered_targets"]
    return json.load(open("artifacts/livecodebench_r11/task_partition.json", encoding="utf-8"))["main_target"]["ids"]


async def main():
    allp = load_code_generation_dataset(release_version=RELEASE)
    by_id = {p.question_id: p for p in allp}
    ids = [q for q in taskset_ids() if q in by_id]
    targets = [by_id[q] for q in ids]
    print("[R12] model=%s arm=%s taskset=%s n=%d" % (MODEL, ARM, TASKSET, len(targets)))

    gens, samples, meta = [], [], []
    async with httpx.AsyncClient() as client:
        prov = OpenAIResponsesProvider("https://api.openai.com/v1", MODEL, EnvSecrets(), family=FAMILY,
                                       reasoning_effort=EFFORT, http_client=client)
        for p in targets:
            rec = {"question_id": p.question_id, "contest_date": str(getattr(p, "contest_date", "")),
                   "difficulty": str(getattr(p, "difficulty", "")), "platform": str(getattr(p, "platform", "")),
                   "arm": ARM, "terminal": "ok", "returned_model": None, "usage": {}}
            mem = MEM.get(p.question_id, "") if ARM != "M0" else ""
            prompt = build_prompt(p, mem)
            try:
                resp, call = await prov.generate(ModelRequest(messages=[{"role": "user", "content": prompt}],
                                                              max_output_tokens=MAX_TOKENS),
                                                 logical_request_id="r12-%s-%s-%s" % (MODEL, ARM, p.question_id))
                code = extract_code(resp.text, LMStyle.OpenAIChat)
                rec["returned_model"] = resp.returned_model
                rec["usage"] = {"input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
                                "total_tokens": resp.total_tokens,
                                "reasoning_tokens": getattr(call, "reasoning_tokens", None),
                                "cached_input_tokens": getattr(call, "cached_input_tokens", None)}
                rec["latency_s"] = call.total_latency
                rec["code_len"] = len(code)
                rec["malformed"] = (len(code.strip()) == 0)
            except ProviderError as ex:
                code = ""; rec["terminal"] = "infra_error"; rec["error"] = str(ex)[:150]
                rec["final_status"] = getattr(getattr(ex, "record", None), "final_status", None)
            except Exception as ex:
                code = ""; rec["terminal"] = "infra_error"; rec["error"] = "%s:%s" % (type(ex).__name__, str(ex)[:120])
            gens.append([code]); samples.append(p.get_evaluation_sample()); meta.append(rec)

    passed = [False] * len(targets)
    try:
        res = codegen_metrics(samples, gens, k_list=[1], num_process_evaluate=4, timeout=6)
        metrics, results = res[0], res[1]
        detail = (metrics or {}).get("detail", {}).get("pass@1", {})
        for i in range(len(targets)):
            if str(i) in detail or i in detail:
                passed[i] = float(detail.get(str(i), detail.get(i, 0.0))) >= 1.0
            else:
                r = results.get(i) if isinstance(results, dict) else results[i]
                g0 = r[0] if r else []
                flat = g0 if isinstance(g0, (list, tuple)) else [g0]
                passed[i] = len(flat) > 0 and all((x is True or x == 1) for x in flat)
    except Exception as ex:
        print("[R12] grader error: %s" % str(ex)[:200])
        for m in meta:
            if m["terminal"] == "ok":
                m["terminal"] = "grader_error"
    for i, m in enumerate(meta):
        m["passed"] = bool(passed[i])

    n = len(meta); npass = sum(m["passed"] for m in meta)
    exec_ok = sum(1 for m in meta if m["terminal"] == "ok")
    malformed = sum(1 for m in meta if m.get("malformed"))
    tin = sum((m["usage"].get("input_tokens") or 0) for m in meta)
    tout = sum((m["usage"].get("output_tokens") or 0) for m in meta)
    out = {"model": MODEL, "family": FAMILY, "effort": EFFORT, "arm": ARM, "taskset": TASKSET,
           "n": n, "n_pass": npass, "pass_at_1": round(npass / n, 4) if n else None,
           "exec_rate": round(exec_ok / n, 4) if n else None, "malformed": malformed,
           "returned_models": sorted(set(m["returned_model"] for m in meta if m["returned_model"])),
           "input_tokens": tin, "output_tokens": tout,
           "est_cost_usd": round(tin / 1e6 * RATE_IN + tout / 1e6 * RATE_OUT, 4) if (RATE_IN or RATE_OUT) else None,
           "results": meta}
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print("[R12] model=%s arm=%s Pass@1=%s exec=%s malformed=%d (%d/%d)"
          % (MODEL, ARM, out["pass_at_1"], out["exec_rate"], malformed, npass, n))


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
