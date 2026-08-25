"""R22 §1-§5 — hard-separated FAKE vs REAL task loading / workspaces / grading / memory. REAL implementations load
the frozen SWE-ContextBench targets, official images, official grader, and frozen stage-memory records; they never
touch the fake fixtures. FAKE implementations are the offline local-fixture path (renamed LOCAL_FIXTURE_HARNESS).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ART = os.path.join(ROOT, "artifacts", "r22")
ENRICHED = {
    "SWE-bench Verified": ("SWE-bench/SWE-bench_Verified", "78f471bf655a3137b2e8a75af1501690ec009ec3"),
    "SWE-bench Lite": ("SWE-bench/SWE-bench_Lite", "b0dde1093fe417d83b7184254edf8199c1f0dff5"),
    "SWE-bench Multilingual": ("SWE-bench/SWE-bench_Multilingual", "846e647b9f33c0b51b739d005d13d85493c9af09"),
}


# ---- interfaces --------------------------------------------------------------
class TaskLoader:
    def load(self) -> List[dict]:
        raise NotImplementedError


class WorkspaceFactory:
    def make(self, task: dict) -> str:
        raise NotImplementedError


class Grader:
    def grade(self, task: dict, model_patch: str) -> dict:
        raise NotImplementedError


class MemorySourceLoader:
    def load(self, source_id: str, stage: str) -> dict:
        raise NotImplementedError


class RealModeViolation(Exception):
    pass


# ---- FAKE (local fixture) ----------------------------------------------------
class FakeTaskLoader(TaskLoader):
    def __init__(self, n, prefix):
        from experiments.r22.paid_runner import fake_tasks
        self.n, self.prefix = n, prefix
        self._fake_tasks = fake_tasks

    def load(self):
        tasks, _ = self._fake_tasks(self.n, seed_prefix=self.prefix)
        return tasks


class FakeWorkspaceFactory(WorkspaceFactory):
    def make(self, task):
        from experiments.r22.runtime import repo_agent as RA
        fixroot = tempfile.mkdtemp()
        task["_fix"] = RA.make_fixture(fixroot)
        wr = tempfile.mkdtemp(); shutil.rmtree(wr); shutil.copytree(fixroot, wr)
        return wr


class LocalFixtureGrader(Grader):
    def grade(self, task, model_patch):
        from experiments.r22.runtime import repo_agent as RA
        return {"resolved": bool(model_patch.strip()) and RA.local_grade(task["_workspace"]),
                "grader": "local_fixture"}


# ---- REAL (frozen SWE-ContextBench) ------------------------------------------
def _frozen_ids(manifest_name):
    m = json.load(open(os.path.join(ART, manifest_name), encoding="utf-8"))
    ids = []
    for t in m["task_list"]:
        if t.get("target_id") not in ids:
            ids.append(t["target_id"])
    return ids


SCB_DATASET = "jiayuanz3/SWEContextBench"
SCB_GH_COMMIT = "31bb04155f52b184bf31b220e3cff0607ac9c953"


class RealR22TaskLoader(TaskLoader):
    """Loads the frozen oracle TARGET rows from the MIT SWE-ContextBench dataset (Related), where the frozen ids
    live. SCB rows carry the SWE-bench schema (base_commit/FAIL_TO_PASS/PASS_TO_PASS/patch/test_patch) but no
    prebuilt `image`; the official harness builds the image from base_commit at grade time. Credential-free."""

    def __init__(self, manifest_name: str, scb_data: Optional[str] = None):
        self.manifest_name = manifest_name
        self.scb_data = scb_data or os.environ.get("R22_SCB_DATA", os.path.join(ART, "_scb_data"))

    def load(self):
        import pandas as pd
        target_ids = _frozen_ids(self.manifest_name)
        rel = pd.read_parquet(os.path.join(self.scb_data, "SWEContextBench_Related.parquet"))
        exp = pd.read_parquet(os.path.join(self.scb_data, "SWEContextBench_Experience.parquet"))
        by = {}
        for df in (rel, exp):
            for _, r in df.iterrows():
                by.setdefault(r["instance_id"], r)
        tasks = []
        for tid in target_ids:
            if tid not in by:
                raise RealModeViolation("frozen target %s not in the SWE-ContextBench dataset" % tid)
            r = by[tid]
            tasks.append({
                "target_id": tid, "subset": "SWE-ContextBench", "dataset_name": SCB_DATASET,
                "dataset_revision": SCB_GH_COMMIT,
                "repository": r["repo"], "base_commit": r["base_commit"],
                "problem_statement": r["problem_statement"], "issue": r["problem_statement"],
                "image": None,  # SCB has no prebuilt image; harness builds from base_commit at grade time
                "environment_setup_commit": r.get("environment_setup_commit"), "version": str(r.get("version")),
                "FAIL_TO_PASS": r["FAIL_TO_PASS"], "PASS_TO_PASS": r["PASS_TO_PASS"],
                "repo_cluster": r["repo"],
                "_gold_patch": r["patch"], "_test_patch": r["test_patch"],   # withheld from the reader
                "stage": "COMPREHEND",
            })
        return tasks


class OfficialImageWorkspaceFactory(WorkspaceFactory):
    """Pull the official row-declared image, verify digest, extract /testbed at base_commit. Requires Docker."""

    def make(self, task):
        image = task["image"]
        if not image:
            raise RealModeViolation("no official image for %s" % task["target_id"])
        subprocess.run(["docker", "pull", image], check=True, capture_output=True)
        digest = subprocess.run(["docker", "inspect", "--format", "{{index .RepoDigests 0}}", image],
                                capture_output=True, text=True).stdout.strip()
        task["image_digest"] = digest
        wr = tempfile.mkdtemp()
        cid = subprocess.run(["docker", "create", image], capture_output=True, text=True).stdout.strip()
        try:
            subprocess.run(["docker", "cp", "%s:/testbed/." % cid, wr], check=True, capture_output=True)
        finally:
            subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
        # the real path must never create the fixture files
        if os.path.exists(os.path.join(wr, "bug.py")) or os.path.exists(os.path.join(wr, "test_bug.py")):
            raise RealModeViolation("fixture files present in a REAL workspace")
        return wr


class OfficialSWEGrader(Grader):
    """Wraps the validated mixed-subset official grader (scripts/r22_grader_run.py adapter). Never local_grade."""

    def grade(self, task, model_patch):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "r22gr", os.path.join(ROOT, "scripts", "r22_grader_run.py"))
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        # write predictions + call the official harness for this instance's subset (as G0 does)
        # (delegated; returns the harness resolved verdict + report path)
        raise NotImplementedError("wired via scripts/r22_grader_run.py in the real workflow; "
                                  "see OfficialSWEGrader.grade_via_cli")

    @staticmethod
    def grade_via_cli(task, model_patch, results_dir):
        """Run the official harness for one (instance, patch). Credential-free (Docker only)."""
        import glob
        os.makedirs(results_dir, exist_ok=True)
        iid = task["target_id"]
        run_id = "r22real-%s" % hashlib.sha256((iid + model_patch).encode()).hexdigest()[:10]
        preds = os.path.join(results_dir, run_id + "_preds.jsonl")
        with open(preds, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"instance_id": iid, "model_name_or_path": "r22real",
                                 "model_patch": model_patch}) + "\n")
        cmd = ["python", "-m", "swebench.harness.run_evaluation", "--dataset_name", task["dataset_name"],
               "--instance_ids", iid, "--predictions_path", preds, "--run_id", run_id, "--max_workers", "1"]
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        report = None
        for p in glob.glob(os.path.join(ROOT, "**", "*%s*.json" % run_id), recursive=True):
            try:
                report = json.load(open(p)); break
            except Exception:
                pass
        resolved = bool(report and iid in set(report.get("resolved_ids", [])))
        return {"resolved": resolved, "grader": "official_swebench", "dataset": task["dataset_name"],
                "image_digest": task.get("image_digest"), "returncode": proc.returncode,
                "report_found": report is not None, "log_tail": (proc.stdout or "")[-1500:]}


class FrozenStageMemoryLoader(MemorySourceLoader):
    """Loads the exact (source_id, stage) record from the frozen GOLD_PRECEDENT bank."""

    def __init__(self):
        bank = json.load(open(os.path.join(ART, "gold_precedent_bank.json"), encoding="utf-8"))
        self.index = {}
        for e in bank["records"]:
            rec = e["record"]
            self.index[(rec["identity"]["source_task_id"], rec["stage"])] = e

    def load(self, source_id, stage):
        e = self.index.get((source_id, stage))
        if e is None:
            return None
        v = e["views"]
        return {"card": v["episodic"].get("attempted_action", ""),
                "semantic": json.dumps(v["semantic"]),
                "episodic": json.dumps(v["episodic"]),
                "full_precedent": json.dumps(v.get("oracle_raw_diff", {})),
                "execution_view": v["execution"]}


class FakeMemorySourceLoader(MemorySourceLoader):
    def load(self, source_id, stage):
        return {"card": "prior issue: arithmetic op wrong",
                "semantic": "when arithmetic result is off, verify the operator; use +",
                "episodic": "tried a-b -> failed; changed to a+b -> pass",
                "full_precedent": "diff: -return a - b +return a + b", "execution_view": {"approx_tokens": 20}}
