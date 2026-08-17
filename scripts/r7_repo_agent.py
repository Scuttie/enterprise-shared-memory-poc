#!/usr/bin/env python3
"""REALBENCH-R7 — SWE-PolyBench repository agent (one instance per invocation).

Path (per §4/§10): pull official GHCR image -> extract repo @ base_commit -> solar-pro3 tool-calling agent
(temperature 0, one trajectory, no result-conditioned repair) with an OPTIONAL injected memory view ->
model_patch = git diff of edited files -> official run_evaluation.py grades resolved -> durable evidence json.

The agent NEVER sees F2P/P2P/test_patch/gold patch (they are not in the base_commit tree and are applied only
evaluator-side). Memory (for M1-M4) is injected as a read-only text block in the system prompt; for G1/M0 it is
empty. Exit 0 always (terminal state recorded in the json); a non-resolved task is a valid outcome, not an error.

Env: R7_INSTANCE_ID, R7_CSV, R7_OUT, R7_POLYBENCH (path to cloned harness), UPSTAGE_API_KEY,
     R7_MODEL(=solar-pro3-260323), R7_MAX_TURNS(=40), R7_MEMORY_FILE(optional), R7_ARM(=M0).
"""
import os, sys, io, json, subprocess, time, urllib.request, urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

INST = os.environ["R7_INSTANCE_ID"]
CSV = os.environ["R7_CSV"]
OUT = os.environ.get("R7_OUT", f"agent_{INST}.json")
POLY = os.environ["R7_POLYBENCH"]
API_KEY = os.environ["UPSTAGE_API_KEY"]
MODEL = os.environ.get("R7_MODEL", "solar-pro3-260323")
MAX_TURNS = int(os.environ.get("R7_MAX_TURNS", "40"))
ARM = os.environ.get("R7_ARM", "M0")
MEM_FILE = os.environ.get("R7_MEMORY_FILE", "")
BASE_URL = "https://api.upstage.ai/v1"
WORK = os.path.abspath("agent_work")
REPO = os.path.join(WORK, "repo")
MAX_OUT = 6000   # per-tool output char cap
DEADLINE_S = int(os.environ.get("R7_WALLCLOCK_S", "1500"))

import pandas as pd


def sh(cmd, cwd=None, timeout=600):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def extract_repo(row):
    img = f"ghcr.io/timesler/swe-polybench.eval.x86_64.{INST.lower()}:latest"
    print(f"[{INST}] pulling {img}")
    rc, o, e = sh(["docker", "pull", img], timeout=1800)
    assert rc == 0, f"pull failed: {e[-500:]}"
    rc, digest, _ = sh(["docker", "inspect", "--format", "{{index .RepoDigests 0}}", img])
    digest = digest.strip()
    rc, workdir, _ = sh(["docker", "inspect", "--format", "{{.Config.WorkingDir}}", img])
    workdir = workdir.strip() or "/"
    # tag as the harness's local image name so run_evaluation reuses it (no re-pull / no base-image build)
    local_name = f"polybench_{str(row['language']).lower()}_{INST.lower()}"
    sh(["docker", "tag", img, local_name])
    rc, cid, e = sh(["docker", "create", img, "tail", "-f", "/dev/null"])
    assert rc == 0, f"create failed: {e[-300:]}"
    cid = cid.strip()
    os.makedirs(WORK, exist_ok=True)
    sh(["rm", "-rf", REPO]); os.makedirs(REPO, exist_ok=True)
    rc, o, e = sh(["docker", "cp", f"{cid}:{workdir}/.", REPO], timeout=600)
    sh(["docker", "rm", "-f", cid])
    assert rc == 0, f"cp failed: {e[-300:]}"
    # ensure a git baseline so we can diff
    if not os.path.isdir(os.path.join(REPO, ".git")):
        sh(["git", "init", "-q"], cwd=REPO); sh(["git", "add", "-A"], cwd=REPO)
        sh(["git", "-c", "user.email=a@b.c", "-c", "user.name=r7", "commit", "-qm", "base"], cwd=REPO)
    return img, digest, workdir


# ---------- tools (operate on REPO, bounded, path-guarded) ----------
def _safe(path):
    # models often pass absolute-style paths ("/src/...") or "./..."; treat everything as repo-relative
    rel = str(path).strip().lstrip("/").lstrip("\\")
    if rel.startswith("./"):
        rel = rel[2:]
    p = os.path.abspath(os.path.join(REPO, rel))
    if not (p == REPO or p.startswith(REPO + os.sep)):
        raise ValueError("path escapes repo; use a repo-relative path like 'src/transformers/trainer.py'")
    return p


