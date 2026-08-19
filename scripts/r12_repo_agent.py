#!/usr/bin/env python3
"""REALBENCH-R12 §10 — SWE-PolyBench repository agent with the OpenAI reader (gpt-5.6-terra via the Responses API,
function-calling). Reuses the EXACT R7 harness (tools, Docker extract, official grader, patch format, tool policy,
budgets) by importing r7_repo_agent; only the model-call layer is the Responses API instead of Solar chat.

Env: R12_INSTANCE_ID, R12_CSV, R12_POLYBENCH, OPENAI_API_KEY, R12_MODEL(=gpt-5.6-terra), R12_EFFORT(=medium),
R12_MAX_TURNS(=40), R12_OUT. No memory (D0 is a no-memory band audit). One trajectory, no result-conditioned repair.
"""
import os, sys, json, time, urllib.request, urllib.error
# NOTE: do NOT wrap sys.stdout here — importing r7_repo_agent already sets the utf-8 TextIOWrapper; wrapping twice
# closes the underlying buffer ("I/O operation on closed file").

# feed R7's module-level env from R12_* so we can import & reuse its machinery unchanged
os.environ.setdefault("R7_INSTANCE_ID", os.environ["R12_INSTANCE_ID"])
os.environ.setdefault("R7_CSV", os.environ["R12_CSV"])
os.environ.setdefault("R7_POLYBENCH", os.environ["R12_POLYBENCH"])
os.environ.setdefault("R7_MAX_TURNS", os.environ.get("R12_MAX_TURNS", "40"))
os.environ.setdefault("R7_WALLCLOCK_S", os.environ.get("R12_WALLCLOCK_S", "1700"))
os.environ.setdefault("UPSTAGE_API_KEY", "unused-openai-path")  # r7 import requires it; call_solar is never used
sys.path.insert(0, "scripts")
import r7_repo_agent as R7  # noqa: E402
import pandas as pd  # noqa: E402

INST = R7.INST
MODEL = os.environ.get("R12_MODEL", "gpt-5.6-terra")
EFFORT = os.environ.get("R12_EFFORT", "medium")
ARM = os.environ.get("R12_ARM", "M0")
OUT = os.environ.get("R12_OUT", f"agent_{INST}.json")
MEM = {}
if os.environ.get("R12_MEMORY_JSON") and os.path.isfile(os.environ["R12_MEMORY_JSON"]):
    MEM = json.load(open(os.environ["R12_MEMORY_JSON"], encoding="utf-8"))
API_KEY = os.environ["OPENAI_API_KEY"]
BASE = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
MAX_TURNS = R7.MAX_TURNS
DEADLINE_S = R7.DEADLINE_S
PER_TURN_OUT = int(os.environ.get("R12_PER_TURN_OUT", "6000"))


def responses_tools():
    """Convert R7 chat-completions tools to Responses-API flat function tools."""
    out = []
    for t in R7.TOOLS:
        f = t["function"]
        out.append({"type": "function", "name": f["name"], "description": f.get("description", ""),
                    "parameters": f.get("parameters", {"type": "object", "properties": {}})})
    return out


def call_openai(input_items, tools, previous_id=None):
    import random
    body = {"model": MODEL, "input": input_items, "tools": tools, "tool_choice": "auto",
            "reasoning": {"effort": EFFORT}, "max_output_tokens": PER_TURN_OUT, "store": True}
    if previous_id:
        body["previous_response_id"] = previous_id
    data = json.dumps(body).encode()
    last = None
    for attempt in range(8):
        try:
            req = urllib.request.Request(BASE + "/responses", data=data,
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=240) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as ex:
            last = f"HTTP {ex.code}: {ex.read()[:150]}"
            if ex.code in (429, 500, 502, 503, 504):
                time.sleep(min(60, 5 * (2 ** attempt)) + random.uniform(0, 5)); continue
            raise
        except Exception as ex:
            last = str(ex)[:120]; time.sleep(min(60, 5 * (2 ** attempt)) + random.uniform(0, 5))
    raise RuntimeError(f"openai call failed: {last}")


def parse_output(resp):
    """Return (function_calls[list of {name,args,call_id}], text)."""
    fcs, text = [], ""
    for item in (resp.get("output") or []):
        if item.get("type") == "function_call":
            try:
                args = json.loads(item.get("arguments") or "{}")
            except Exception:
                args = {}
            fcs.append({"name": item.get("name"), "args": args, "call_id": item.get("call_id")})
        elif item.get("type") == "message":
            for c in (item.get("content") or []):
                if c.get("type") in ("output_text", "text"):
                    text += c.get("text", "")
    return fcs, text


