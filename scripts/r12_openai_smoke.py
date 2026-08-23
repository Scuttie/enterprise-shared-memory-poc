#!/usr/bin/env python3
"""R12 §5 — live OpenAI provider smoke (+ §2 model availability). Sends EXACTLY 3 fictional code prompts per
candidate model through OpenAIResponsesProvider against the real Responses API, and records model availability
from /v1/models plus per-call accounting. Provider smoke only — NOT benchmark evidence; do not tune from outputs.

Candidates (no substitution): gpt-4o-mini-2024-07-18 (gpt4o), gpt-5.6-luna (gpt5.6/medium),
gpt-5.6-terra (gpt5.6/medium). A candidate that 404s / errors is marked unavailable; never silently replaced.
Env: OPENAI_API_KEY (required). Writes artifacts/openai_reader_r12/provider_smoke.json.
"""
import os, sys, io, json, time, asyncio
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import httpx

sys.path.insert(0, "src")
from enterprise_memory.providers.openai_responses import OpenAIResponsesProvider
from enterprise_memory.providers.base import ModelRequest, ProviderError

BASE = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
KEY = os.environ["OPENAI_API_KEY"]

CANDIDATES = [("gpt-4o-mini-2024-07-18", "gpt4o", None),
              ("gpt-5.6-luna", "gpt5.6", "medium"),
              ("gpt-5.6-terra", "gpt5.6", "medium")]

PROMPTS = [
    "Write a Python function `add(a, b)` that returns the sum of two integers. Return only a ```python code block.",
    "Write a Python function `is_palindrome(s)` returning True iff the string reads the same backwards. ```python only.",
    "Write a Python function `nth_fib(n)` returning the n-th Fibonacci number (0-indexed, nth_fib(0)=0). ```python only.",
]


class EnvSecrets:
    def get(self, name):
        return os.environ.get(name)


def has_code_block(text):
    return "```" in text


def model_list():
    try:
        r = httpx.get(BASE + "/models", headers={"Authorization": "Bearer %s" % KEY}, timeout=60)
        if r.status_code != 200:
            return {"status": r.status_code, "ids": []}
        ids = [m.get("id") for m in r.json().get("data", [])]
        return {"status": 200, "ids": ids}
    except Exception as ex:
        return {"status": "error", "error": type(ex).__name__, "ids": []}


async def smoke_model(model, family, effort):
    out = {"requested_model": model, "family": family, "reasoning_effort": effort, "calls": [],
           "available": None, "returned_model": None}
    async with httpx.AsyncClient() as client:
        prov = OpenAIResponsesProvider(BASE, model, EnvSecrets(), family=family,
                                       reasoning_effort=(effort or "medium"), http_client=client)
        for i, p in enumerate(PROMPTS):
            rec = {"i": i}
            t0 = time.monotonic()
            try:
                resp, call = await prov.generate(ModelRequest(messages=[{"role": "user", "content": p}],
                                                              max_output_tokens=4096), logical_request_id="smoke-%s-%d" % (model, i))
                rec.update({"ok": True, "returned_model": resp.returned_model, "response_id": call.provider_request_id,
                            "finish": call.finish_reason, "extraction": has_code_block(resp.text),
                            "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
                            "total_tokens": resp.total_tokens,
                            "reasoning_tokens": getattr(call, "reasoning_tokens", None),
                            "cached_input_tokens": getattr(call, "cached_input_tokens", None),
                            "latency_s": round(time.monotonic() - t0, 2), "retries": len(call.attempt_records) - 1,
                            "redaction": call.redaction_status})
                out["returned_model"] = resp.returned_model
                out["available"] = True
            except ProviderError as ex:
                rec.update({"ok": False, "error": type(ex).__name__, "detail": str(ex)[:150],
                            "final_status": getattr(getattr(ex, "record", None), "final_status", None),
                            "latency_s": round(time.monotonic() - t0, 2)})
                if out["available"] is None:
                    out["available"] = False
            except Exception as ex:
                rec.update({"ok": False, "error": type(ex).__name__, "detail": str(ex)[:150]})
                if out["available"] is None:
                    out["available"] = False
            out["calls"].append(rec)
    return out


async def main():
    ml = model_list()
    results = []
    for model, family, effort in CANDIDATES:
        r = await smoke_model(model, family, effort)
        r["in_model_list"] = model in ml.get("ids", [])
        results.append(r)
        av = "AVAILABLE" if r["available"] else "UNAVAILABLE"
        print("[R12-smoke] %-26s %s returned=%s in_list=%s" % (model, av, r["returned_model"], r["in_model_list"]))
    gpt56_ok = any(r["available"] for r in results if r["family"] == "gpt5.6")
    summary = {"base_url": BASE, "model_list_status": ml.get("status"),
               "model_list_has": {m: (m in ml.get("ids", [])) for m, _, _ in CANDIDATES},
               "results": results, "at_least_one_gpt56_available": gpt56_ok,
               "decision": ("proceed" if gpt56_ok else "STOP: no GPT-5.6 candidate available (gpt-4o-mini alone insufficient)")}
    os.makedirs("artifacts/openai_reader_r12", exist_ok=True)
    json.dump(summary, open("artifacts/openai_reader_r12/provider_smoke.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    print("[R12-smoke] >=1 GPT-5.6 available:", gpt56_ok, "->", summary["decision"])


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