def t_list_dir(path="."):
    p = _safe(path)
    if not os.path.isdir(p):
        return f"not a dir: {path}"
    out = []
    for e in sorted(os.listdir(p))[:300]:
        full = os.path.join(p, e)
        out.append(e + ("/" if os.path.isdir(full) else ""))
    return "\n".join(out)[:MAX_OUT]


def t_read_file(path, start_line=1, end_line=None):
    p = _safe(path)
    if not os.path.isfile(p):
        return f"not a file: {path}"
    lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
    s = max(1, int(start_line))
    e = min(len(lines), int(end_line) if end_line else s + 150)  # generous default window
    body = "\n".join(f"{i+1}\t{lines[i]}" for i in range(s - 1, e))
    return body[:MAX_OUT] or "(empty range)"


def t_search(pattern, path="."):
    p = _safe(path)
    rc, o, _ = sh(["grep", "-rnI", "--max-count=5", pattern, p], timeout=60)
    o = o.replace(REPO + os.sep, "")
    return ("\n".join(o.splitlines()[:80]) or "(no matches)")[:MAX_OUT]


EDITED = set()


def t_edit_file(path, old_string, new_string):
    p = _safe(path)
    if not os.path.isfile(p):
        return f"not a file: {path}"
    txt = open(p, encoding="utf-8", errors="replace").read()
    if txt.count(old_string) == 0:
        return "old_string not found"
    if txt.count(old_string) > 1:
        return f"old_string not unique ({txt.count(old_string)} matches); add context"
    open(p, "w", encoding="utf-8").write(txt.replace(old_string, new_string, 1))
    EDITED.add(os.path.relpath(p, REPO).replace(os.sep, "/"))
    return "ok"