def main():
    df = pd.read_csv(R7.CSV)
    row = df[df["instance_id"] == INST].iloc[0].to_dict()
    t0 = time.time()
    terminal = "ok"; resolved = None; err = None
    tokens = {"input": 0, "output": 0, "reasoning": 0}; turns = 0; patch = ""
    img = digest = None
    try:
        img, digest, _ = R7.extract_repo(row)
        sys_prompt = (
            "You are an expert software engineer fixing a real bug in a repository. STRICT budget of "
            f"{MAX_TURNS} tool calls, ONE attempt.\n\nREQUIRED WORKFLOW:\n"
            "1. Locate the buggy code FAST with search() (keywords/symbols from the issue), read generously.\n"
            "2. As soon as located (~10 calls), FIX it — PREFER replace_lines(path,start,end,new_content) using "
            "read_file line numbers. Reading alone fixes nothing.\n3. After editing, call submit.\n"
            "You do NOT have the test suite; write a correct general fix. Do not edit test files.")
        mem = (MEM.get(INST, "") or "") if ARM != "M0" else ""
        if mem:
            sys_prompt += ("\n\n[RETRIEVED MEMORY — read-only guidance from a previous, DIFFERENT resolved issue; "
                           "it does NOT contain this issue's solution or tests]\n" + mem[:8000])
        tools = responses_tools()
        input_items = [{"role": "developer", "content": sys_prompt},
                       {"role": "user", "content": f"Repository issue to fix (instance {INST}, language {row['language']}):\n\n{row['problem_statement']}"}]
        prev = None; explore = 0; last_sig = None; rep = 0
        while turns < MAX_TURNS and (time.time() - t0) < DEADLINE_S:
            turns += 1
            allowed = {t["function"]["name"] for t in R7.tools_for(turns, bool(R7.EDITED))}
            offered = [t for t in responses_tools() if t["name"] in allowed]
            resp = call_openai(input_items, offered, previous_id=prev)
            prev = resp.get("id")
            u = resp.get("usage", {}) or {}
            tokens["input"] += u.get("input_tokens", 0); tokens["output"] += u.get("output_tokens", 0)
            tokens["reasoning"] += (u.get("output_tokens_details", {}) or {}).get("reasoning_tokens", 0)
            fcs, text = parse_output(resp)
            if not fcs:
                if R7.EDITED:
                    print(f"[{INST}] turn {turns}: no tool_call after editing -> done."); break
                input_items = [{"role": "user", "content": "You made NO edit and called no tool. You MUST call "
                                "replace_lines/edit_file/create_file to implement the fix now, then submit."}]
                continue
            input_items = []  # next turn carries only the function_call_output items (previous_id chains state)
            done = False
            for fc in fcs:
                fn = fc["name"]; args = fc["args"]
                if fn in ("list_dir", "search"):
                    explore += 1
                if fn != "submit" and fn not in allowed:
                    result = f"'{fn}' is disabled now — read the ONE relevant file then edit_file/replace_lines, or submit."
                elif fn == "list_dir" and explore > 12:
                    result = "Exploration budget exhausted. Use search or read_file then edit. Stop listing directories."
                elif fn == "submit" and not R7.EDITED:
                    result = "You cannot submit — you made NO edit. Implement the fix first, THEN submit."
                elif fn == "submit":
                    result = "submitted"; done = True
                else:
                    try:
                        result = R7.TOOLS_IMPL[fn](**args)
                    except Exception as ex:
                        result = f"tool error: {ex}"
                left = MAX_TURNS - turns
                suffix = f"\n[budget: {left} calls left; edits: {len(R7.EDITED)}]" if fn != "submit" else ""
                input_items.append({"type": "function_call_output", "call_id": fc["call_id"],
                                    "output": str(result)[:R7.MAX_OUT] + suffix})
                print(f"[{INST}] turn {turns}: {fn}({ {k: str(v)[:36] for k, v in list(args.items())[:2]} }) -> {str(result)[:70]}")
                sig = fn + json.dumps(args, sort_keys=True)[:150]
                rep = rep + 1 if sig == last_sig else 0; last_sig = sig
                if rep >= 2:
                    input_items.append({"role": "user", "content": "You are repeating the same call. Re-read the file for exact current text, or try a different edit."}); rep = 0
            if turns in (8, 15, 22, 30) and not R7.EDITED:
                input_items.append({"role": "user", "content": f"STOP READING ({turns} calls, 0 edits). NEXT action MUST be an edit, then submit."})
            if done:
                print(f"[{INST}] submitted at turn {turns}; edited={sorted(R7.EDITED)}"); break
        patch = R7.build_model_patch()
        if not patch.strip():
            terminal = "empty_patch"
        resolved, grader_rc = R7.grade(patch, row)
        if resolved is None:
            terminal = "grader_no_result"
    except Exception as ex:
        terminal = "infra_error"; err = f"{type(ex).__name__}: {ex}"[:250]

    result = {"instance_id": INST, "language": row.get("language"), "repo": row.get("repo"), "arm": ARM,
              "model": MODEL, "effort": EFFORT, "image_digest": digest, "resolved": resolved,
              "terminal_state": terminal, "error": err, "turns": turns, "edited_files": sorted(R7.EDITED),
              "patch_bytes": len(patch), "tokens": tokens, "secs": round(time.time() - t0, 1)}
    json.dump(result, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    open(OUT + ".patch", "w", encoding="utf-8").write(patch)
    print(f"[{INST}] RESULT resolved={resolved} terminal={terminal} turns={turns} edited={len(R7.EDITED)}")
    sys.exit(0)


if __name__ == "__main__":
    main()
