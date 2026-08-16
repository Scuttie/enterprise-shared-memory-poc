"""REALBENCH-R5-A0 GATE — SkillsBench v1.1 ORACLE reproduction (gold-only; NO paid model). For each selected
task, run the official BenchFlow runner with `--agent oracle` and confirm the oracle solution passes the task's
own verifier (reward==1). This is the SkillsBench analogue of R3's DS-1000 100% gold reproduction and closes
audit conditions 3 (oracle passes verifier) + 4 (Docker reproducible). Learns/parses the bench result format
defensively. Env: SKILLSBENCH_DIR (clone), R5_TASKS (comma list). Writes artifacts/swe_skills_r5/oracle_repro.json.
"""
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.environ.get("SKILLSBENCH_DIR", os.path.join(REPO, "skillsbench"))
OUT = os.path.join(REPO, "artifacts", "swe_skills_r5", "oracle_repro.json")
TASKS = [t.strip() for t in os.environ.get("R5_TASKS", "dialogue-parser,python-scala-translation").split(",") if t.strip()]


def _run(cmd, timeout):
    try:
        p = subprocess.run(cmd, cwd=SB, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + "\n" + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def _find_reward():
    """Search the skillsbench tree for a freshly written verifier reward file (1/0)."""
    hits = []
    for root, _dirs, files in os.walk(SB):
        for f in files:
            if f == "reward.txt" or f.endswith("reward.txt"):
                try:
                    hits.append((os.path.join(root, f), open(os.path.join(root, f)).read().strip()))
                except Exception:
                    pass
    return hits


def main():
    results = {}
    for tid in TASKS:
        tdir = os.path.join("tasks", tid)
        # 1) schema check (fast, no docker)
        rc_chk, out_chk = _run(["bench", "tasks", "check", tdir], 300)
        # 2) oracle run through the real verifier in docker
        rc_run, out_run = _run(["bench", "eval", "run", "--tasks-dir", tdir, "--agent", "oracle",
                                "--sandbox", "docker"], int(os.environ.get("R5_TASK_TIMEOUT", "1800")))
        blob = out_run + "\n" + out_chk
        # defensive reward parse: reward.txt, or "reward": 1, or reward=1, or pass/PASSED markers
        reward = None
        # match "reward": 1.0 / 'reward': 1.0 / reward=1 / Rewards: {'reward': 1.0}
        m = re.search(r"['\"]?reward['\"]?\s*[:=]\s*([01](?:\.\d+)?)", blob)
        if m:
            reward = float(m.group(1))
        rewards = _find_reward()
        if reward is None and rewards:
            try:
                reward = max(float(r[1]) for r in rewards if r[1] in ("0", "1", "0.0", "1.0"))
            except ValueError:
                pass
        passed = (reward == 1) or (reward is None and rc_run == 0 and re.search(r"\b(PASSED|reward=1|1/1 passed)\b", blob))
        results[tid] = {"schema_check_rc": rc_chk, "oracle_run_rc": rc_run, "reward": reward,
                        "passed": bool(passed), "reward_files": rewards[:3],
                        "tail": blob[-1200:]}
        print("== %s == schema_rc=%s oracle_rc=%s reward=%s passed=%s" %
              (tid, rc_chk, rc_run, reward, passed), flush=True)
    npass = sum(1 for r in results.values() if r["passed"])
    out = {"gate": "skillsbench_v11_oracle_reproduction", "n_tasks": len(TASKS), "n_oracle_pass": npass,
           "tasks": TASKS, "results": results,
           "reproduced": npass == len(TASKS) and len(TASKS) > 0}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8", newline="\n"), indent=2, sort_keys=True)
    print("ORACLE REPRO: %d/%d oracle-pass; reproduced=%s" % (npass, len(TASKS), out["reproduced"]), flush=True)
    # do NOT hard-fail the job on non-repro during the exploratory gate — we want the logs/format either way
    if not out["reproduced"]:
        print("NOTE: not all oracle runs reproduced (see tails); this is the audit signal, not a crash", flush=True)


if __name__ == "__main__":
    main()
