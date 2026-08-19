#!/usr/bin/env python3
"""REALBENCH-R14 — SWE-bench Verified repository agent (one instance/invocation). Reuses R7's tool machinery
(imported) but with the SWE-bench Docker image, the official `swebench` grader, gpt-4o-mini (chat/completions +
tools), and RAW worked-example memory (a real prior same-repo resolved issue: source problem + source gold diff),
NOT a distilled abstraction. The agent never sees the TARGET's gold patch/tests.

Env: R14_INSTANCE_ID, R14_CSV, R14_OUT, OPENAI_API_KEY, R14_MODEL(gpt-4o-mini-2024-07-18), R14_MAX_TURNS(40),
R14_ARM(M0), R14_MEMORY_JSON(optional qid->worked-example text). Exit 0 always; terminal state recorded.
"""
import os, sys, json, time, subprocess, urllib.request, urllib.error, glob, random

os.environ.setdefault("R7_INSTANCE_ID", os.environ["R14_INSTANCE_ID"])
os.environ.setdefault("R7_CSV", os.environ["R14_CSV"])
os.environ.setdefault("R7_POLYBENCH", os.environ.get("R14_POLY", "."))
os.environ.setdefault("R7_MAX_TURNS", os.environ.get("R14_MAX_TURNS", "40"))
os.environ.setdefault("R7_WALLCLOCK_S", os.environ.get("R14_WALLCLOCK_S", "1700"))
os.environ.setdefault("UPSTAGE_API_KEY", "unused")
sys.path.insert(0, "scripts")
import r7_repo_agent as R7  # noqa: E402
import pandas as pd  # noqa: E402

INST = R7.INST
MODEL = os.environ.get("R14_MODEL", "gpt-4o-mini-2024-07-18")
OUT = os.environ.get("R14_OUT", f"agent_{INST}.json")
ARM = os.environ.get("R14_ARM", "M0")
API_KEY = os.environ["OPENAI_API_KEY"]
BASE = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
DATASET = "SWE-bench/SWE-bench_Verified"
MEM = {}
if os.environ.get("R14_MEMORY_JSON") and os.path.isfile(os.environ["R14_MEMORY_JSON"]):
    MEM = json.load(open(os.environ["R14_MEMORY_JSON"], encoding="utf-8"))


def sh(cmd, timeout=1800, cwd=None):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    return p.returncode, p.stdout, p.stderr


def image_name():
    return "swebench/sweb.eval.x86_64.%s:latest" % INST.replace("__", "_1776_")


def extract_repo(row):
    img = image_name()
    print(f"[{INST}] pulling {img}")
    rc, o, e = sh(["docker", "pull", img], timeout=1800)
    assert rc == 0, f"pull failed: {e[-400:]}"
    rc, digest, _ = sh(["docker", "inspect", "--format", "{{index .RepoDigests 0}}", img])
    rc, cid, e = sh(["docker", "create", img, "tail", "-f", "/dev/null"])
    assert rc == 0, f"create failed: {e[-300:]}"
    cid = cid.strip()
    # SWE-bench repos live at /testbed
    sh(["rm", "-rf", R7.REPO]); os.makedirs(R7.REPO, exist_ok=True)
    rc, o, e = sh(["docker", "cp", f"{cid}:/testbed/.", R7.REPO], timeout=600)
    sh(["docker", "rm", "-f", cid])
    assert rc == 0, f"cp failed: {e[-300:]}"
    if not os.path.isdir(os.path.join(R7.REPO, ".git")):
        sh(["git", "init", "-q"], cwd=R7.REPO); sh(["git", "add", "-A"], cwd=R7.REPO)
        sh(["git", "-c", "user.email=a@b.c", "-c", "user.name=r14", "commit", "-qm", "base"], cwd=R7.REPO)
    return img, digest.strip()


