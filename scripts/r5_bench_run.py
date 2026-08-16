"""REALBENCH-R5 — generalized SkillsBench runner over BenchFlow (ACP agent + LiteLLM model routing). Handles:
  - oracle reproduction (AGENT=oracle) — gold-only gate (no model)
  - A0 NO_SKILL calibration (AGENT=claude-agent-acp, MODEL=openai/solar-pro2-251215, SKILL_MODE=no-skill) — PAID
  - A1/A2/A3 (SKILL_MODE=with-skill + SKILLS_DIR) — PAID confirmatory arms (only after approval)
Reads reward + tokens from the BenchFlow `jobs/` tree. Env: SKILLSBENCH_DIR, R5_TASKS, AGENT, MODEL, SKILL_MODE,
SKILLS_DIR, ARM_LABEL, R5_TASK_TIMEOUT. Writes artifacts/swe_skills_r5/bench_run_<ARM_LABEL>.json.
"""
import glob
import json
import os
import re
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.environ.get("SKILLSBENCH_DIR", os.path.join(REPO, "skillsbench"))
AGENT = os.environ.get("AGENT", "oracle")
MODEL = os.environ.get("MODEL", "")
SKILL_MODE = os.environ.get("SKILL_MODE", "no-skill")
SKILLS_DIR = os.environ.get("SKILLS_DIR", "")
ARM = os.environ.get("ARM_LABEL", AGENT)
TASKS = [t.strip() for t in os.environ.get("R5_TASKS", "").split(",") if t.strip()]
OUT = os.path.join(REPO, "artifacts", "swe_skills_r5", "bench_run_%s.json" % ARM)


def _run(cmd, timeout):
    try:
        p = subprocess.run(cmd, cwd=SB, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + "\n" + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def _latest_job_summary():
    """Find the newest jobs/*/summary.json (BenchFlow writes rewards/tokens there)."""
    cands = sorted(glob.glob(os.path.join(SB, "jobs", "*", "summary.json")), key=os.path.getmtime)
    return cands[-1] if cands else None


def _reward_from_blob(blob):
    m = re.search(r"['\"]?reward['\"]?\s*[:=]\s*([01](?:\.\d+)?)", blob)
    return float(m.group(1)) if m else None


def main():
    results = {}
    for tid in TASKS:
        tdir = os.path.join("tasks", tid)
        cmd = ["bench", "eval", "run", "--tasks-dir", tdir, "--agent", AGENT, "--sandbox", "docker",
               "--skill-mode", SKILL_MODE]
        if MODEL:
            cmd += ["--model", MODEL]
        if SKILL_MODE == "with-skill" and SKILLS_DIR:
            cmd += ["--skills-dir", SKILLS_DIR.replace("<id>", tid)]
        t0 = time.time()
        rc, blob = _run(cmd, int(os.environ.get("R5_TASK_TIMEOUT", "2400")))
        reward = _reward_from_blob(blob)
        tokens = None
        summ = _latest_job_summary()
        sdata = {}
        if summ:
            try:
                sdata = json.load(open(summ, encoding="utf-8"))
            except Exception:
                sdata = {}
            if reward is None:
                for key in ("reward", "mean_reward", "score"):
                    if key in json.dumps(sdata):
                        m = re.search(r'"%s"\s*:\s*([01](?:\.\d+)?)' % key, json.dumps(sdata))
                        if m:
                            reward = float(m.group(1)); break
        passed = reward == 1 or (reward is None and re.search(r"\[PASS\]|1/1 \(100", blob) is not None)
        # capture the newest result.json diagnostics (api_error_info, tool-call counts) for debugging the agent
        diag = {}
        rj = sorted(glob.glob(os.path.join(SB, "jobs", "*", "**", "result.json"), recursive=True),
                    key=os.path.getmtime)
        if rj:
            try:
                rjd = json.load(open(rj[-1], encoding="utf-8"))
                for k in ("api_error_info", "transport_error_info", "error", "tool_calls", "num_tool_calls",
                          "reward", "usage", "tokens"):
                    if k in json.dumps(rjd):
                        m = re.search(r'"%s"\s*:\s*("[^"]*"|\{[^}]*\}|\[[^\]]*\]|[0-9.]+)' % k, json.dumps(rjd))
                        if m:
                            diag[k] = m.group(1)[:400]
            except Exception:
                pass
        results[tid] = {"rc": rc, "reward": reward, "passed": bool(passed), "secs": round(time.time() - t0, 1),
                        "tail": blob[-1500:], "diag": diag,
                        "summary_path": (os.path.basename(os.path.dirname(summ)) if summ else None)}
        print("== %s [%s] rc=%s reward=%s passed=%s (%.0fs)" %
              (tid, ARM, rc, reward, passed, results[tid]["secs"]), flush=True)
    npass = sum(1 for r in results.values() if r["passed"])
    n = len(results)
    out = {"arm": ARM, "agent": AGENT, "model": MODEL, "skill_mode": SKILL_MODE, "n": n, "n_pass": npass,
           "pass_rate": round(npass / n, 4) if n else 0.0, "tasks": TASKS, "results": results}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8", newline="\n"), indent=2, sort_keys=True)
    print("R5 [%s] pass_rate=%.4f (%d/%d)" % (ARM, out["pass_rate"], npass, n), flush=True)


if __name__ == "__main__":
    main()