def t_create_file(path, content):
    p = _safe(path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(content)
    EDITED.add(os.path.relpath(p, REPO).replace(os.sep, "/"))
    return "ok"


TOOLS_IMPL = {"list_dir": t_list_dir, "read_file": t_read_file, "search": t_search,
              "edit_file": t_edit_file, "create_file": t_create_file}

TOOLS = [
    {"type": "function", "function": {"name": "list_dir", "description": "List entries of a directory in the repo.",
      "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a file (line-numbered).",
      "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "search", "description": "grep -rn a regex within a path.",
      "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "edit_file", "description": "Replace an exact unique old_string with new_string in a file.",
      "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}}, "required": ["path", "old_string", "new_string"]}}},
    {"type": "function", "function": {"name": "create_file", "description": "Create a new file with content.",
      "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "submit", "description": "Finish: the fix is complete.",
      "parameters": {"type": "object", "properties": {}}}},
]


def trim_history(messages, keep=22):
    """Bound context: keep system + initial user + a recent tail, without orphaning a 'tool' message
    (a tool result must follow its assistant tool_call, or the API rejects it)."""
    if len(messages) <= keep + 2:
        return messages
    head = messages[:2]  # system + initial user issue
    tail = messages[-keep:]
    while tail and tail[0].get("role") == "tool":
        tail = tail[1:]
    return head + tail


def tools_for(turns, edited):
    """Progressively force action: if the model keeps exploring without editing, remove the broad exploration
    tools so it must read-then-edit, and finally must edit/submit. A forced imperfect edit is a fair attempt
    (resolved by the official grader); endless reading is a scaffold artifact."""
    names = None
    if not edited and turns > 30:
        names = {"read_file", "edit_file", "create_file", "submit"}
    elif not edited and turns > 24:
        names = {"read_file", "search", "edit_file", "create_file", "submit"}
    if names is None:
        return TOOLS
    return [t for t in TOOLS if t["function"]["name"] in names]


def call_solar(messages, tools=None):
    import random
    body = json.dumps({"model": MODEL, "messages": messages, "tools": tools or TOOLS,
                       "tool_choice": "auto", "temperature": 0}).encode()
    last = None
    for attempt in range(10):
        try:
            req = urllib.request.Request(BASE_URL + "/chat/completions", data=body,
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as ex:
            hdr = getattr(ex, "headers", None)
            ra = None
            try:
                ra = float(hdr.get("Retry-After")) if hdr and hdr.get("Retry-After") else None
            except Exception:
                ra = None
            last = f"HTTP {ex.code}"
            if ex.code in (429, 403, 500, 502, 503, 504):
                wait = ra if ra else min(60, 5 * (2 ** attempt))
                wait += random.uniform(0, 5)  # jitter (plain Python CI script; random is available)
                time.sleep(wait); continue
            raise
        except Exception as ex:
            last = str(ex)[:120]; time.sleep(min(60, 5 * (2 ** attempt)) + random.uniform(0, 5))
    raise RuntimeError(f"solar call failed after retries: {last}")


def build_model_patch():
    if not EDITED:
        return ""
    sh(["git", "add", "-A", "--"] + list(EDITED), cwd=REPO)
    rc, diff, _ = sh(["git", "-c", "core.autocrlf=false", "diff", "--cached", "--"] + list(EDITED), cwd=REPO)
    return diff


def grade(model_patch, row):
    """Grade via the official harness modules directly (imported), reusing the locally-tagged prebuilt image.
    This is the exact path validated in the §2 G0 smoke (8/8 all languages); it avoids run_evaluation.py's
    Java base-image *build* fallback that fails in CI. Applies test_patch then model_patch in a fresh container,
    runs the official test_command, parses with the repo's official parser, and scores F2P/P2P."""
    import ast as _ast
    from poly_bench_evaluation.docker_utils import DockerManager
    from poly_bench_evaluation.scoring import instance_level_scoring
    from poly_bench_evaluation.constants import DEFAULT_TIMEOUT, JAVA_TIMEOUT, REPO_TO_PARSER_CLASS
    import poly_bench_evaluation.parsers as all_parsers
    import docker as _docker

    def _to_list(v):
        if isinstance(v, list):
            return v
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return []
        return _ast.literal_eval(v)

    language = row["language"]; repo = row["repo"]
    image_id = f"polybench_{language.lower()}_{INST.lower()}"
    parser_class_name = REPO_TO_PARSER_CLASS[repo]
    f2p = _to_list(row["F2P"]); p2p = _to_list(row["P2P"])
    client = _docker.from_env()
    dm = DockerManager(image_id=image_id, delete_image=False, client=client)
    if not dm.check_image_local(local_image_name=image_id):
        if not dm.try_pull_prebuilt_image(INST):
            return None, 1
    dm.create_container()
    try:
        if dm.apply_patch_to_container(patch_content=row["test_patch"], patch_type="test") != 0:
            return None, 2
        if model_patch.strip():
            if dm.apply_patch_to_container(patch_content=model_patch, patch_type="code") != 0:
                # model patch failed to apply -> official semantics: not resolved
                return False, 0
        run_timeout = JAVA_TIMEOUT if language.lower() == "java" else DEFAULT_TIMEOUT
        dm.docker_run(test_command=row["test_command"], timeout=run_timeout)
        logs = "\n".join(dm.run_logs)
        result = getattr(all_parsers, parser_class_name)(test_content=logs).parse()
        out = instance_level_scoring(instance_id=INST, result=result, f2p=f2p, p2p=p2p,
                                     patch_applied=True, generation=True)
        return bool(getattr(out, "resolved", False)), 0
    finally:
        try:
            dm.__del__()
        except Exception:
            pass


def main():
    import random
    time.sleep(random.uniform(0, 30))  # startup stagger to desync concurrent jobs' API bursts
    df = pd.read_csv(CSV)
    row = df[df["instance_id"] == INST].iloc[0].to_dict()
    t0 = time.time()
    terminal = "ok"; resolved = None; err = None
    tokens = {"prompt": 0, "completion": 0}; turns = 0; grader_rc = None; patch = ""
    img = digest = workdir = None
    try:
        img, digest, workdir = extract_repo(row)
        mem = ""
        if MEM_FILE and os.path.isfile(MEM_FILE):
            mem = open(MEM_FILE, encoding="utf-8", errors="replace").read()[:8000]
        sys_prompt = (
            "You are an expert software engineer fixing a real bug in a repository. You have a STRICT budget of "
            f"{MAX_TURNS} tool calls and ONE attempt (temperature 0).\n\n"
            "REQUIRED WORKFLOW:\n"
            "1. Locate the buggy code FAST: use search() with distinctive keywords/symbols from the issue "
            "(class names, error strings, function names) instead of navigating directories one by one with "
            "list_dir. Read generously (150+ lines), not 10 at a time.\n"
            "2. As soon as you have located the cause (usually within ~10 calls), you MUST fix it with edit_file "
            "(or create_file). Reading alone fixes nothing and wastes your budget.\n"
            "3. After editing, call submit.\n\n"
            "You do NOT have access to the test suite; write a correct, general fix to the source code. Do not edit "
            "test files. It is far better to make a reasonable edit than to keep reading. If unsure, make your best "
            "edit and submit.")
        if mem:
            sys_prompt += "\n\n[RETRIEVED MEMORY — read-only context]\n" + mem
        messages = [{"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"Repository issue to fix (instance {INST}, language {row['language']}):\n\n{row['problem_statement']}"}]
        last_sig = None; rep = 0; explore_calls = 0
        while turns < MAX_TURNS and (time.time() - t0) < DEADLINE_S:
            turns += 1
            messages = trim_history(messages)
            offered = tools_for(turns, bool(EDITED))
            allowed_names = {t["function"]["name"] for t in offered}
            resp = call_solar(messages, tools=offered)
            u = resp.get("usage", {}); tokens["prompt"] += u.get("prompt_tokens", 0); tokens["completion"] += u.get("completion_tokens", 0)
            msg = resp["choices"][0]["message"]
            messages.append(msg)
            tcs = msg.get("tool_calls") or []
            if not tcs:
                print(f"[{INST}] turn {turns}: no tool_call -> stop. content={str(msg.get('content'))[:120]}")
                break  # model produced final text without a tool call -> stop
            done = False
            for tc in tcs:
                fn = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except Exception:
                    args = {}
                # enforce the (possibly restricted) tool set — Upstage does not reject out-of-list tool calls,
                # so a lost model can keep navigating forever unless we refuse disallowed tools ourselves.
                if fn in ("list_dir", "search"):
                    explore_calls += 1
                if fn != "submit" and fn not in allowed_names:
                    result = (f"'{fn}' is disabled now — you have explored enough. Read the ONE relevant file "
                              "with read_file, then fix it with edit_file/create_file, or call submit.")
                elif fn == "list_dir" and explore_calls > 12:
                    result = ("Exploration budget exhausted. Use search to find the relevant symbol, or read_file "
                              "the file you already found, then edit_file. Stop listing directories.")
                elif fn == "submit":
                    result = "submitted"; done = True
                else:
                    try:
                        result = TOOLS_IMPL[fn](**args)
                    except Exception as ex:
                        result = f"tool error: {ex}"
                arg_brief = {k: (str(v)[:40]) for k, v in list(args.items())[:2]}
                print(f"[{INST}] turn {turns}: {fn}({arg_brief}) -> {str(result)[:80].replace(chr(10),' ')}")
                left = MAX_TURNS - turns
                suffix = f"\n[budget: {left} tool calls left; edits made so far: {len(EDITED)}]" if fn != "submit" else ""
                messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": str(result)[:MAX_OUT] + suffix})
                sig = fn + "|" + json.dumps(args, sort_keys=True)[:200]
                rep = rep + 1 if sig == last_sig else 0
                last_sig = sig
                if rep >= 2:
                    messages.append({"role": "user", "content":
                        "You are repeating the same call. Change your approach: re-read the file to get the EXACT "
                        "current text for edit_file.old_string (it must match verbatim and be unique), or try a "
                        "different edit. Do not repeat the identical call again."})
                    rep = 0
            # escalating nudge if the model keeps reading without editing
            if turns in (8, 15, 22, 30) and not EDITED:
                messages.append({"role": "user", "content":
                    f"STOP READING. You have made {turns} calls and 0 edits, with {MAX_TURNS-turns} left. "
                    "Your NEXT action MUST be edit_file or create_file to implement the fix, then submit. "
                    "Make your best-judgment edit now even if not fully certain."})
            if done:
                print(f"[{INST}] submitted at turn {turns}; edited={sorted(EDITED)}")
                break
        patch = build_model_patch()
        if not patch.strip():
            terminal = "empty_patch"
        resolved, grader_rc = grade(patch, row)
        if resolved is None:
            terminal = "grader_no_result"
    except subprocess.TimeoutExpired as ex:
        terminal = "timeout"; err = str(ex)[:300]
    except AssertionError as ex:
        terminal = "infra_error"; err = str(ex)[:300]
    except Exception as ex:
        terminal = "error"; err = f"{type(ex).__name__}: {ex}"[:300]

    result = {"instance_id": INST, "language": row.get("language"), "repo": row.get("repo"),
              "arm": ARM, "model": MODEL, "image": img, "image_digest": digest,
              "resolved": resolved, "terminal_state": terminal, "error": err,
              "turns": turns, "edited_files": sorted(EDITED), "patch_bytes": len(patch),
              "tokens": tokens, "grader_rc": grader_rc, "secs": round(time.time() - t0, 1)}
    json.dump(result, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    # persist the patch + transcript separately (durable evidence)
    open(OUT + ".patch", "w", encoding="utf-8").write(patch)
    print(f"[{INST}] RESULT resolved={resolved} terminal={terminal} turns={turns} edited={len(EDITED)} secs={result['secs']}")
    sys.exit(0)


if __name__ == "__main__":
    main()