def call_openai_chat(messages, tools=None):
    body = json.dumps({"model": MODEL, "messages": messages, "tools": tools or R7.TOOLS,
                       "tool_choice": "auto", "temperature": 0}).encode()
    last = None
    for attempt in range(8):
        try:
            req = urllib.request.Request(BASE + "/chat/completions", data=body,
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as ex:
            last = f"HTTP {ex.code}"
            if ex.code in (429, 500, 502, 503, 504):
                time.sleep(min(60, 5 * (2 ** attempt)) + random.uniform(0, 5)); continue
            raise
        except Exception as ex:
            last = str(ex)[:100]; time.sleep(min(60, 5 * (2 ** attempt)) + random.uniform(0, 5))
    raise RuntimeError(f"openai failed: {last}")


def grade(model_patch):
    if not model_patch.strip():
        return False, "empty"
    preds = os.path.abspath("preds.jsonl")
    open(preds, "w", encoding="utf-8").write(json.dumps(
        {"instance_id": INST, "model_name_or_path": "r14", "model_patch": model_patch}) + "\n")
    rid = "r14-" + INST.replace("__", "-")[:40]
    rc, o, e = sh([sys.executable, "-m", "swebench.harness.run_evaluation",
                   "--dataset_name", DATASET, "--predictions_path", preds, "--run_id", rid,
                   "--max_workers", "1", "--instance_ids", INST, "--timeout", "1800"],
                  timeout=2400)
    print(f"[{INST}] swebench rc={rc}\n{o[-500:]}\n{e[-300:]}")
    # per-instance report.json under logs/run_evaluation/<rid>/r14/<inst>/report.json
    for rp in glob.glob(f"logs/run_evaluation/{rid}/**/report.json", recursive=True) + glob.glob("**/report.json", recursive=True):
        try:
            d = json.load(open(rp, encoding="utf-8"))
        except Exception:
            continue
        if INST in d:
            return bool(d[INST].get("resolved")), "graded"
        if "resolved" in d:
            return bool(d["resolved"]), "graded"
    # final summary report r14.<rid>.json
    for rp in glob.glob(f"r14.{rid}.json") + glob.glob("*.json"):
        try:
            d = json.load(open(rp, encoding="utf-8"))
        except Exception:
            continue
        if isinstance(d.get("resolved_ids"), list):
            return (INST in d["resolved_ids"]), "graded"
    return None, "no_report"


def main():
    time.sleep(random.uniform(0, 20))
    df = pd.read_csv(R7.CSV)
    row = df[df["instance_id"] == INST].iloc[0].to_dict()
    t0 = time.time()
    terminal = "ok"; resolved = None; err = None; turns = 0; patch = ""; digest = None
    tokens = {"prompt": 0, "completion": 0}
    try:
        img, digest = extract_repo(row)
        mem = (MEM.get(INST, "") or "") if ARM != "M0" else ""
        sys_prompt = (
            "You are an expert software engineer fixing a real GitHub issue in a Python repository. STRICT budget "
            f"of {R7.MAX_TURNS} tool calls, ONE attempt.\nWORKFLOW: 1) locate the buggy code with search(); read "
            "generously. 2) as soon as located, FIX it with replace_lines (preferred) or edit_file. 3) call submit. "
            "You do NOT have the tests; write a correct general fix. Do not edit test files.")
        if mem:
            sys_prompt += ("\n\n[RETRIEVED MEMORY — a REAL prior resolved issue in THIS repository and the actual "
                           "fix that was applied; read-only worked example, not this issue's solution]\n" + mem[:9000])
        messages = [{"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"Issue to fix (instance {INST}, repo {row['repo']}):\n\n{row['problem_statement'][:9000]}"}]
        last_sig = None; rep = 0; explore = 0
        while turns < R7.MAX_TURNS and (time.time() - t0) < R7.DEADLINE_S:
            turns += 1
            messages = R7.trim_history(messages)
            offered = R7.tools_for(turns, bool(R7.EDITED))
            allowed = {t["function"]["name"] for t in offered}
            resp = call_openai_chat(messages, tools=offered)
            u = resp.get("usage", {}); tokens["prompt"] += u.get("prompt_tokens", 0); tokens["completion"] += u.get("completion_tokens", 0)
            msg = resp["choices"][0]["message"]; messages.append(msg)
            tcs = msg.get("tool_calls") or []
            if not tcs:
                if R7.EDITED:
                    break
                messages.append({"role": "user", "content": "You made NO edit and called no tool. Call replace_lines/edit_file now, then submit."}); continue
            done = False
            for tc in tcs:
                fn = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except Exception:
                    args = {}
                if fn in ("list_dir", "search"):
                    explore += 1
                if fn != "submit" and fn not in allowed:
                    result = f"'{fn}' disabled now — read the relevant file then edit, or submit."
                elif fn == "list_dir" and explore > 12:
                    result = "Exploration budget exhausted; use search/read_file then edit."
                elif fn == "submit" and not R7.EDITED:
                    result = "You cannot submit — no edit yet. Fix first, then submit."
                elif fn == "submit":
                    result = "submitted"; done = True
                else:
                    try:
                        result = R7.TOOLS_IMPL[fn](**args)
                    except Exception as ex:
                        result = f"tool error: {ex}"
                messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                                 "content": (str(result)[:R7.MAX_OUT] + (f"\n[left: {R7.MAX_TURNS-turns}; edits: {len(R7.EDITED)}]" if fn != 'submit' else ''))})
                sig = fn + json.dumps(args, sort_keys=True)[:150]
                rep = rep + 1 if sig == last_sig else 0; last_sig = sig
                if rep >= 2:
                    messages.append({"role": "user", "content": "Repeating the same call — re-read the file for exact text or try a different edit."}); rep = 0
            if turns in (8, 15, 22, 30) and not R7.EDITED:
                messages.append({"role": "user", "content": f"STOP READING ({turns} calls, 0 edits). Next action MUST be an edit, then submit."})
            if done:
                break
        patch = R7.build_model_patch()
        if not patch.strip():
            terminal = "empty_patch"
        resolved, gnote = grade(patch)
        if resolved is None:
            terminal = "grader_no_result"
    except Exception as ex:
        terminal = "infra_error"; err = f"{type(ex).__name__}: {ex}"[:250]

    result = {"instance_id": INST, "repo": row.get("repo"), "arm": ARM, "model": MODEL, "image_digest": digest,
              "resolved": resolved, "terminal_state": terminal, "error": err, "turns": turns,
              "edited_files": sorted(R7.EDITED), "patch_bytes": len(patch), "tokens": tokens,
              "secs": round(time.time() - t0, 1)}
    json.dump(result, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    open(OUT + ".patch", "w", encoding="utf-8").write(patch)
    print(f"[{INST}] RESULT resolved={resolved} terminal={terminal} turns={turns} edited={len(R7.EDITED)}")
    sys.exit(0)


if __name__ == "__main__":
    main()
